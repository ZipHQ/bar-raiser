from __future__ import annotations

import json
from os import environ
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

from github.CheckRun import CheckRun
from github.PullRequest import PullRequest

from bar_raiser.utils.slack import dm_on_check_failure, post_a_slack_message

if TYPE_CHECKING:
    from pathlib import Path


@patch.dict(environ, {"SLACK_BOT_TOKEN": "xxx"})
def test_post_a_slack_message() -> None:
    CHANNEL = "C06V783RYAA"
    with patch("bar_raiser.utils.slack.WebClient") as mock_web_client:
        post_a_slack_message(CHANNEL, "test message")
        mock_web_client.return_value.chat_postMessage.assert_called_with(
            channel=CHANNEL, icon_url=None, text="test message", username=None
        )


def test_dm_on_check_failure(tmp_path: Path):
    # Create a dummy mapping file
    mapping_file = tmp_path / "user_mapping.json"
    channel = "U15NC768RK1"
    mapping_data = {"jimmy-lai-zip": channel}  # Example mapping
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(mapping_data, f)

    with (
        patch(
            "bar_raiser.utils.slack.get_pull_request",
            return_value=MagicMock(
                spec=PullRequest,
                draft=False,
                user=MagicMock(login="jimmy-lai-zip"),
                html_url="github.com/pull/1",
                number=1,
            ),
        ),
        patch(
            "bar_raiser.utils.slack.post_a_slack_message"
        ) as mock_post_a_slack_message,
    ):
        checks: list[CheckRun] = [
            MagicMock(
                spec=CheckRun,
                html_url="github.com/check/1",
                conclusion="action_required",
            ),
            MagicMock(
                spec=CheckRun,
                html_url="github.com/check/2",
                conclusion="success",
            ),
        ]
        checks[0].name = "check1"  # pyright: ignore[reportAttributeAccessIssue]
        checks[1].name = "check2"  # pyright: ignore[reportAttributeAccessIssue]
        dm_on_check_failure(checks, mapping_file)
        mock_post_a_slack_message.assert_called_once_with(
            channel=channel,
            text="Github check `check1` failed on <github.com/pull/1|PR-1>: github.com/check/1",
        )
