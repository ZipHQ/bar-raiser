from __future__ import annotations

from typing import TYPE_CHECKING

import libcst as cst
from libcst.codemod import CodemodContext

from bar_raiser.codemods.remove_unnecessary_pyright_ignore_comments import (
    RemoveUnnecessaryPyrightIgnoreComments,
)

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

SOURCE = (
    "a = 1  # pyright: ignore[reportFoo,reportBar]\n"
    "b = 2  # pyright: ignore[reportBaz]\n"
    "c = 3\n"
)


def test_removes_only_the_unnecessary_pyright_ignore_rules(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    path = tmp_path / "module.py"
    path.write_text(SOURCE)
    monkeypatch.setenv(
        "PYRIGHT_OUTPUT",
        f'{path}:1:5 - error: Unnecessary "# pyright: ignore" rule: "reportFoo"\n'
        f'{path}:2:5 - error: Unnecessary "# pyright: ignore" rule: "reportBaz"\n',
    )
    # The codemod keeps pyright's results in class-level dicts shared by every instance.
    for attribute in (
        "pyright_errors_by_comment",
        "pyright_errors_by_line",
        "pyright_errors_by_line_by_filename",
    ):
        monkeypatch.setattr(RemoveUnnecessaryPyrightIgnoreComments, attribute, {})

    codemod = RemoveUnnecessaryPyrightIgnoreComments(CodemodContext(filename=str(path)))
    result = codemod.transform_module(cst.parse_module(SOURCE)).code

    assert [line.rstrip() for line in result.splitlines()] == [
        "a = 1  # pyright: ignore[reportBar]",
        "b = 2",
        "c = 3",
    ]
