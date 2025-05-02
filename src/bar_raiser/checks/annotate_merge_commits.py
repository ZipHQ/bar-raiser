from __future__ import annotations

from logging import getLogger
from typing import TYPE_CHECKING

from bar_raiser.utils.check import create_arg_parser
from bar_raiser.utils.github import (
    create_check_run,
    get_github_repo,
    get_head_sha,
    get_pull_request,
    initialize_logging,
)
from bar_raiser.utils.slack import dm_on_check_failure

if TYPE_CHECKING:
    from github.Commit import Commit
    from github.PaginatedList import PaginatedList

logger = getLogger(__name__)
CHECK_NAME = "avoid-merge-commits"


def contains_merge_commit(commits: PaginatedList[Commit]) -> bool:
    """
    Check if any commit in the list is a merge commit.
    """
    return any(len(commit.parents) > 1 for commit in commits)


def main():
    parser = create_arg_parser()
    args = parser.parse_args()
    repo = get_github_repo()
    pull_request = get_pull_request()
    if not pull_request:
        logger.info("No pull request found.")
        return

    # Retrieve commits from the pull request
    commits = pull_request.get_commits()
    logger.info(f"Commits: {commits}")

    # Check for merge commits
    if contains_merge_commit(commits):
        conclusion = "action_required"
        title = "Merge Commits Detected"
        summary = (
            f"Your pull request #{pull_request.number} contains merge commits. "
            "Please rebase your commits onto the latest master branch to prevent potential linting errors."
        )
    else:
        conclusion = "success"
        title = "No Merge Commits"
        summary = f"Your pull request #{pull_request.number} does not contain any merge commits."

    # Create a check run
    checks = create_check_run(
        repo=repo,
        name=CHECK_NAME,
        head_sha=get_head_sha(),
        conclusion=conclusion,
        title=title,
        summary=summary,
        annotations=[],  # No annotations needed for this check
        actions=[],
    )

    message = "CAUTION: Please rebase your commits onto the latest master branch to prevent potential linting errors."

    if args.slack_dm_on_failure:
        dm_on_check_failure(checks, args.slack_dm_on_failure, message)
    else:
        logger.info("No slack_dm_on_failure configured.")


if __name__ == "__main__":
    initialize_logging()
    main()
