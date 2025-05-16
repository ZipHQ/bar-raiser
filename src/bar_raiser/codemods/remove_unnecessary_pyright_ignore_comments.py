from __future__ import annotations

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from typing import TYPE_CHECKING, ClassVar, cast

from libcst import Comment, Module, RemovalSentinel
from libcst.codemod import CodemodContext, VisitorBasedCodemodCommand
from libcst.metadata import PositionProvider

if TYPE_CHECKING:
    from libcst.metadata import CodeRange


@dataclass(frozen=True, slots=True)
class PyrightError:
    rule: str


class RemoveUnnecessaryPyrightIgnoreComments(VisitorBasedCodemodCommand):
    DESCRIPTION = """
    Removes unnecessary `pyright: ignore` comments.

    Command: ```

    python -m libcst.tool codemod --jobs=1 remove_unnecessary_pyright_ignore_comments.RemoveUnnecessaryPyrightIgnoreComments <path/to/file.py>

    ```
    """

    COMMENT_REGEX = r"(?:pyright|type): ignore(?:\[(.+)\])?"

    COMMENT_RULE_REGEX = r"pyright: ignore\[([a-zA-Z,]+)\]"

    COMMENT_VALUE = "pyright: ignore"

    METADATA_DEPENDENCIES = (PositionProvider,)

    # {filename}:{line}:{column} - error: Unnecessary " " rule: "{rule}"
    PYRIGHT_ERROR_REGEX = (
        r'(.+):(\d+):(\d+) - error: Unnecessary "# pyright: ignore" rule: "(\w+)"'
    )

    pyright_errors_by_comment: ClassVar[dict[Comment, list[PyrightError]]] = {}

    pyright_errors_by_line: ClassVar[dict[int, list[PyrightError]]] = {}

    pyright_errors_by_line_by_filename: ClassVar[
        dict[str, dict[int, list[PyrightError]]]
    ] = {}

    def __init__(self, context: CodemodContext) -> None:
        super().__init__(context)

        filenames = [self.context.filename] if self.context.filename else sys.argv[3:]
        pyright_project = cast(
            "str | None", self.context.scratch.get("pyright_project")
        )

        pyright_args = (
            [
                "pyright",
                "-p",
                pyright_project,
                *filenames,
            ]
            if pyright_project
            else ["pyright", *filenames]
        )

        pyright_stdout = (
            os.getenv("PYRIGHT_OUTPUT")
            or subprocess.run(
                pyright_args,
                capture_output=True,
                check=False,
                env=dict(os.environ, NODE_OPTIONS="--max-old-space-size=8192"),
                text=True,
            ).stdout
        )

        self._set_pyright_errors_by_line_by_filename(pyright_stdout)

    def _set_pyright_errors_by_line_by_filename(self, pyright_stdout: str) -> None:
        for filename, line, *_, rule in re.findall(
            self.PYRIGHT_ERROR_REGEX, pyright_stdout
        ):
            self.pyright_errors_by_line_by_filename.setdefault(
                filename.strip(), {}
            ).setdefault(int(line), []).append(PyrightError(rule=rule))

    def visit_Module(self, node: Module) -> bool | None:
        pyright_stdout = os.getenv("PYRIGHT_OUTPUT")

        if pyright_stdout:
            self._set_pyright_errors_by_line_by_filename(pyright_stdout)

        self.pyright_errors_by_line = {}  # pyright: ignore[reportAttributeAccessIssue]

        if (
            not self.context.filename
            or self.context.filename not in self.pyright_errors_by_line_by_filename
        ):
            return False

        self.pyright_errors_by_line = self.pyright_errors_by_line_by_filename[  # pyright: ignore[reportAttributeAccessIssue]
            self.context.filename
        ]

        return True

    def visit_Comment(self, node: Comment) -> bool | None:
        metadata = cast("CodeRange", self.get_metadata(PositionProvider, node))

        if metadata.start.line in self.pyright_errors_by_line:
            self.pyright_errors_by_comment[node] = self.pyright_errors_by_line[
                metadata.start.line
            ]

        return True

    def leave_Comment(  # pyright: ignore[reportIncompatibleMethodOverride]
        self, original_node: Comment, updated_node: Comment
    ) -> Comment | RemovalSentinel:
        if original_node not in self.pyright_errors_by_comment:
            return updated_node

        comment_rules = {
            comment_rule
            for _comment_rules in re.findall(
                self.COMMENT_RULE_REGEX, (original_node and original_node.value) or ""
            )
            for comment_rule in _comment_rules.split(",")
            if _comment_rules and comment_rule
        }

        comment_value: str | None = None

        pyright_errors = self.pyright_errors_by_comment[original_node]

        rules = comment_rules - {pyright_error.rule for pyright_error in pyright_errors}

        if rules:
            rules_str = ",".join(sorted(rules))

            pyright_ignore_comment_value = f"{self.COMMENT_VALUE}[{rules_str}]"

            comment_value = " ".join([
                pyright_ignore_comment_value,
                re.sub(self.COMMENT_REGEX, "", original_node.value)
                .replace("#", "")
                .strip(),
            ]).strip()

        return (
            Comment(f"# {comment_value}") if comment_value else RemovalSentinel.REMOVE
        )
