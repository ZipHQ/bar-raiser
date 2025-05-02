from __future__ import annotations

from argparse import ArgumentParser
from pathlib import Path

from bar_raiser.utils.check import create_arg_parser_with_slack_dm_on_failure


def test_create_arg_parser_with_slack_dm_on_failure():
    parser = create_arg_parser_with_slack_dm_on_failure()
    assert isinstance(parser, ArgumentParser)
    args = parser.parse_args(["--slack-dm-on-failure", "path/to/file.json"])
    assert args.slack_dm_on_failure == Path("path/to/file.json")
