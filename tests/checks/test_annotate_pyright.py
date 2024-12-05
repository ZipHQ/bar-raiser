from __future__ import annotations

import sys
from pathlib import Path
from subprocess import CalledProcessError
from unittest.mock import MagicMock, patch

from git import Commit

from bar_raiser.checks.annotate_pyright import (
    get_annotations_and_actions_for_pyright_check,
    main,
)

REPO_DIR = "/home/user/bar_raiser"
WORKING_DIR = "/home/user/bar_raiser/subfolder"

PYRIGHT_OUTPUT_WITH_ERROR = """
{"version": "1.1.304",
    "time": "1705431974306",
    "generalDiagnostics": [
        {"file": "/home/user/bar_raiser/subfolder/checks/annotate_pyright.py",
            "severity": "error",
            "message": "Try statement must have at least one except or finally clause",
            "range": {"start": {"line": 15,
                    "character": 4
                },
                "end": {"line": 15,
                    "character": 7
                }
            }
        }
    ],
    "summary": {"filesAnalyzed": 45,
        "errorCount": 1,
        "warningCount": 0,
        "informationCount": 0,
        "timeInSec": 4.554
    }
}
"""

PYRIGHT_OUTPUT_WITH_UNNECESSARY_IGNORE = r"""
{"version": "1.1.304",
    "time": "1705455668409",
    "generalDiagnostics": [
        {"file": "/home/user/bar_raiser/subfolder/checks/annotate_pyright.py",
            "severity": "error",
            "message": "Unnecessary \"# pyright: ignore\" rule: \"reportUnknownMemberType\"",
            "range": {"start": {"line": 31,
                    "character": 52
                },
                "end": {"line": 31,
                    "character": 75
                }
            }
        }
    ],
    "summary": {"filesAnalyzed": 46,
        "errorCount": 1,
        "warningCount": 0,
        "informationCount": 0,
        "timeInSec": 4.654
    }
}
"""

PYRIGHT_OUTPUT_WITH_NO_ERROR = """
{
    "version": "1.1.304",
    "time": "1705456899041",
    "generalDiagnostics": [],
    "summary": {
        "filesAnalyzed": 46,
        "errorCount": 0,
        "warningCount": 0,
        "informationCount": 0,
        "timeInSec": 4.959
    }
}
"""

PYRIGHT_OUTPUT_WITH_RULE_ERROR = r"""
{
    "version": "1.1.304",
    "time": "1705530427151",
    "generalDiagnostics": [
        {
            "file": "/home/user/bar_raiser/subfolder/lib/common.py",
            "severity": "error",
            "message": "Type of \"line\" is unknown",
            "range": {
                "start": {
                    "line": 190,
                    "character": 12
                },
                "end": {
                    "line": 190,
                    "character": 16
                }
            },
            "rule": "reportUnknownVariableType"
        },
        {
            "file": "/home/user/bar_raiser/subfolder/lib/common.py",
            "severity": "error",
            "message": "Argument type is unknown\n  Argument corresponds to parameter \"__object\" in function \"append\"",
            "range": {
                "start": {
                    "line": 201,
                    "character": 20
                },
                "end": {
                    "line": 201,
                    "character": 24
                }
            },
            "rule": "reportUnknownArgumentType"
        }
    ],
    "summary": {
        "filesAnalyzed": 1,
        "errorCount": 10,
        "warningCount": 0,
        "informationCount": 0,
        "timeInSec": 0.691
    }
}
"""


def test_get_annotations_and_actions_for_pyright() -> None:
    with patch(
        "bar_raiser.checks.annotate_pyright.Path.cwd",
        return_value=Path(WORKING_DIR),
    ):
        assert get_annotations_and_actions_for_pyright_check(
            Path(REPO_DIR), PYRIGHT_OUTPUT_WITH_ERROR
        ) == (
            [
                {
                    "path": "subfolder/checks/annotate_pyright.py",
                    "start_line": 16,
                    "end_line": 16,
                    "annotation_level": "failure",
                    "message": "Try statement must have at least one except or finally clause",
                }
            ],
            [],
        )

        assert get_annotations_and_actions_for_pyright_check(
            Path(REPO_DIR), PYRIGHT_OUTPUT_WITH_UNNECESSARY_IGNORE
        ) == (
            [
                {
                    "path": "subfolder/checks/annotate_pyright.py",
                    "start_line": 32,
                    "end_line": 32,
                    "annotation_level": "failure",
                    "message": 'Unnecessary "# pyright: ignore" rule: "reportUnknownMemberType"',
                }
            ],
            [
                {
                    "label": "autofix",
                    "description": "Click to auto-push an autofix commit",
                    "identifier": "pyright-ignores",
                }
            ],
        )

        assert get_annotations_and_actions_for_pyright_check(
            Path(REPO_DIR), PYRIGHT_OUTPUT_WITH_NO_ERROR
        ) == ([], [])

        print(
            get_annotations_and_actions_for_pyright_check(
                Path(REPO_DIR), PYRIGHT_OUTPUT_WITH_RULE_ERROR
            )
        )
        assert get_annotations_and_actions_for_pyright_check(
            Path(REPO_DIR), PYRIGHT_OUTPUT_WITH_RULE_ERROR
        ) == (
            [
                {
                    "path": "subfolder/lib/common.py",
                    "start_line": 191,
                    "end_line": 191,
                    "annotation_level": "failure",
                    "message": 'Type of "line" is unknown [reportUnknownVariableType]',
                },
                {
                    "path": "subfolder/lib/common.py",
                    "start_line": 202,
                    "end_line": 202,
                    "annotation_level": "failure",
                    "message": 'Argument type is unknown\n  Argument corresponds to parameter "__object" in function "append" [reportUnknownArgumentType]',
                },
            ],
            [],
        )


def test_main() -> None:
    target_module = "bar_raiser.checks.annotate_pyright"

    with (
        patch(f"{target_module}.create_check_run") as mock_create_check_run,
        patch(f"{target_module}.get_github_repo"),
        patch(f"{target_module}.get_git_repo") as mock_git_repo,
        patch(f"{target_module}.exit") as mock_exit,
        patch(
            "bar_raiser.checks.annotate_pyright.Path.cwd",
            return_value=Path(WORKING_DIR),
        ),
        patch.object(sys, "argv", ["annotate_pyright.py"]),
        patch(f"{target_module}.get_head_sha", return_value="1"),
    ):
        mock_git_repo.return_value.working_dir = Path(REPO_DIR)
        mock_git_repo.return_value.head.commit.parents = [
            MagicMock(spec=Commit, hexsha="1"),
        ]
        with patch(
            f"{target_module}.check_output",
            side_effect=CalledProcessError(
                1, [], output=PYRIGHT_OUTPUT_WITH_ERROR.encode("utf-8")
            ),
        ):
            main()
            assert len(mock_create_check_run.call_args_list) == 1
            kwargs = mock_create_check_run.call_args_list[0].kwargs
            assert kwargs["name"] == "python-pyright-report"
            assert kwargs["head_sha"] == "1"
            assert kwargs["conclusion"] == "action_required"
            assert kwargs["title"] == "Python Pyright Type Checker"
            assert len(kwargs["annotations"]) == 1
            assert len(kwargs["actions"]) == 0
            mock_exit.assert_called_once_with(1)
            mock_create_check_run.reset_mock()
            mock_exit.reset_mock()

        with patch(
            f"{target_module}.check_output",
            side_effect=CalledProcessError(
                0, [], output=PYRIGHT_OUTPUT_WITH_NO_ERROR.encode("utf-8")
            ),
        ):
            main()
            assert len(mock_create_check_run.call_args_list) == 1
            kwargs = mock_create_check_run.call_args_list[0].kwargs
            assert kwargs["name"] == "python-pyright-report"
            assert kwargs["head_sha"] == "1"
            assert kwargs["conclusion"] == "success"
            assert kwargs["title"] == "Python Pyright Type Checker"
            assert len(kwargs["annotations"]) == 0
            assert len(kwargs["actions"]) == 0
            mock_exit.assert_called_once_with(0)
