from __future__ import annotations

from json import loads
from os import environ
from typing import TYPE_CHECKING

from slack.web.client import WebClient

from bar_raiser.utils.github import get_pull_request

if TYPE_CHECKING:
    from pathlib import Path

    from github.CheckRun import CheckRun


def post_a_slack_message(channel: str, text: str):
    client = WebClient(token=environ["SLACK_BOT_TOKEN"])
    client.chat_postMessage(channel=channel, text=text)


def get_slack_user_id_from_github_login(
    github_login: str, mapping_path: Path
) -> str | None:
    return loads(mapping_path.read_text()).get(github_login, None)


def dm_on_check_failure(checks: list[CheckRun], mapping_path: Path):
    pull = get_pull_request()

    if pull and not pull.draft:
        user_id = get_slack_user_id_from_github_login(pull.user.login, mapping_path)
        if user_id:
            failed_checks = [
                check
                for check in checks
                if check.conclusion in {"action_required", "failure"}
            ]
            if failed_checks:
                check_urls = " ".join(check.html_url for check in failed_checks)
                post_a_slack_message(
                    channel=user_id,
                    text=f"Github check `{failed_checks[0].name}` failed on <{pull.html_url}|PR-{pull.number}>: {check_urls}",
                )
