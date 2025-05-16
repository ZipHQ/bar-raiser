from __future__ import annotations

from json import loads
from logging import getLogger
from os import environ
from typing import TYPE_CHECKING

from slack.web.client import WebClient

from bar_raiser.utils.github import get_pull_request

if TYPE_CHECKING:
    from pathlib import Path

    from github.CheckRun import CheckRun
    from slack.web.slack_response import SlackResponse

logger = getLogger(__name__)


def post_a_slack_message(
    channel: str, text: str, icon_url: str | None = None, username: str | None = None
):
    client = WebClient(token=environ["SLACK_BOT_TOKEN"])
    client.chat_postMessage(  # pyright: ignore[reportUnknownMemberType]
        channel=channel, text=text, icon_url=icon_url, username=username
    )


def get_slack_channel_from_mapping_path(key: str, mapping_path: Path) -> str | None:
    return loads(mapping_path.read_text()).get(key, None)


def dm_on_check_failure(
    checks: list[CheckRun], mapping_path: Path, message: str | None = None
):
    pull = get_pull_request()

    if pull and not pull.draft:
        user_id = get_slack_channel_from_mapping_path(pull.user.login, mapping_path)
        if user_id:
            failed_checks = [
                check
                for check in checks
                if check.conclusion in {"action_required", "failure"}
            ]
            if failed_checks:
                check_urls = " ".join(check.html_url for check in failed_checks)
                base_message = f"Github check `{failed_checks[0].name}` failed on <{pull.html_url}|PR-{pull.number}>: {check_urls}"
                slack_message = (
                    f"{message}\n\n{base_message}" if message else base_message
                )
                post_a_slack_message(
                    channel=user_id,
                    text=slack_message,
                )
    else:
        logger.info("No pull request found.")


def get_slack_user_icon_url_and_username(
    user_id: str,
) -> tuple[str, str] | tuple[None, None]:
    client = WebClient(token=environ["SLACK_BOT_TOKEN"])
    response: SlackResponse = client.users_info(user=user_id)  # pyright: ignore[reportUnknownMemberType,reportAssignmentType,reportUnknownVariableType]
    try:
        if response["ok"]:
            user_info = response["user"]  # pyright: ignore[reportUnknownVariableType]
            if user_info:
                return user_info["profile"]["image_72"], user_info["real_name"]  # pyright: ignore[reportUnknownVariableType]
    except Exception:
        logger.exception(f"Error getting slack user info for {user_id}.")
    return None, None
