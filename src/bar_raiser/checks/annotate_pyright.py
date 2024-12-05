from __future__ import annotations

from json import loads
from logging import getLogger
from pathlib import Path
from subprocess import CalledProcessError, check_output
from sys import exit

from bar_raiser.utils.check import create_arg_parser
from bar_raiser.utils.github import (
    Action,
    Annotation,
    Autofixes,
    create_check_run,
    get_git_repo,
    get_github_repo,
    get_head_sha,
    initialize_logging,
)
from bar_raiser.utils.slack import dm_on_check_failure

logger = getLogger(__name__)

CHECK_NAME = "python-pyright-report"


def get_annotations_and_actions_for_pyright_check(
    working_dir: Path, pyright_output_json: str
) -> tuple[list[Annotation], list[Action]]:
    annotations: list[Annotation] = []
    data = loads(pyright_output_json)
    action_ids: set[str] = set()
    for error in data["generalDiagnostics"]:
        rule = f" [{error['rule']}]" if "rule" in error else ""
        annotations.append(
            Annotation(
                path=str(Path(error["file"]).relative_to(working_dir)),
                start_line=error["range"]["start"]["line"]
                + 1,  # pyright uses 0-based line numbers
                end_line=error["range"]["end"]["line"] + 1,
                annotation_level="failure",
                message=error["message"] + rule,
            )
        )
        if 'Unnecessary "# pyright: ignore"' in error["message"]:
            action_ids.add(Autofixes.PYRIGHT_IGNORES.value)
    actions = [
        Action(
            label="autofix",
            description="Click to auto-push an autofix commit",
            identifier=action_id,
        )
        for action_id in action_ids
    ]
    return annotations, actions


def main() -> None:
    initialize_logging()
    args = create_arg_parser().parse_args()
    git_repo = get_git_repo()
    annotations: list[Annotation] = []
    actions: list[Action] = []
    return_code = -1
    try:
        output = check_output(
            [
                "pyright",
                "--outputjson",
            ],
        )
        pyright_output_json = output.decode("utf-8")
        return_code = 0
    except CalledProcessError as e:
        pyright_output_json = e.output.decode("utf-8")
        annotations, actions = get_annotations_and_actions_for_pyright_check(
            Path(git_repo.working_dir), pyright_output_json
        )
        return_code = e.returncode

    summary = f"Pyright found {len(annotations)} errors."
    if len(actions) > 0:
        summary += "Autofix is available. Simply click :point_up_2: the above `autofix` button to apply.\n"
        summary += "After the autofix, if you plan to continue developing, run `git pull --rebase` to fetch the changes in your working directory.\n\n"

    logger.info(summary)
    for annotation in annotations:
        logger.info(
            f"{annotation['path']}:{annotation['start_line']}:{annotation['message']}"
        )
    checks = create_check_run(
        repo=get_github_repo(),
        name=CHECK_NAME,
        head_sha=get_head_sha(),
        conclusion="success" if len(annotations) == 0 else "action_required",
        title="Python Pyright Type Checker",
        summary=summary,
        annotations=annotations,
        actions=actions,
    )
    if args.slack_dm_on_failure:
        dm_on_check_failure(checks, args.slack_dm_on_failure)

    exit(return_code)


if __name__ == "__main__":
    main()
