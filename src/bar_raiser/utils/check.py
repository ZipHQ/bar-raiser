from __future__ import annotations

from argparse import ArgumentParser
from dataclasses import dataclass
from pathlib import Path
from re import match

from bar_raiser.utils.github import Action, Annotation, Autofixes


@dataclass(frozen=True)
class CheckPattern:
    regex: str
    message: str | None = None
    line: int | None = None
    should_create_annotation: bool = True
    is_autofixable: bool = False


def parse_line(
    pattern: CheckPattern, line: str, repo: Path
) -> tuple[Annotation | None, bool]:
    matched = match(pattern.regex, line)
    is_autofixable = pattern.is_autofixable
    if matched:
        line_num = int(matched.group("line")) if pattern.line is None else pattern.line
        return (
            Annotation(
                path=str(Path(Path.cwd() / matched.group("path")).relative_to(repo)),
                start_line=line_num,
                end_line=line_num,
                annotation_level="failure",
                message=matched.group("message")
                if pattern.message is None
                else pattern.message,
            ),
            is_autofixable,
        )
    return (None, is_autofixable)


def get_annotations_and_actions(
    repo_dir: Path, ruff_output: str, patterns: list[CheckPattern], autofix: Autofixes
) -> tuple[list[Annotation], Action | None]:
    annotations: list[Annotation] = []
    is_autofix_available = False
    for line in ruff_output.split("\n"):
        for pattern in patterns:
            if pattern.should_create_annotation:
                annotation, is_autofixable = parse_line(pattern, line, repo_dir)
                if annotation:
                    annotations.append(annotation)
                    if is_autofixable:
                        is_autofix_available = is_autofixable
            elif (
                is_autofix_available is False
                and pattern.is_autofixable
                and match(pattern.regex, line)
            ):
                is_autofix_available = True
    action = (
        Action(
            label="autofix",
            description="Click to auto-push an autofix commit",
            identifier=str(autofix),
        )
        if is_autofix_available
        else None
    )
    return annotations, action


def create_arg_parser() -> ArgumentParser:
    parser = ArgumentParser(
        description="Run checks and optionally send Slack DMs on failure."
    )
    parser.add_argument(
        "--slack-dm-on-failure",
        type=Path,
        help="Path to a JSON file containing a mapping from GitHub login to Slack user ID.",
        default=None,
    )
    return parser
