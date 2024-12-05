from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock, patch

from bar_raiser.checks.annotate_run_ruff import (
    RUFF_CHECK_PATTERNS,
    RUFF_FORMAT_PATTERNS,
    main,
)
from bar_raiser.utils.check import get_annotations_and_actions

RUFF_FORMAT_OUTPUT = """\
error: Failed to format apply_autofixes.py: source contains syntax errors: ParseError { error: UnrecognizedToken(Colon, None), offset: 554, source_path: "<filename>" }
error: Failed to format test_annotate_run_ruff.py: source contains syntax errors: ParseError { error: UnrecognizedToken(Semi, None), offset: 957, source_path: "<filename>" }
Would reformat: annotate_run_ruff.py
1 file would be reformatted, 7975 files left unchanged
"""

RUFF_CHECK_OUTPUT = """\
error: Failed to parse annotate_run_ruff.py:68:14: Unexpected token 'if'
charts.py:1:1: I002 [*] Missing required import: `from __future__ import annotations`
test_annotate_run_ruff.py:5:22: F401 [*] `unittest.mock` imported but unused
Found 2 errors.
[*] 2 fixable with the `--fix` option.
"""

REPO_DIR = "/home/user/bar_raiser"
WORKING_DIR = "/home/user/bar_raiser/subfolder"


def test_get_annotations_and_actions_for_ruff_format() -> None:
    with patch(
        "bar_raiser.checks.annotate_run_ruff.Path.cwd",
        return_value=Path(WORKING_DIR),
    ):
        assert get_annotations_and_actions(
            Path(REPO_DIR),
            RUFF_FORMAT_OUTPUT,
            RUFF_FORMAT_PATTERNS,
        ) == (
            [
                {
                    "path": "subfolder/apply_autofixes.py",
                    "start_line": 554,
                    "end_line": 554,
                    "annotation_level": "failure",
                    "message": "source contains syntax errors: ParseError { error: UnrecognizedToken(Colon, None)",
                },
                {
                    "path": "subfolder/test_annotate_run_ruff.py",
                    "start_line": 957,
                    "end_line": 957,
                    "annotation_level": "failure",
                    "message": "source contains syntax errors: ParseError { error: UnrecognizedToken(Semi, None)",
                },
                {
                    "path": "subfolder/annotate_run_ruff.py",
                    "start_line": 1,
                    "end_line": 1,
                    "annotation_level": "failure",
                    "message": "Ruff would reformat this file.",
                },
            ],
            {
                "label": "autofix",
                "description": "Click to auto-push an autofix commit",
                "identifier": "autofix-ruff",
            },
        )


def test_get_annotations_and_actions_for_ruff_check() -> None:
    with patch(
        "bar_raiser.checks.annotate_run_ruff.Path.cwd",
        return_value=Path(WORKING_DIR),
    ):
        assert get_annotations_and_actions(
            Path(REPO_DIR), RUFF_CHECK_OUTPUT, RUFF_CHECK_PATTERNS
        ) == (
            [
                {
                    "path": "subfolder/annotate_run_ruff.py",
                    "start_line": 68,
                    "end_line": 68,
                    "annotation_level": "failure",
                    "message": "Unexpected token 'if'",
                },
                {
                    "path": "subfolder/charts.py",
                    "start_line": 1,
                    "end_line": 1,
                    "annotation_level": "failure",
                    "message": "I002 [*] Missing required import: `from __future__ import annotations`",
                },
                {
                    "path": "subfolder/test_annotate_run_ruff.py",
                    "start_line": 5,
                    "end_line": 5,
                    "annotation_level": "failure",
                    "message": "F401 [*] `unittest.mock` imported but unused",
                },
            ],
            {
                "label": "autofix",
                "description": "Click to auto-push an autofix commit",
                "identifier": "autofix-ruff",
            },
        )


def test_main() -> None:
    returncode = -1
    target_module = "bar_raiser.checks.annotate_run_ruff"

    def mock_check_output(cmds: list[str], stderr: int):
        match cmds[1]:
            case "format":
                raise CalledProcessError(
                    returncode, [], output=RUFF_FORMAT_OUTPUT.encode("utf-8")
                )
            case "check":
                raise CalledProcessError(
                    returncode, [], output=RUFF_CHECK_OUTPUT.encode("utf-8")
                )

    with (
        patch(f"{target_module}.create_check_run") as mock_create_check_run,
        patch(
            f"{target_module}.check_output",
            mock_check_output,
        ),
        patch(f"{target_module}.get_github_repo"),
        patch(f"{target_module}.get_git_repo") as mock_git_repo,
        patch(f"{target_module}.get_head_sha", return_value="1"),
        patch(f"{target_module}.exit") as mock_exit,
        patch(
            "bar_raiser.checks.annotate_run_ruff.Path.cwd",
            return_value=Path(WORKING_DIR),
        ),
        patch.object(sys, "argv", ["annotate_run_ruff.py"]),
    ):
        mock_git_repo.return_value.working_dir = Path(WORKING_DIR)
        main()
        assert len(mock_create_check_run.call_args_list) == 1
        kwargs = mock_create_check_run.call_args_list[0].kwargs
        assert kwargs["name"] == "python-ruff-report"
        assert kwargs["head_sha"] == "1"
        assert kwargs["conclusion"] == "action_required"
        assert kwargs["title"] == "Python Ruff formatter and linter"
        assert len(kwargs["annotations"]) == 6
        assert len(kwargs["actions"]) == 1
        mock_exit.assert_called_once_with(returncode)


def test_main_only_fail_on_format() -> None:
    returncode = -1
    target_module = "bar_raiser.checks.annotate_run_ruff"

    def mock_check_output(cmds: list[str], stderr: int) -> MagicMock | None:
        match cmds[1]:
            case "format":
                return MagicMock()
            case "check":
                raise CalledProcessError(
                    returncode, [], output=RUFF_CHECK_OUTPUT.encode("utf-8")
                )

    with (
        patch(f"{target_module}.create_check_run") as mock_create_check_run,
        patch(
            f"{target_module}.check_output",
            mock_check_output,
        ),
        patch(f"{target_module}.get_github_repo"),
        patch(f"{target_module}.get_git_repo") as mock_git_repo,
        patch(f"{target_module}.get_head_sha", return_value="1"),
        patch(f"{target_module}.exit") as mock_exit,
        patch(
            "bar_raiser.checks.annotate_run_ruff.Path.cwd",
            return_value=Path(WORKING_DIR),
        ),
        patch.object(sys, "argv", ["annotate_run_ruff.py"]),
    ):
        mock_git_repo.return_value.working_dir = Path(REPO_DIR)
        main()
        assert len(mock_create_check_run.call_args_list) == 1
        kwargs = mock_create_check_run.call_args_list[0].kwargs
        assert kwargs["name"] == "python-ruff-report"
        assert kwargs["head_sha"] == "1"
        assert kwargs["conclusion"] == "action_required"
        assert kwargs["title"] == "Python Ruff formatter and linter"
        assert len(kwargs["annotations"]) == 3
        assert len(kwargs["actions"]) == 1
        mock_exit.assert_called_once_with(returncode)
