from __future__ import annotations

from typing import TYPE_CHECKING

from fixit import InvalidTestCase as Invalid

from bar_raiser.tech_debt_framework.utils import BaseCodeAnalyzer, TechDebtCategory

if TYPE_CHECKING:
    from libcst import Comment


class FindPyrightIgnores(BaseCodeAnalyzer):
    INVALID = [  # noqa: RUF012
        Invalid("slack_text = subject  # pyright: ignore[reportUnboundVariable]")
    ]

    def visit_Comment(self, node: Comment) -> bool | None:
        if node.value.startswith("# pyright: ignore"):
            self.report(
                node,
                TechDebtCategory.PYRIGHT_IGNORE.value,
                "Pyright ignore comment found",
            )
        return super().visit_Comment(node)
