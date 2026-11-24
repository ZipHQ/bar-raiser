from __future__ import annotations

from pathlib import Path

from bar_raiser.tech_debt_framework.utils import (
    TechDebtCategory,
    get_analyzers,
    get_lint_config,
    lint_file,
)

SOURCE = b"x = 1  # pyright: ignore[reportFoo]\ny = 2\n"


def test_get_analyzers_finds_the_pyright_analyzer():
    assert "FindPyrightIgnores" in {analyzer.__name__ for analyzer in get_analyzers()}


def test_lint_file_reports_the_pyright_ignore_comment():
    results = lint_file(
        Path("sample.py"), SOURCE, config=get_lint_config(), rules=get_analyzers()
    )

    assert (TechDebtCategory.PYRIGHT_IGNORE.value, 1) in [
        (result.key, result.line)  # pyright: ignore[reportAttributeAccessIssue]
        for result in results
    ]
