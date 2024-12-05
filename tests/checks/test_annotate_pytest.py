from __future__ import annotations

import sys
from json import dumps
from pathlib import Path
from unittest.mock import patch

from bar_raiser.checks.annotate_pytest import PytestReportJson, get_annotations, main

REPO_DIR = "/home/user/bar_raiser"
WORKING_DIR = "/home/user/bar_raiser/subfolder"

pytest_report_json: PytestReportJson = {
    "root": WORKING_DIR,
    "summary": {
        "passed": 12,
        "failed": 1,
        "total": 13,
    },
    "tests": [
        {
            "nodeid": "test_rules.py::NoAwaitInLoopRule::test_INVALID_0",
            "lineno": 223,
            "outcome": "passed",
            "call": {},
        },
        {
            "nodeid": "test_rules.py::NoAwaitInLoopRule::test_VALID_0",
            "lineno": 223,
            "outcome": "passed",
            "call": {},
        },
        {
            "nodeid": "github/test_utils.py::test_get_repo",
            "lineno": 8,
            "outcome": "failed",
            "call": {
                "longrepr": '@patch.dict(\n        environ,\n        {\n            "APP_ID": "_ID",\n            "PRIVATE_KEY": "_KEY",\n            "GITHUB_REPOSITORY_OWNER": "Greenbax",\n            "GITHUB_REPOSITORY": "Greenbax/evergreen",\n        },\n    )\n    def test_get_repo() -> None:\n>       with patch(\n            "fixit_linters.github.annotate_missing_test_coverage.GithubIntegration"\n        ), patch(\n            "fixit_linters.github.annotate_missing_test_coverage.Github"\n        ) as mock_github:\n\nfixit_linters/github/test_utils.py:19: \n_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _\n\nself = <unittest.mock._patch object at 0x7f896fc95b10>\n\n    def get_original(self):\n        target = self.getter()\n        name = self.attribute\n    \n        original = DEFAULT\n        local = False\n    \n        try:\n            original = target.__dict__[name]\n        except (AttributeError, KeyError):\n            original = getattr(target, name, DEFAULT)\n        else:\n            local = True\n    \n        if name in _builtins and isinstance(target, ModuleType):\n            self.create = True\n    \n        if not self.create and original is DEFAULT:\n>           raise AttributeError(\n                "%s does not have the attribute %r" % (target, name)\n            )\nE           AttributeError: <module \'fixit_linters.github.annotate_missing_test_coverage\' from \'/home/admin/evergreen/website/fixit_linters/github/annotate_missing_test_coverage.py\'> does not have the attribute \'GithubIntegration\'\n\n../../.pyenv/versions/3.11.3/lib/python3.11/unittest/mock.py:1410: AttributeError'
            },
        },
        {
            "nodeid": "github/test_utils.py::test_create_check_run",
            "lineno": 27,
            "outcome": "passed",
            "call": {},
        },
    ],
}


def test_get_annotations() -> None:
    annotations = get_annotations(pytest_report_json, Path(REPO_DIR))
    assert len(annotations) == 1
    assert annotations[0]["path"] == "subfolder/github/test_utils.py"


def test_main() -> None:
    with (
        patch(
            "bar_raiser.checks.annotate_pytest.create_check_run"
        ) as mock_create_check_run,
        patch("bar_raiser.checks.annotate_pytest.get_git_repo") as mock_get_git_repo,
        patch("bar_raiser.checks.annotate_pytest.get_github_repo"),
        patch("bar_raiser.checks.annotate_pytest.get_head_sha", return_value="1"),
        patch(
            "bar_raiser.checks.annotate_pytest.dm_on_check_failure"
        ) as mock_dm_on_check_failure,
        patch.object(sys, "argv", ["annotate_pytest.py", "path/to/report.json"]),
        patch("pathlib.Path.read_text", return_value=dumps(pytest_report_json)),
    ):
        mock_get_git_repo.return_value.working_dir = Path(WORKING_DIR)
        main()
        assert len(mock_create_check_run.call_args_list) == 1
        kwargs = mock_create_check_run.call_args_list[0].kwargs
        assert kwargs["name"] == "python-pytest-report"
        assert kwargs["head_sha"] == "1"
        assert kwargs["conclusion"] == "action_required"
        assert kwargs["title"] == "Python Pytest Report"
        assert len(kwargs["annotations"]) == 1
        mock_dm_on_check_failure.assert_not_called()
