from __future__ import annotations

import json
import operator
import os
from calendar import monthrange
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime
from enum import StrEnum
from importlib import import_module
from inspect import isclass
from logging import getLogger
from pathlib import Path
from pkgutil import walk_packages
from re import match
from typing import TYPE_CHECKING, Any, cast

import libcst as cst
from dateutil.relativedelta import relativedelta
from fixit import CstLintRule
from fixit.cli import (
    map_paths,  # pyright: ignore[reportUnknownVariableType]
)
from fixit.cli.args import LintWorkers
from fixit.common.base import CstContext, LintConfig
from fixit.common.config import get_lint_config
from fixit.rule_lint_engine import _visit_cst_rules_with_context
from libcst.metadata import CodePosition, MetadataWrapper, PositionProvider

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping

    from fixit.common.report import BaseLintRuleReport
    from git import Commit, DiffIndex
    from git.diff import Diff
    from git.repo import Repo
    from libcst.metadata.base_provider import ProviderT
    from types_aiobotocore_s3 import S3Client


logger = getLogger(__name__)

S3_BUCKET = "s3-bucket"
S3_KEY_LEADERBOARD = "bar-raiser/leaderboard/"
S3_KEY_PATH_RESULTS = "bar-raiser/path_results/"
S3_KEY_HISTORY = "bar-raiser/history/"


@dataclass(frozen=True)
class Result:
    key: str
    path: str
    line: int
    col: int
    code: str
    patch: None
    count: int = 1


class CodeAnalyzerContext(CstContext):
    def __init__(
        self,
        wrapper: MetadataWrapper,
        source: bytes,
        file_path: Path,
        config: LintConfig,
    ) -> None:
        self.results: list[Result] = []
        super().__init__(wrapper, source, file_path, config)


class BaseCodeAnalyzer(CstLintRule):
    context: CodeAnalyzerContext

    def report(  # pyright: ignore[reportIncompatibleMethodOverride]
        self,
        node: cst.CSTNode,
        key: str,
        message: str | None = None,
        *,
        count: int = 1,
        position: CodePosition | None = None,
        replacement: cst.CSTNode | cst.RemovalSentinel | None = None,
    ) -> None:
        if position is None:
            position = self.context.wrapper.resolve(PositionProvider)[node].start
        self.context.results.append(
            Result(
                key=key,
                path=str(self.context.file_path),
                line=position.line,
                col=position.column,
                code=self.__class__.__name__,
                count=count,
                patch=None,
            )
        )
        return super().report(  # pyright: ignore[reportUnknownMemberType]
            node, message, position=position, replacement=replacement
        )


def lint_file(
    file_path: Path,
    source: bytes,
    *,
    use_ignore_byte_markers: bool = True,
    use_ignore_comments: bool = True,
    config: LintConfig,
    rules: Collection[type[CstLintRule]] = (),
    cst_wrapper: MetadataWrapper | None = None,
    find_unused_suppressions: bool = False,
) -> list[Result] | list[BaseLintRuleReport]:
    if cst_wrapper is None:
        cst_wrapper = MetadataWrapper(cst.parse_module(source), unsafe_skip_copy=True)

    use_code_analyzer = any(issubclass(rule, BaseCodeAnalyzer) for rule in rules)
    if use_code_analyzer:
        context = CodeAnalyzerContext(cst_wrapper, source, file_path, config)
        _visit_cst_rules_with_context(cst_wrapper, rules, context)
        return context.results
    context = CstContext(cst_wrapper, source, file_path, config)
    _visit_cst_rules_with_context(cst_wrapper, rules, context)
    return context.reports


@dataclass(frozen=True)
class LintOptions:
    rules: Collection[type[CstLintRule]]
    config: LintConfig


def index_to_coordinates(text: str, index: int) -> tuple[int, int]:
    """Returns (line_number, col) of `index` in `s`."""
    if not len(text):
        return 1, 1
    sp = text[: index + 1].splitlines(keepends=True)
    return len(sp), len(sp[-1])


class TechDebtCategory(StrEnum):
    WEIGHTED_SCORE = "Weighted Score"
    PYRIGHT_IGNORE = "pyright-ignore"
    BE_LINES = "BE-lines"


REGRESSION_TECH_DEBT_CATEGORIES = [  # Tech debt categories that could regress over time
    TechDebtCategory.BE_LINES,  # Only earn scores when making net reduction and will not lose scores when adding more debts
]

TECH_DEBT_SHOUT_OUT_THRESHOLD: dict[TechDebtCategory, int] = {
    TechDebtCategory.PYRIGHT_IGNORE: -1,
    TechDebtCategory.BE_LINES: -25,
}

TECH_DEBT_CONTRIBUTION_EXPLANATION: dict[TechDebtCategory, str] = {
    TechDebtCategory.PYRIGHT_IGNORE: "that improved backend type safety",
    TechDebtCategory.BE_LINES: "that cleaned up unused backend code and improved code quality",
}

TECH_DEBT_IMPACT: dict[TechDebtCategory, str] = {
    TechDebtCategory.PYRIGHT_IGNORE: "Fixing Pyright ignore comments can enhance type safety and reduce runtime errors by ensuring that all type issues are addressed during development.",
    TechDebtCategory.BE_LINES: "Removing unused backend code can simplify the codebase, making it easier to maintain and reducing potential confusion.",
}

CURRNET_QUARTER = "Q2"
QUARTER_BEGINNING = datetime(2025, 4, 1)
quarter_end = QUARTER_BEGINNING + relativedelta(months=2)
last_day = monthrange(quarter_end.year, quarter_end.month)[1]
QUARTER_END = quarter_end.replace(day=last_day)

TECH_DEBT_BEGINNING_AND_GOALS: dict[TechDebtCategory, tuple[int, int]] = {}

TECH_DEBT_WEIGHTS: dict[TechDebtCategory, int] = {
    TechDebtCategory.PYRIGHT_IGNORE: 10,
    TechDebtCategory.BE_LINES: 1,
}


TROPHY_EMOJI = ":trophy:"

NEW_TECH_DEBT_MESSAGE = "You're about to introduce new tech debt. Would you be able to address it upfront or, alternatively, tackle some existing tech debt from http://go/quality-wins offset the impact? :pray:"


def find_files(paths: Iterable[str | Path]) -> Iterator[str]:
    """
    Given an iterable of paths, yields any files and walks over any directories.
    """
    for path in paths:
        if os.path.isfile(path):
            yield str(path)
        else:
            for root, _dirs, files in os.walk(path):
                for f in files:
                    if not os.path.islink(f):
                        yield os.path.join(root, f)


def get_analyzed_results(
    path: Path, options: LintOptions, _: Mapping[ProviderT, object] | None
) -> list[Result]:
    try:
        if ".venv/" in str(path):
            return []
        source = path.read_bytes()
        source_str = source.decode("utf-8")
        match path.suffix:
            case ".py":
                results: list[Result] = cast(
                    "list[Result]",
                    lint_file(
                        path,
                        source,
                        rules=options.rules,
                        config=options.config,
                        cst_wrapper=None,
                        find_unused_suppressions=True,
                    ),
                )
                results.append(
                    Result(
                        key=TechDebtCategory.BE_LINES.value,
                        path=str(path),
                        line=1,
                        col=1,
                        code=TechDebtCategory.BE_LINES.value,
                        patch=None,
                        count=sum(1 for _ in source_str.split("\n")),
                    )
                )
                return results
    except Exception as exp:
        print(exp)
    return []


class DataclassJSONEncoder(json.JSONEncoder):
    def default(
        self,
        o: Any,
    ):
        if is_dataclass(o):
            return asdict(o)  # pyright: ignore[reportArgumentType]
        return super().default(o)


def get_analyzers() -> set[type[BaseCodeAnalyzer]]:
    package = import_module("bar_raiser.tech_debt_framework.analyzers")
    analyzers: set[type[BaseCodeAnalyzer]] = set()
    for _loader, name, _is_pkg in walk_packages(package.__path__):
        full_name = package.__name__ + "." + name
        try:
            module = import_module(full_name)
            for obj_name in dir(module):
                obj = getattr(module, obj_name)
                if (
                    isclass(obj)
                    and obj is not BaseCodeAnalyzer
                    and issubclass(obj, BaseCodeAnalyzer)
                ):
                    analyzers.add(obj)
        except ModuleNotFoundError:
            pass
    return analyzers


def remove_delta(
    delta: Counter[TechDebtCategory], path_results: PathResults, path: str
) -> None:
    if path and path in path_results:
        for result in path_results[path]:
            delta[TechDebtCategory(result.key)] -= result.count
        del path_results[path]


def get_delta(
    path_results: PathResults,
    diffs: DiffIndex[Diff],
    analyzers: set[type[BaseCodeAnalyzer]],
) -> Counter[TechDebtCategory]:
    delta = Counter[TechDebtCategory]()
    updated_paths: set[str] = set()
    for diff in diffs:
        if diff.a_path:
            remove_delta(delta, path_results, diff.a_path)
        b_path = diff.b_path
        if b_path:
            updated_paths.add(b_path)

    results = PathResults.analyze_paths(list(updated_paths), analyzers)
    for path, rlts in results.items():
        for result in rlts:
            delta[TechDebtCategory(result.key)] += result.count
        path_results[path] = rlts
    zero_keys = [key for key, val in delta.items() if val == 0]
    for key in zero_keys:
        del delta[key]
    return delta


def get_delta_value_with_emoji(delta_value: int, with_emoji: bool = True) -> str:
    if delta_value > 0:
        return f"{delta_value:+,d}{' :cry:' if with_emoji else ''}"
    if delta_value < 0:
        return f"{delta_value:,} :tada:"
    return str(f"{delta_value:,}")


def get_progress_text(beginning: int, goal: int, current: int) -> str:
    today = datetime.now()
    expected = beginning + (today - QUARTER_BEGINNING).total_seconds() / (
        QUARTER_END - QUARTER_BEGINNING
    ).total_seconds() * (goal - beginning)
    if current > expected:
        return f":warning: expecting {expected:,.0f}"
    return ":white_check_mark: on track"


class PathResults(dict[str, list[Result]]):
    @staticmethod
    def load(path: str) -> PathResults:
        path_results = PathResults()
        with open(path, encoding="utf-8") as f:
            raw_path_results = json.load(f)
            for sub_path, results in raw_path_results.items():
                path_results[sub_path] = [Result(**result) for result in results]
        return path_results

    @staticmethod
    async def load_with_commit(s3: S3Client, commit: Commit) -> PathResults:
        local_json_path = f"path_results-{commit.hexsha}.json"
        if not Path(local_json_path).exists():
            s3_key = f"{S3_KEY_PATH_RESULTS}{commit.hexsha}.json"
            await s3.download_file(
                S3_BUCKET,
                s3_key,
                local_json_path,
            )
            logger.info(f"Successfully downloaded {s3_key}")
        return PathResults.load(local_json_path)

    def dump(self, path: str) -> None:
        json.dump(
            obj=self,
            fp=open(path, "w", encoding="utf-8"),
            cls=DataclassJSONEncoder,
            indent=2,
        )

    async def upload_to_s3(self, s3: S3Client, commit: Commit) -> None:
        local_json_path = f"path_results-{commit.hexsha}.json"
        self.dump(local_json_path)
        s3_key = f"{S3_KEY_PATH_RESULTS}{commit.hexsha}.json"
        await s3.upload_file(local_json_path, S3_BUCKET, s3_key)
        logger.info(f"Successfully uploaded {s3_key}")

    def __getitem__(self, __key: str) -> list[Result]:
        if __key not in self:
            super().__setitem__(__key, [])
        return super().__getitem__(__key)

    @staticmethod
    def analyze_paths(
        paths: list[str],
        analyzers: set[type[BaseCodeAnalyzer]],
        workers: LintWorkers = LintWorkers.CPU_COUNT,
    ) -> PathResults:
        path_results = PathResults()
        print(analyzers)
        for results in map_paths(  # pyright: ignore[reportUnknownVariableType]
            get_analyzed_results,
            {str(path) for path in find_files(paths)},
            LintOptions(
                rules=analyzers,
                config=get_lint_config(),
            ),
            workers=workers,
        ):
            for result in results:  # pyright: ignore[reportUnknownVariableType]
                result = cast("Result", result)
                path_results[result.path].append(result)
        return path_results

    def get_key_counts(self) -> Counter[TechDebtCategory]:
        counter = Counter[TechDebtCategory]()
        for results in self.values():
            for result in results:
                counter[TechDebtCategory(result.key)] += result.count
        return counter

    @staticmethod
    async def gen_from_incremental_analysis(  # noqa: PLR0917
        s3: S3Client,
        git_repo: Repo,
        base_commit: Commit,
        head_commit: Commit,
        paths: list[str],
        analyzers: set[type[BaseCodeAnalyzer]],
        force_recompute: bool = False,
    ) -> tuple[Counter[TechDebtCategory], PathResults]:
        if force_recompute:
            git_repo.git.checkout(base_commit)
            logger.info(f"git checkout {base_commit}")
            path_results = PathResults.analyze_paths(paths, analyzers)
            git_repo.git.checkout(head_commit)
            logger.info(f"git checkout {head_commit}")
        else:
            try:
                path_results = await PathResults.load_with_commit(s3, base_commit)
            except Exception:
                logger.warning(
                    f"Failed to download PathResults. Checkout {base_commit}"
                )
                git_repo.git.checkout(base_commit)
                path_results = PathResults.analyze_paths(paths, analyzers)
                try:
                    await path_results.upload_to_s3(s3, base_commit)
                except Exception:
                    logger.warning("Failed to upload PathResults to s3.")
                git_repo.git.checkout(head_commit)

        delta = get_delta(
            path_results,
            base_commit.diff(  # pyright: ignore[reportUnknownArgumentType,reportUnknownMemberType]
                head_commit
            ),
            analyzers,
        )
        logger.info(f"Delta: {delta}")
        try:
            await path_results.upload_to_s3(s3, head_commit)
        except Exception:
            logger.warning("Failed to upload PathResults to s3.")
        return delta, path_results

    def get_markdown_summary(
        self,
        delta: Counter[TechDebtCategory],
        author: str,
        cumulative_delta: Counter[TechDebtCategory] | None = None,
    ) -> str:
        overall = self.get_key_counts()

        show_regression_notice = False
        for key, value in delta.items():
            if key not in REGRESSION_TECH_DEBT_CATEGORIES and value > 0:
                show_regression_notice = True

        output = f"## Tech Debt Contribution Summary for {author}\n\n"
        if show_regression_notice:
            output += f"> [!CAUTION]\n> {NEW_TECH_DEBT_MESSAGE}\n\n"
        output += f"| Tech Debt | {CURRNET_QUARTER} Goal | Remaining | Progress Check | Weight | Upcoming Contribution from this PR |"
        if cumulative_delta:
            output += f" Your Contribution in 2025 {CURRNET_QUARTER} |"
        output += "\n|:---------:|:----------:|:----------:|:----------:|:----------:|:-----------:|"
        if cumulative_delta:
            output += ":-----------:|"
        output += "\n"

        for key, val in sorted(overall.items(), key=operator.itemgetter(0)):
            if key in TECH_DEBT_BEGINNING_AND_GOALS:
                beginning, goal = TECH_DEBT_BEGINNING_AND_GOALS[key]
                progress = get_progress_text(beginning, goal, val)
                goal_text = f"{goal:,}"
            else:
                progress = "N/A"
                goal_text = "N/A"
            output += (
                "| "
                + key
                + " | "
                + goal_text
                + " | "
                + f"{val:,}"
                + " | "
                + progress
                + " | "
                + str(TECH_DEBT_WEIGHTS.get(key, "N/A"))
                + " | "
                + get_delta_value_with_emoji(
                    delta.get(key, 0),
                    key not in REGRESSION_TECH_DEBT_CATEGORIES,
                )
            )
            if cumulative_delta:
                cumulative_value = cumulative_delta.get(key, 0)
                output += " | " + str(
                    get_delta_value_with_emoji(
                        cumulative_value,
                        key not in REGRESSION_TECH_DEBT_CATEGORIES,
                    )
                )

            output += " |\n"
        output += "\n"
        return output


class History:
    def __init__(self) -> None:
        self.data: dict[str, list[tuple[str, Counter[TechDebtCategory]]]] = {}

    @staticmethod
    def load(path: str) -> History:
        history = History()
        with open(path, encoding="utf-8") as f:
            raw_history = json.load(f)
            for author, items in raw_history.items():
                history.data[author] = [(sha, Counter(delta)) for sha, delta in items]
        return history

    @staticmethod
    async def load_with_commit(s3: S3Client, commit: Commit) -> History:
        local_json_path = f"history-{commit.hexsha}.json"
        if not Path(local_json_path).exists():
            s3_key = f"{S3_KEY_HISTORY}{commit.hexsha}.json"
            await s3.download_file(
                S3_BUCKET,
                s3_key,
                local_json_path,
            )
            logger.info(f"Successfully downloaded {s3_key}")
        return History.load(local_json_path)

    def dump(self, path: str) -> None:
        json.dump(
            obj=self.data,
            fp=open(path, "w", encoding="utf-8"),
            indent=2,
        )

    async def upload_to_s3(self, s3: S3Client, commit: Commit) -> None:
        local_json_path = f"history-{commit.hexsha}.json"
        self.dump(local_json_path)
        s3_key = f"{S3_KEY_HISTORY}{commit.hexsha}.json"
        await s3.upload_file(local_json_path, S3_BUCKET, s3_key)
        logger.info(f"Successfully uploaded {s3_key}")

    def add_delta(
        self,
        author: str,
        sha: str,
        delta: Counter[TechDebtCategory],
        weighted_score: int,
    ) -> None:
        if TechDebtCategory.WEIGHTED_SCORE not in delta:
            delta[TechDebtCategory.WEIGHTED_SCORE] = weighted_score
        if author not in self.data:
            self.data[author] = []
        self.data[author].append((sha, delta))

    def get_markdown_summary(self, author: str) -> str:
        output = f"## Tech Debt Contribution History for {author}\n\n"
        output += "> [!NOTE]\n> The scores in parentheses represent the weighted delta, which is added to the overall weighted score. The scores inside parenthes are weighted delta that is added to the weigted scores. There's no penalty for adding new FE-lines or BE-lines. You'll earn points in these categories when you achieve a net reduction in lines of code.\n\n"
        output += "| Commit | "
        if author not in self.data:
            return output
        tech_debt_keys = list(TechDebtCategory)
        for key in tech_debt_keys:
            output += f" {key} |"
        output += "\n|:----------|"
        for _ in tech_debt_keys:
            output += "----------:|"
        output += "\n"
        for sha, delta in self.data[author]:
            output += (
                f"| [{sha[:7]}](https://github.com/ZipHQ/bar-raisercommit/{sha}) |"
            )
            for key in tech_debt_keys:
                raw_score = delta.get(key, 0)
                output += get_delta_value_with_emoji(
                    raw_score,
                    key
                    not in {
                        *REGRESSION_TECH_DEBT_CATEGORIES,
                        TechDebtCategory.WEIGHTED_SCORE,
                    },
                )
                if raw_score != 0 and key not in {
                    *REGRESSION_TECH_DEBT_CATEGORIES,
                    TechDebtCategory.WEIGHTED_SCORE,
                }:
                    output += f" ({raw_score * TECH_DEBT_WEIGHTS[key]:+,d})"
                output += " |"
            output += "\n"
        return output


def ordinal(n: int):
    # Convert an integer to its ordinal representation.
    if 11 <= n % 100 <= 13:  # Special cases for 11th, 12th, 13th
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


class LeaderBoard:
    contribution_summary: str = ""

    def __init__(self) -> None:
        self.board: dict[str, Counter[TechDebtCategory]] = defaultdict(Counter)

    @staticmethod
    def load(path: str) -> LeaderBoard:
        leaderboard = LeaderBoard()
        with open(path, encoding="utf-8") as f:
            raw_leaderboard = json.load(f)
            for author, delta in raw_leaderboard.items():
                leaderboard.board[author] = Counter(delta)
        return leaderboard

    @staticmethod
    async def load_with_commit(s3: S3Client, commit: Commit) -> LeaderBoard:
        local_json_path = f"leaderboard-{commit.hexsha}.json"
        if not Path(local_json_path).exists():
            s3_key = f"{S3_KEY_LEADERBOARD}{commit.hexsha}.json"
            await s3.download_file(
                S3_BUCKET,
                s3_key,
                local_json_path,
            )
            logger.info(f"Successfully downloaded {s3_key}")
        return LeaderBoard.load(local_json_path)

    def dump(self, path: str) -> None:
        json.dump(
            obj=self.board,
            fp=open(path, "w", encoding="utf-8"),
            indent=2,
        )

    async def upload_to_s3(self, s3: S3Client, commit: Commit) -> None:
        local_json_path = f"leaderboard-{commit.hexsha}.json"
        self.dump(local_json_path)
        s3_key = f"{S3_KEY_LEADERBOARD}{commit.hexsha}.json"
        await s3.upload_file(local_json_path, S3_BUCKET, s3_key)
        logger.info(f"Successfully uploaded {s3_key}")

    def add_delta_and_check_contribution(
        self, author: str, delta: Counter[TechDebtCategory]
    ) -> None:
        tech_debt_regression = ""
        for key, count in delta.items():
            if key in {
                *REGRESSION_TECH_DEBT_CATEGORIES,
                TechDebtCategory.WEIGHTED_SCORE,
            }:
                continue
            if count > 0:
                tech_debt_regression += f"- {key}: +{count}\n"
        self.tech_debt_regression = tech_debt_regression

        contribution_summary = ""
        for key, count in delta.items():
            if count <= TECH_DEBT_SHOUT_OUT_THRESHOLD.get(
                key, -1
            ):  # shout out when making a contribution meets the threshold
                if len(contribution_summary) > 0:
                    contribution_summary += ", and "
                contribution_summary += f"fixing *{count * -1} {key}* {TECH_DEBT_CONTRIBUTION_EXPLANATION.get(key, '')}"
            self.board[author][key] += count
        self.contribution_summary = contribution_summary

    def compute_weighted_score(self) -> None:
        for winner, delta in self.board.items():
            weighted_scores = 0
            for key, score in delta.items():
                if (
                    key in REGRESSION_TECH_DEBT_CATEGORIES and score > 0
                ) or key == TechDebtCategory.WEIGHTED_SCORE:
                    continue
                weighted_scores += score * TECH_DEBT_WEIGHTS[key]
            self.board[winner][TechDebtCategory.WEIGHTED_SCORE] = weighted_scores

    def get_markdown_summary(self, author: str, limit: int = 30) -> str:  # noqa: PLR0912
        tech_debt_keys = list(TechDebtCategory)
        output = f"## 2025 {CURRNET_QUARTER} Code Quality Award Leaderboard\n\n"
        output += f"> [!NOTE]\n> At the end of {CURRNET_QUARTER} ({QUARTER_END.strftime('%m/%d/%Y')}), an award committee will select 5 winners base on the [weighted](https://github.com/Greenbax/evergreen/blob/master/website/fixit_linters/analyzers/utils.py) scores to distribute the awards!\n\n"
        tech_debt_ranks: dict[str, list[tuple[str, int]]] = defaultdict(list)
        output += "|"
        for key in tech_debt_keys:
            output += f" {key} contribution | Rank |"
            for winner, delta in self.board.items():
                tech_debt_ranks[key].append((winner, delta[key]))
        output += "\n|"
        for _ in tech_debt_keys:
            output += "----------:|:----------|"
        output += "\n"

        for ranks in tech_debt_ranks.values():
            ranks.sort(key=operator.itemgetter(1))
        notes: dict[str, list[str]] = defaultdict(list)
        detail = ""
        num_trophies = 0
        for rank in range(len(self.board)):
            if rank < limit:
                detail += "|"
            for key in tech_debt_keys:
                winner, score = tech_debt_ranks[key][rank]
                winner_text = winner
                if winner == author:
                    winner_text = f"**{winner}** :point_left:"
                    notes[key].append(f"Your rank: **{ordinal(rank + 1)}**.")
                    if rank - 1 >= 0:
                        score_diff = tech_debt_ranks[key][rank - 1][1] - score
                        if score_diff == 0:
                            score_diff = -1
                        notes[key].append(
                            f"You need {score_diff:,} contribution to Rank Up :rocket:"
                        )
                        if (
                            key == TechDebtCategory.WEIGHTED_SCORE
                            and self.contribution_summary
                        ):
                            self.contribution_summary += f". You're currently ranked *{ordinal(rank + 1)}* and need *{-1 * score_diff:,}* more weighted scores to rank up 🚀"
                    elif (
                        key == TechDebtCategory.WEIGHTED_SCORE
                        and self.contribution_summary
                    ):
                        self.contribution_summary += f". You're currently ranked *{ordinal(rank + 1)}* 🚀 Keep it up!"
                spaces = 25 - len(winner_text)
                WINNER_EXCLUSIONS = set[str]([
                    "zip-bar-raiser[bot]",
                ])
                if rank < limit:
                    emoji = (
                        TROPHY_EMOJI
                        if num_trophies < 5
                        and key == TechDebtCategory.WEIGHTED_SCORE
                        and winner not in WINNER_EXCLUSIONS
                        else ""
                    )
                    if emoji == TROPHY_EMOJI:
                        num_trophies += 1
                    detail += f" {score:,} | {emoji} {rank + 1} {winner_text} {' ' * (max(0, spaces))} |"
            detail += "\n"
        if notes:
            output += "|"
            for key in tech_debt_keys:
                notes_list = notes[key]
                if notes_list:
                    output += f" {notes_list[0]} |"
                output += f" {notes_list[1]} |" if len(notes_list) > 1 else " |"
            output += "\n"
        output += detail
        return output


def get_pr_num_from_commit_message(commit_message: str) -> str:
    matched = match(
        r"^.*\(#(?P<PR_NUMBER>[0-9]+)\)$",
        commit_message,
    )
    return matched.group("PR_NUMBER") if matched else ""
