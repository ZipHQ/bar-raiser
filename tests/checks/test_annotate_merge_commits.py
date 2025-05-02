from __future__ import annotations

from argparse import ArgumentParser, Namespace
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, create_autospec, patch

from github.Commit import Commit
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Repository import Repository

from bar_raiser.checks.annotate_merge_commits import (
    CHECK_NAME,
    contains_merge_commit,
    main,
)

if TYPE_CHECKING:
    from collections.abc import Iterator


class CustomPaginatedList(PaginatedList[Commit]):
    def __init__(self, commits: list[Commit]) -> None:
        self._commits = commits

    def __iter__(self) -> Iterator[Commit]:
        return iter(self._commits)


def test_contains_merge_commit_true() -> None:
    commit1 = MagicMock(spec=Commit)
    commit1.parents = [MagicMock(), MagicMock()]  # Merge commit (2 parents)
    commit2 = MagicMock(spec=Commit)
    commit2.parents = [MagicMock()]  # Regular commit (1 parent)
    commits = CustomPaginatedList([commit1, commit2])

    result = contains_merge_commit(commits)

    assert result is True


def test_contains_merge_commit_false() -> None:
    commit1 = MagicMock(spec=Commit)
    commit1.parents = [MagicMock()]
    commit2 = MagicMock(spec=Commit)
    commit2.parents = [MagicMock()]
    commits = CustomPaginatedList([commit1, commit2])

    result = contains_merge_commit(commits)

    assert result is False


@patch(
    "bar_raiser.checks.annotate_merge_commits.create_arg_parser_with_slack_dm_on_failure"
)
@patch("bar_raiser.checks.annotate_merge_commits.get_github_repo")
@patch("bar_raiser.checks.annotate_merge_commits.get_pull_request")
@patch("bar_raiser.checks.annotate_merge_commits.get_head_sha")
@patch("bar_raiser.checks.annotate_merge_commits.create_check_run")
@patch("bar_raiser.checks.annotate_merge_commits.dm_on_check_failure")
def test_amc_with_merge_commits(  # noqa: PLR0917
    mock_dm_on_check_failure: MagicMock,
    mock_create_check_run: MagicMock,
    mock_get_head_sha: MagicMock,
    mock_get_pull_request: MagicMock,
    mock_get_github_repo: MagicMock,
    mock_create_arg_parser: MagicMock,
) -> None:
    mock_args = MagicMock(spec=Namespace)
    mock_args.slack_dm_on_failure = mapping_path = "user_mapping.json"

    mock_parser = create_autospec(spec=ArgumentParser)
    mock_parser.parse_args.return_value = mock_args
    mock_create_arg_parser.return_value = mock_parser

    mock_repo = MagicMock(spec=Repository)
    mock_get_github_repo.return_value = mock_repo

    mock_pr = create_autospec(spec=PullRequest)
    pr_num = 123
    mock_pr.number = pr_num

    commit1 = MagicMock(spec=Commit)
    commit1.parents = [MagicMock(), MagicMock()]  # Merge commit

    mock_commits = CustomPaginatedList([commit1])
    mock_pr.get_commits.return_value = mock_commits
    mock_get_pull_request.return_value = mock_pr

    mock_head_sha = "abc123"
    mock_get_head_sha.return_value = mock_head_sha

    mock_check_run = MagicMock()
    mock_create_check_run.return_value = mock_check_run

    main()

    mock_create_check_run.assert_called_once_with(
        repo=mock_repo,
        name=CHECK_NAME,
        head_sha=mock_head_sha,
        conclusion="action_required",
        title="Merge Commits Detected",
        summary=(
            f"Your pull request #{pr_num} contains merge commits. "
            "Please rebase your commits onto the latest master branch to prevent potential linting errors."
        ),
        annotations=[],
        actions=[],
    )

    mock_dm_on_check_failure.assert_called_once_with(
        mock_check_run,
        mapping_path,
        "CAUTION: Please rebase your commits onto the latest master branch to prevent potential linting errors.",
    )


@patch(
    "bar_raiser.checks.annotate_merge_commits.create_arg_parser_with_slack_dm_on_failure"
)
@patch("bar_raiser.checks.annotate_merge_commits.get_github_repo")
@patch("bar_raiser.checks.annotate_merge_commits.get_pull_request")
@patch("bar_raiser.checks.annotate_merge_commits.get_head_sha")
@patch("bar_raiser.checks.annotate_merge_commits.create_check_run")
@patch("bar_raiser.checks.annotate_merge_commits.dm_on_check_failure")
def test_amc_without_merge_commits(  # noqa: PLR0917
    mock_dm_on_check_failure: MagicMock,
    mock_create_check_run: MagicMock,
    mock_get_head_sha: MagicMock,
    mock_get_pull_request: MagicMock,
    mock_get_github_repo: MagicMock,
    mock_create_arg_parser: MagicMock,
) -> None:
    mock_args = MagicMock(spec=Namespace)
    mock_args.slack_dm_on_failure = None

    mock_parser = create_autospec(spec=ArgumentParser)
    mock_parser.parse_args.return_value = mock_args
    mock_create_arg_parser.return_value = mock_parser

    mock_repo = MagicMock(spec=Repository)
    mock_get_github_repo.return_value = mock_repo

    mock_pr = create_autospec(spec=PullRequest)
    pr_num = 123
    mock_pr.number = pr_num

    commit1 = MagicMock(spec=Commit)
    commit1.parents = [MagicMock()]
    mock_commits = CustomPaginatedList([commit1])
    mock_pr.get_commits.return_value = mock_commits
    mock_get_pull_request.return_value = mock_pr

    mock_head_sha = "abc123"
    mock_get_head_sha.return_value = mock_head_sha

    main()

    mock_create_check_run.assert_called_once_with(
        repo=mock_repo,
        name=CHECK_NAME,
        head_sha=mock_head_sha,
        conclusion="success",
        title="No Merge Commits",
        summary=f"Your pull request #{pr_num} does not contain any merge commits.",
        annotations=[],
        actions=[],
    )

    mock_dm_on_check_failure.assert_not_called()


@patch(
    "bar_raiser.checks.annotate_merge_commits.create_arg_parser_with_slack_dm_on_failure"
)
@patch("bar_raiser.checks.annotate_merge_commits.get_github_repo")
@patch("bar_raiser.checks.annotate_merge_commits.get_pull_request")
@patch("bar_raiser.checks.annotate_merge_commits.logger.info")
def test_amc_no_pull_request(
    mock_logger: MagicMock,
    mock_get_pull_request: MagicMock,
    mock_get_github_repo: MagicMock,
    mock_create_arg_parser: MagicMock,
) -> None:
    mock_args = MagicMock(spec=Namespace)

    mock_parser = create_autospec(spec=ArgumentParser)
    mock_parser.parse_args.return_value = mock_args
    mock_create_arg_parser.return_value = mock_parser

    mock_repo = MagicMock(spec=Repository)
    mock_get_github_repo.return_value = mock_repo
    mock_get_pull_request.return_value = None

    main()

    mock_logger.assert_called_once_with("No pull request found.")
