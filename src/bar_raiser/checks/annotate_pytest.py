from __future__ import annotations

from json import loads
from pathlib import Path
from typing import NotRequired, TypedDict

from bar_raiser.utils.check import create_arg_parser_with_slack_dm_on_failure
from bar_raiser.utils.github import (
    Annotation,
    create_check_run,
    get_git_repo,
    get_github_repo,
    get_head_sha,
)
from bar_raiser.utils.slack import dm_on_check_failure

CHECK_NAME = "python-pytest-report"


class Call(TypedDict):
    longrepr: NotRequired[str]


class Test(TypedDict):
    nodeid: str
    outcome: str
    lineno: int
    setup: NotRequired[Call]
    call: NotRequired[Call]
    teardown: NotRequired[Call]


class TestSummary(TypedDict):
    passed: NotRequired[int]
    failed: int
    error: NotRequired[int]
    total: int


class PytestReportJson(TypedDict):
    root: str
    summary: TestSummary
    tests: list[Test]


def get_longrepr(test: Test) -> str:
    # A test that errors in a fixture has no "call" stage, so check every stage.
    for stage in ("setup", "call", "teardown"):
        longrepr = test.get(stage, {}).get("longrepr")
        if longrepr:
            return longrepr
    return "Missing longrepr from pytest report."


def get_annotations(
    pytest_report_json: PytestReportJson, git_root: Path
) -> list[Annotation]:
    annotations: list[Annotation] = []
    for test in pytest_report_json["tests"]:
        if test["outcome"] in {"failed", "error"}:
            full_path = Path(pytest_report_json["root"]).joinpath(
                test["nodeid"].split("::")[0]
            )
            # pytest-json-report line numbers are 0-based, GitHub's are 1-based.
            line = test["lineno"] + 1
            annotations.append(
                Annotation(
                    path=str(full_path.relative_to(git_root)),
                    start_line=line,
                    end_line=line,
                    annotation_level="failure",
                    message=get_longrepr(test),
                )
            )
    return annotations


def get_summary(pytest_report_json: PytestReportJson) -> str:
    summary = pytest_report_json["summary"]
    errors = summary.get("error", 0)
    errors_text = f", Errors: {errors}" if errors else ""
    return f"Passed: {summary.get('passed', 0)}, Failed: {summary.get('failed', 0)}{errors_text}, Total: {summary['total']}"


def main():
    parser = create_arg_parser_with_slack_dm_on_failure()
    parser.add_argument(
        "pytest_json_report",
        type=Path,
        help="Path to the pytest json report crated with --json-report option using pytest-json-report",
    )
    args = parser.parse_args()
    pytest_report_json: PytestReportJson = loads(args.pytest_json_report.read_text())
    annotations = get_annotations(pytest_report_json, Path(get_git_repo().working_dir))
    checks = create_check_run(
        repo=get_github_repo(),
        name=CHECK_NAME,
        head_sha=get_head_sha(),
        conclusion="action_required" if len(annotations) > 0 else "success",
        title="Python Pytest Report",
        summary=get_summary(pytest_report_json),
        annotations=annotations,
        actions=[],
    )
    if args.slack_dm_on_failure:
        dm_on_check_failure(checks, args.slack_dm_on_failure)


if __name__ == "__main__":
    main()
