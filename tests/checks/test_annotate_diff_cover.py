from __future__ import annotations

import argparse
from os import environ
from pathlib import Path
from unittest.mock import Mock, mock_open, patch

from bar_raiser.checks.annotate_diff_cover import (
    TIP_TEXT,
    DiffCoverJson,
    get_annotations,
    get_conclusion,
    get_github_repo,
    get_ranges,
    get_summary,
    main,
)
from bar_raiser.utils.github import Annotation


@patch.dict(
    environ,
    {
        "APP_ID": "_ID",
        "PRIVATE_KEY": "_KEY",
        "GITHUB_REPOSITORY_OWNER": "ZipHQ",
        "GITHUB_REPOSITORY": "ZipHQ/bar-raiser",
    },
)
def test_get_repo() -> None:
    with (
        patch("bar_raiser.utils.github.GithubIntegration"),
        patch("bar_raiser.utils.github.Github") as mock_github,
    ):
        get_github_repo()
        mock_github.return_value.get_repo.assert_called_with("ZipHQ/bar-raiser")


def test_get_ranges() -> None:
    assert get_ranges([1, 2, 3, 4, 5, 8, 9, 11, 13, 14, 15]) == [
        (1, 5),
        (8, 9),
        (11, 11),
        (13, 15),
    ]


def test_get_conclusion() -> None:
    assert get_conclusion(80) == "success"
    assert get_conclusion(75) == "success"
    assert get_conclusion(74) == "action_required"


def test_get_annotations() -> None:
    diff_cover_json: DiffCoverJson = {
        "src_stats": {
            "github/annotate_missing_test_coverage.py": {
                "violation_lines": [
                    14,
                    15,
                    16,
                    17,
                    18,
                    19,
                    20,
                    21,
                    62,
                    63,
                    64,
                    65,
                    66,
                    67,
                    76,
                    80,
                    90,
                ],
            }
        },
        "total_num_lines": 48,
        "total_num_violations": 17,
        "total_percent_covered": 64,
        "num_changed_lines": 148,
    }
    assert get_annotations(diff_cover_json) == [
        Annotation(
            path="github/annotate_missing_test_coverage.py",
            start_line=14,
            end_line=21,
            annotation_level="failure",
            message=f"Missing test coverage for 8 lines.{TIP_TEXT}",
        ),
        Annotation(
            path="github/annotate_missing_test_coverage.py",
            start_line=62,
            end_line=67,
            annotation_level="failure",
            message=f"Missing test coverage for 6 lines.{TIP_TEXT}",
        ),
        Annotation(
            path="github/annotate_missing_test_coverage.py",
            start_line=76,
            end_line=76,
            annotation_level="failure",
            message=f"Missing test coverage for 1 line.{TIP_TEXT}",
        ),
        Annotation(
            path="github/annotate_missing_test_coverage.py",
            start_line=80,
            end_line=80,
            annotation_level="failure",
            message=f"Missing test coverage for 1 line.{TIP_TEXT}",
        ),
        Annotation(
            path="github/annotate_missing_test_coverage.py",
            start_line=90,
            end_line=90,
            annotation_level="failure",
            message=f"Missing test coverage for 1 line.{TIP_TEXT}",
        ),
    ]


MARKDOWN_TEST_REPORT = """## Python Test Coverage Report

# Diff Coverage
## Diff: HEAD^...HEAD, staged and unstaged changes

- github/annotate_missing_test_coverage&#46;py (73.8%): Missing lines 14-21,78-82,86-87,97

## Summary

- **Total**: 61 lines
- **Missing**: 16 lines
- **Coverage**: 73%



## github/annotate_missing_test_coverage&#46;py

Lines 10-25

```python
from github.Repository import Repository
"""


def test_get_summary() -> None:
    assert (
        get_summary(MARKDOWN_TEST_REPORT)
        == """## Python Test Coverage Report

# Diff Coverage
## Diff: HEAD^...HEAD, staged and unstaged changes

- github/annotate_missing_test_coverage&#46;py (73.8%): Missing lines 14-21,78-82,86-87,97

## Summary

- **Total**: 61 lines
- **Missing**: 16 lines
- **Coverage**: 73%"""
    )


@patch("bar_raiser.checks.annotate_diff_cover.get_github_repo")
@patch("bar_raiser.checks.annotate_diff_cover.get_head_sha")
@patch(
    "bar_raiser.checks.annotate_diff_cover.load",
    side_effect=[{"total_percent_covered": 70, "src_stats": {}}],
)
@patch(
    "bar_raiser.checks.annotate_diff_cover.Path.open",
    new_callable=mock_open,
    read_data='{"total_percent_covered": 70, "src_stats": {}}',
)
@patch("bar_raiser.checks.annotate_diff_cover.create_arg_parser")
def test_main(
    mock_create_arg_parser: Mock,
    mock_open: Mock,
    mock_load: Mock,
    mock_get_head_sha: Mock,
    mock_get_github_repo: Mock,
) -> None:
    mock_parser = mock_create_arg_parser.return_value
    mock_parser.parse_args.return_value = argparse.Namespace(
        diff_cover_json_report=Path("diff_cover.json"),
        diff_cover_markdown_report=Path("diff_cover.md"),
        slack_dm_on_failure=None,
    )

    with patch(
        "bar_raiser.checks.annotate_diff_cover.create_check_run"
    ) as mock_create_check_run:
        main()

        mock_create_check_run.assert_called_once()
        mock_get_github_repo.assert_called_once()
        mock_get_head_sha.assert_called_once()
        mock_load.assert_called_once()
        assert mock_open.call_count == 2
