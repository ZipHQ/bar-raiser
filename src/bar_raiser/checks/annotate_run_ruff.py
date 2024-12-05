from __future__ import annotations

from logging import getLogger
from pathlib import Path
from subprocess import STDOUT, CalledProcessError, check_output
from sys import exit
from typing import TYPE_CHECKING

from bar_raiser.utils.check import CheckPattern, get_annotations_and_actions
from bar_raiser.utils.github import (
    Action,
    Annotation,
    create_check_run,
    get_git_repo,
    get_github_repo,
    initialize_logging,
)

if TYPE_CHECKING:
    from collections.abc import Callable

logger = getLogger(__name__)


CHECK_NAME = "python-ruff-report"
WOULD_REFORMAT_PATTERN = CheckPattern(
    regex="^Would reformat: (?P<path>.*)$",
    message="Ruff would reformat this file.",
    line=1,
    is_autofixable=True,
)
CANNOT_FORMAT_PATTERN = CheckPattern(
    regex="^error: Failed to format (?P<path>[^:]+): (?P<message>.*), offset: (?P<line>[0-9]+), .*$"
)
RUFF_FORMAT_PATTERNS = [
    WOULD_REFORMAT_PATTERN,
    CANNOT_FORMAT_PATTERN,
]
CHECK_ERROR_PATTERN = CheckPattern(
    regex="^(?P<path>[^:]+):(?P<line>[0-9]+):[0-9]+: (?P<message>.*)$"
)
CANNOT_PARSE_PATTERN = CheckPattern(
    regex="^error: Failed to parse (?P<path>[^:]+):(?P<line>[0-9]+):[0-9]+: (?P<message>.*)$"
)
FIXABLE_PATTERN = CheckPattern(
    regex="^.* fixable with the `--fix` option.$",
    should_create_annotation=False,
    is_autofixable=True,
)
RUFF_CHECK_PATTERNS = [CANNOT_PARSE_PATTERN, CHECK_ERROR_PATTERN, FIXABLE_PATTERN]


def main() -> None:
    initialize_logging()
    git_repo = get_git_repo()
    annotations: list[Annotation] = []
    actions: list[Action] = []
    cmds_parsers: list[
        tuple[list[str], Callable[[Path, str], tuple[list[Annotation], Action | None]]]
    ] = [
        (
            ["ruff", "format", "--check", "."],
            lambda wd, output: get_annotations_and_actions(
                wd, output, [WOULD_REFORMAT_PATTERN, CANNOT_FORMAT_PATTERN]
            ),
        ),
        (
            ["ruff", "check", "."],
            lambda wd, output: get_annotations_and_actions(
                wd, output, [CHECK_ERROR_PATTERN, CANNOT_PARSE_PATTERN, FIXABLE_PATTERN]
            ),
        ),
    ]
    RETURN_CODE_NOT_SET = -100
    return_code = RETURN_CODE_NOT_SET
    for cmds, parser in cmds_parsers:
        try:
            output = check_output(cmds, stderr=STDOUT)
            ruff_output = output.decode("utf-8")
            if return_code == RETURN_CODE_NOT_SET:
                return_code = 0
        except CalledProcessError as e:
            ruff_output = e.output.decode("utf-8")
            return_code = e.returncode
            new_annotations, action = parser(Path(git_repo.working_dir), ruff_output)
            annotations.extend(new_annotations)
            if len(actions) == 0 and action is not None:
                actions.append(action)

        logger.info(ruff_output)

    summary = f"Ruff found {len(annotations)} errors."
    if len(actions) > 0:
        summary += "Autofix is available. Simply click :point_up_2: the above `autofix` button to apply.\n"
        summary += "After the autofix, if you plan to continue developing, run `git pull --rebase` to fetch the changes in your working directory.\n\n"
        summary += "To fix format errors manually in your working directory, run: `ruff format .`"
        summary += "To fix check errors manually in your working directory, run: `ruff check --fix .`"

    checks = create_check_run(
        repo=get_github_repo(),
        name=CHECK_NAME,
        head_sha=git_repo.head.commit.parents[-1].hexsha,  # pyright: ignore[reportUnknownMemberType,reportUnknownArgumentType]
        conclusion="success" if len(annotations) == 0 else "action_required",
        title="Python Ruff formatter",
        summary=summary,
        annotations=annotations,
        actions=list(actions),
    )
    if len(actions) > 0:
        logger.info(
            f"Autofix is available. Simply click the autofix button on the following page to apply: {' '.join([check.html_url for check in checks])}"
        )
        logger.info(
            "After the autofix, if you plan to continue developing, run `git pull --rebase` to fetch the changes in your working directory."
        )
        logger.info(
            "To fix format errors manually in your working directory, run: `ruff format .`"
        )
        logger.info(
            "To fix check errors manually in your working directory, run: `ruff check --fix .`"
        )

    exit(return_code)


if __name__ == "__main__":
    main()
