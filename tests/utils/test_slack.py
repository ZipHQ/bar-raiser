from __future__ import annotations

from os import environ
from unittest.mock import patch

from bar_raiser.utils.slack import post_a_slack_message


@patch.dict(environ, {"SLACK_BOT_TOKEN": "xxx"})
def test_post_a_slack_message() -> None:
    CHANNEL = "C06V783RYAA"
    with patch("bar_raiser.utils.slack.WebClient") as mock_web_client:
        post_a_slack_message(CHANNEL, "test message")
        mock_web_client.return_value.chat_postMessage.assert_called_with(
            channel=CHANNEL, icon_url=None, text="test message", username=None
        )
