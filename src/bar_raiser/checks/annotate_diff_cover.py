from __future__ import annotations

from itertools import groupby
from json import load
from operator import itemgetter
from pathlib import Path
from typing import Literal, TypedDict

from bar_raiser.utils.check import create_arg_parser
from bar_raiser.utils.github import (
    Annotation,
    create_check_run,
    get_github_repo,
    get_head_sha,
)
from bar_raiser.utils.slack import dm_on_check_failure

TIP_TEXT = " Please add tests for these lines.\nIf you believe there is a good reason to skip it, please click the '+' button to add an inline comment on this pull request to let the reviewers know."


def get_ranges(data: list[int]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for _k, g in groupby(enumerate(data), lambda x: x[0] - x[1]):
        group = map(itemgetter(1), g)
        group = list(map(int, group))
        ranges.append((group[0], group[-1]))
    return ranges


class DiffCoverStat(TypedDict):
    violation_lines: list[int]


class DiffCoverJson(TypedDict):
    src_stats: dict[str, DiffCoverStat]
    total_percent_covered: int
    total_num_lines: int
    total_num_violations: int
    num_changed_lines: int


def get_annotations(diff_cover_json: DiffCoverJson) -> list[Annotation]:
    annotations: list[Annotation] = []
    for path, stats in diff_cover_json["src_stats"].items():
        for start, end in get_ranges(stats["violation_lines"]):
            lines = end - start + 1
            lines_msg = "1 line" if lines == 1 else f"{lines} lines"
            annotations.append(
                Annotation(
                    path=path,
                    start_line=start,
                    end_line=end,
                    annotation_level="failure",
                    message=f"Missing test coverage for {lines_msg}.{TIP_TEXT}",
                )
            )
    return annotations


def get_conclusion(coverage: float) -> Literal["success", "action_required"]:
    if coverage >= 75:
        return "success"
    return "action_required"


def get_summary(markdown_report: str) -> str:
    lines = markdown_report.split("\n")
    for i in range(len(lines)):
        if lines[i : i + 3] == ["", "", ""]:
            return "\n".join(lines[:i])
    return markdown_report


CHECK_NAME = "python-diff-cover-report"


def main():
    parser = create_arg_parser()
    parser.add_argument(
        "diff_cover_json_report",
        type=Path,
        help="Path to the diff-cover generated json report",
    )
    parser.add_argument(
        "diff_cover_markdown_report",
        type=Path,
        help="Path to the diff-cover generated markdown report",
    )
    args = parser.parse_args()
    diff_cover_json: DiffCoverJson = load(
        args.diff_cover_json_report.open(encoding="utf-8")
    )
    repo = get_github_repo()
    checks = create_check_run(
        repo=repo,
        name=CHECK_NAME,
        head_sha=get_head_sha(),
        conclusion=get_conclusion(diff_cover_json["total_percent_covered"]),
        title="Python Test Coverage",
        summary=get_summary(
            args.diff_cover_markdown_report.read_text(encoding="utf-8")
        ),
        annotations=get_annotations(diff_cover_json),
        actions=[],
    )
    if args.slack_dm_on_failure:
        dm_on_check_failure(checks, args.slack_dm_on_failure)


if __name__ == "__main__":
    main()
