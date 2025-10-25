from __future__ import annotations

from os import chdir, getcwd, environ
from unittest.mock import MagicMock, mock_open, patch

from git import Diff
from github.File import File
from github.IssueComment import IssueComment
from github.NamedUser import NamedUser
from github.PullRequest import PullRequest
from github.Repository import Repository

from bar_raiser.utils.github import (
    Annotation,
    commit_changes,
    create_a_pull_request,
    create_check_run,
    get_github_repo,
    get_pull_request,
    get_updated_paths,
    has_previous_issue_comment,
    run_codemod_and_commit_changes,
)

TEST_ORG = "ZipHQ"
TEST_REPO = f"{TEST_ORG}/bar-raiser"


@patch.dict(
    environ,
    {
        "APP_ID": "_ID",
        "PRIVATE_KEY": "_KEY",
        "GITHUB_REPOSITORY_OWNER": TEST_ORG,
        "GITHUB_REPOSITORY": TEST_REPO,
    },
)
def test_get_repo() -> None:  # touch
    with (
        patch("bar_raiser.utils.github.GithubIntegration"),
        patch("bar_raiser.utils.github.Github") as mock_github,
    ):
        get_github_repo()
        mock_github.return_value.get_repo.assert_called_with(TEST_REPO)


def test_create_check_run_with_pagination() -> None:
    mock_repo = MagicMock(spec=Repository)
    create_check_run(
        repo=mock_repo,
        name="",
        head_sha="",
        conclusion="action_required",
        title="",
        summary="",
        annotations=[
            Annotation(
                path="", start_line=1, end_line=1, annotation_level="", message=""
            )
            for i in range(75)
        ],
        actions=[],
    )
    assert mock_repo.create_check_run.call_count == 2


def test_create_check_run_with_no_annotations() -> None:
    mock_repo = MagicMock(spec=Repository)
    create_check_run(
        repo=mock_repo,
        name="",
        head_sha="",
        conclusion="success",
        title="",
        summary="",
        annotations=[],
        actions=[],
    )
    assert mock_repo.create_check_run.call_count == 1


def test_commit_changes(tmp_path) -> None:
    mock_repo = MagicMock(spec=Repository)
    # fmt: off
    mock_repo.create_git_blob.return_value = MagicMock(
        sha="blob_sha"
    )
    # fmt: on

    # Create a real temporary file
    test_file = tmp_path / "a.py"
    test_file.write_text("file content", encoding="utf-8")

    # Change dir to test relative dir access
    cwd = getcwd()
    chdir(tmp_path)
    with patch("bar_raiser.utils.github.InputGitTreeElement") as mock_element:
        commit_changes(mock_repo, "a_branch", "a_sha", [test_file.name], "a_commit_message")
    chdir(cwd)

    # Verify blob was created with correct content
    mock_repo.create_git_blob.assert_called_once_with("file content", "utf-8")

    # Verify InputGitTreeElement was constructed with correct arguments
    mock_element.assert_called_once_with(test_file.name, "100644", "blob", sha="blob_sha")

    # Verify tree was created with the element
    assert mock_repo.create_git_tree.call_count == 1

    # Verify commit was created
    assert mock_repo.create_git_commit.call_count == 1
    mock_repo.reset_mock()

    with patch("bar_raiser.utils.github.open", mock_open(read_data="")):
        commit_changes(
            mock_repo,
            "a_branch",
            "a_sha",
            [f"a_{i}.py" for i in range(201)],
            "a_commit_message",
        )
    assert mock_repo.create_git_commit.call_count == 2


def test_run_codemod_and_commit_changes() -> None:
    mock_repo = MagicMock(spec=Repository)
    with (
        patch("bar_raiser.utils.github.check_output") as mock_check_output,
        patch("bar_raiser.utils.github.Repo") as mock_git_repo,
        patch("bar_raiser.utils.github.commit_changes") as mock_commit_changes,
    ):
        mock_git_repo.return_value.index.diff.return_value = []
        run_codemod_and_commit_changes(
            mock_repo, 123, [["black"]], "Apply Black Format", run_on_updated_paths=True
        )
        mock_check_output.assert_called_with(["black"])
        mock_commit_changes.assert_not_called()
        mock_pull = mock_repo.get_pull.return_value
        mock_pull.create_issue_comment.assert_called_once_with(
            "No updated paths to commit."
        )

        mock_git_repo.return_value.index.diff.return_value = [
            MagicMock(spec=Diff, b_path="a.py")
        ]
        mock_pull.get_files.return_value = [
            MagicMock(spec=str, status="added", filename="a.py")
        ]
        mock_pull.create_issue_comment.reset_mock()
        run_codemod_and_commit_changes(
            mock_repo, 123, [["black"]], "Apply Black Format", run_on_updated_paths=True
        )
        mock_commit_changes.assert_called_once()
        mock_pull.create_issue_comment.assert_not_called()


def test_get_updated_paths() -> None:
    mock_pull = MagicMock(spec=PullRequest)
    mock_pull.get_files.return_value = [
        MagicMock(spec=File, filename="a.py", status="added"),
        MagicMock(spec=File, filename="b.py", status="removed"),
    ]
    get_updated_paths(mock_pull)


@patch.dict(
    environ,
    {
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": TEST_REPO,
        "GITHUB_RUN_ID": "12345",
    },
)
def test_create_a_pull_request() -> None:
    with (
        patch("bar_raiser.utils.github.Repo") as mock_git_repo,
        patch("bar_raiser.utils.github.commit_changes") as mock_commit_changes,
    ):
        mock_git_repo.return_value.index.diff.return_value = [
            MagicMock(spec=Diff, b_path="a.py")
        ]
        mock_github_repo = MagicMock(spec=Repository)
        create_a_pull_request(
            mock_github_repo,
            "python3 -m libcst.tool codemod convert_to_async.AsyncFunctionTransformer --target-qualified-name pre_call_handler integrations/erp_client_metrics_wrapper.py",
            "jimmy",
            extra_body="some more context",
        )
        mock_commit_changes.assert_called_once()
        mock_github_repo.create_pull.assert_called_once()
        call = mock_github_repo.create_pull.call_args
        assert call.kwargs["title"].startswith(
            "Codemod convert_to_async.AsyncFunctionTransformer by jimmy at "
        )
        assert call.kwargs["head"].startswith(
            "refs/heads/codemod-convert_to_async.AsyncFunctionTransformer-"
        )
        assert call.kwargs["body"].endswith("some more context")


def test_has_previous_issue_comment() -> None:
    assert (
        has_previous_issue_comment(
            MagicMock(spec=PullRequest), "jimmy", "net new tech debt"
        )
        is False
    )
    pull = MagicMock(
        spec=PullRequest,
        get_issue_comments=lambda: [
            MagicMock(
                spec=IssueComment,
                user=MagicMock(spec=NamedUser, login="jimmy"),
                body="You introduced some net new tech debt",
            )
        ],
    )
    assert has_previous_issue_comment(pull, "jimmy", "net new tech debt") is True


def test_get_pull_request() -> None:
    with patch("bar_raiser.utils.github.get_github_repo"):
        assert get_pull_request() is None
