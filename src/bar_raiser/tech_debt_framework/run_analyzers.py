from __future__ import annotations

import asyncio
from argparse import ArgumentParser
from collections import Counter
from logging import getLogger
from os import environ
from typing import TYPE_CHECKING

from aioboto3 import Session
from botocore.exceptions import ClientError
from git.repo import Repo

from bar_raiser.tech_debt_framework.utils import (
    NEW_TECH_DEBT_MESSAGE,
    REGRESSION_TECH_DEBT_CATEGORIES,
    BaseCodeAnalyzer,
    History,
    LeaderBoard,
    PathResults,
    TechDebtCategory,
    get_analyzers,
    get_pr_num_from_commit_message,
)
from bar_raiser.utils.github import (
    create_check_run,
    get_git_repo,
    get_github_repo,
    get_pull_request,
    has_previous_issue_comment,
    initialize_logging,
)
from bar_raiser.utils.slack import post_a_slack_message

if TYPE_CHECKING:
    from git import Commit
    from github.Repository import Repository
    from types_aiobotocore_s3 import S3Client

logger = getLogger(__name__)

CHECK_NAME = "quality-wins-report"
MAX_COMMENT_LENGTH = 65536
RAISE_THE_BAR_LOGIN = "zip-bar-raiser[bot]"
TECH_DEBT_SHOUTOUT_CHANNEL = "C0600000000"


def get_slack_handle_from_github_login(github_login: str) -> str:
    return ""


def trim_to_max_bytes(text: str, max_bytes: int) -> str:
    """
    Trim a string to ensure it's at most max_bytes in UTF-8 encoding.
    If trimming results in a partial character at the end, that character is removed.
    """
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text

    trimmed = encoded[:max_bytes]

    try:
        return trimmed.decode("utf-8")
    except UnicodeDecodeError:
        while trimmed:
            trimmed = trimmed[:-1]
            try:
                return trimmed.decode("utf-8")
            except UnicodeDecodeError:
                continue

    return ""  # Fallback, should not reach here


def get_parser() -> ArgumentParser:
    parser = ArgumentParser()
    parser.add_argument("paths", nargs="*", help="List of paths to run lint rules on.")
    parser.add_argument(
        "--backfill",
        type=int,
        default=None,
        help="number of recent commits to backfill",
    )
    parser.add_argument(
        "--start-hexsha",
        type=str,
        help="A starting commit hexsha to backfill from",
    )
    parser.add_argument(
        "--backfill-leaderboard",
        action="store_true",
        help="backfill 2023 Q3 leaderboard data",
    )
    return parser


def shout_out_contribution(
    github_login: str,
    commit_sha: str,
    contribution_summary: str,
    check_url: str,
    is_backfill: bool,
) -> None:
    if not is_backfill and environ.get("GITHUB_EVENT_NAME", "") == "push":
        slack_handle = get_slack_handle_from_github_login(github_login)
        text = f"""\
🎉 Big Cheers for {slack_handle}! 🎉
A huge shout-out to {slack_handle} for the <https://github.com/Greenbax/evergreen/commit/{commit_sha}|{commit_sha[:7]}> change🌟 {contribution_summary}
Your contributions are now reflected on the Code Quality Award <{check_url}|Leaderboard>!👏
"""
        post_a_slack_message(TECH_DEBT_SHOUTOUT_CHANNEL, text)


async def analyze_contribution_and_create_a_check_run(  # noqa: PLR0917
    git_repo: Repo,
    github_repo: Repository,
    s3: S3Client,
    base_commit: Commit,
    head_commit: Commit,
    paths: list[str],
    analyzers: set[type[BaseCodeAnalyzer]],
    author: str,
    is_backfill: bool,
) -> None:
    (
        delta,
        path_results,
    ) = await PathResults.gen_from_incremental_analysis(
        s3,
        git_repo,
        base_commit,
        head_commit,
        paths,
        analyzers,
    )

    pr_comment_body = ""
    significant_contribution = ""
    pull = get_pull_request()
    try:
        try:
            leaderboard = await LeaderBoard.load_with_commit(s3, base_commit)
        except Exception:
            logger.warning("Failed to load leaderboard from s3.")
            leaderboard = LeaderBoard()
        try:
            history = await History.load_with_commit(s3, base_commit)
        except Exception:
            logger.warning("Failed to load history from s3.")
            history = History()
        summary = path_results.get_markdown_summary(
            delta, author, leaderboard.board.get(author, Counter[TechDebtCategory]())
        )
        leaderboard.add_delta_and_check_contribution(author, delta)
        leaderboard.compute_weighted_score()
        history.add_delta(
            author,
            head_commit.hexsha,
            delta,
            leaderboard.board[author][TechDebtCategory.WEIGHTED_SCORE],
        )
        try:
            await leaderboard.upload_to_s3(s3, head_commit)
        except Exception:
            logger.warning("Failed to upload leaderboard to s3.")
        try:
            await history.upload_to_s3(s3, head_commit)
        except Exception:
            logger.warning("Failed to upload history to s3.")
        summary += leaderboard.get_markdown_summary(author, 1000)
        summary += history.get_markdown_summary(author)
        if (
            leaderboard.tech_debt_regression
            and pull is not None
            and not has_previous_issue_comment(
                pull, RAISE_THE_BAR_LOGIN, NEW_TECH_DEBT_MESSAGE
            )
        ):
            pr_comment_body = f"Hey @{author}, {NEW_TECH_DEBT_MESSAGE}\n{leaderboard.tech_debt_regression}"
        if leaderboard.contribution_summary:
            significant_contribution = leaderboard.contribution_summary

    except ClientError:  # fail to load leaderboard
        summary = path_results.get_markdown_summary(delta, author)
        logger.warning("fail to load leaderboard or history")

    checks = create_check_run(
        repo=github_repo,
        name=CHECK_NAME,
        head_sha=head_commit.hexsha,
        conclusion=(
            "action_required"
            if any(
                val > 0
                for key, val in delta.items()
                if key
                not in ({
                    *REGRESSION_TECH_DEBT_CATEGORIES,
                    TechDebtCategory.WEIGHTED_SCORE,
                })
            )
            else "success"
        ),
        title="Python Tech Debt Report",
        summary=trim_to_max_bytes(summary, MAX_COMMENT_LENGTH),
        annotations=[],
        actions=[],
    )
    if pull and pr_comment_body:
        if checks:
            pr_comment_body += (
                f"\n\n[Check your Tech Debt Contribution]({checks[0].html_url})"
            )
        pull.create_issue_comment(pr_comment_body)
    if significant_contribution:
        shout_out_contribution(
            author,
            head_commit.hexsha,
            significant_contribution,
            checks[0].html_url,
            is_backfill,
        )


async def main() -> None:
    initialize_logging()
    args = get_parser().parse_args()
    analyzers = get_analyzers()
    logger.info(f"Analyzers: {analyzers}")
    session = Session()
    if args.backfill_leaderboard:
        git_repo = Repo()
        processed = 0
        github_repo = get_github_repo()
        # lint-fixme: NoS3ClientRule
        async with session.client(service_name="s3") as s3:  # pyright: ignore[reportUnknownMemberType]
            prev_commit = None
            for commit in list(git_repo.iter_commits())[::-1]:
                author = github_repo.get_commit(commit.hexsha).author.login
                logger.info(
                    f"{processed} {commit.hexsha[:7]} {commit.committed_datetime.isoformat()} [{author}]"
                )
                if prev_commit is None:
                    if commit.hexsha == args.start_hexsha:
                        prev_commit = commit
                    continue
                pr_url = f"https://github.com/Greenbax/evergreen/pull/{get_pr_num_from_commit_message(str(commit.summary))}"
                logger.info(pr_url)
                git_repo.git.checkout(commit)
                # lint-fixme: NoAwaitInLoopRule: this await cannot be gathered due to dependencies
                await analyze_contribution_and_create_a_check_run(
                    git_repo,
                    github_repo,
                    s3,
                    prev_commit,
                    commit,
                    args.paths,
                    analyzers,
                    author,
                    is_backfill=True,
                )
                processed += 1

                prev_commit = commit
    else:
        git_repo = get_git_repo()
        head_commit = git_repo.head.commit
        pull = get_pull_request()
        if pull:
            base_commit_sha = pull.get_commits()[0].parents[0].sha
        else:
            base_commit_sha = head_commit.parents[0].hexsha
        base_commit = git_repo.commit(base_commit_sha)
        # lint-fixme: NoS3ClientRule
        async with session.client("s3") as s3:  # pyright: ignore[reportUnknownMemberType]
            github_repo = get_github_repo()
            try:
                pull = get_pull_request()
                if pull is not None:
                    author = pull.user.login
                else:
                    author = github_repo.get_commit(head_commit.hexsha).author.login
            except AttributeError:
                author = "UnknownAuthor"
            await analyze_contribution_and_create_a_check_run(
                git_repo,
                github_repo,
                s3,
                base_commit,
                head_commit,
                args.paths,
                analyzers,
                author,
                is_backfill=False,
            )


if __name__ == "__main__":
    asyncio.run(main())
