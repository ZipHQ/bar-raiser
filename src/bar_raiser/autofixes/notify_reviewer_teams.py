from __future__ import annotations

import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from logging import getLogger
from pathlib import Path
from typing import TYPE_CHECKING

from github.Team import Team

from bar_raiser.utils.slack import (
    get_slack_user_icon_url_and_username,
)

if TYPE_CHECKING:
    from github.PullRequest import PullRequest


from bar_raiser.utils.github import get_pull_request, initialize_logging
from bar_raiser.utils.slack import (
    get_slack_channel_from_mapping_path,
    post_a_slack_message,
)

logger = getLogger(__name__)


LABEL_TO_REMOVE = "autofix-notify-reviewer-teams"


@dataclass
class ReviewRequest:
    team: str
    channel: str | None
    slack_id: str
    pull_request: PullRequest


def create_slack_message(review_request: ReviewRequest) -> str:
    """Create a Slack message for a review request."""
    return (
        f"Hi team, Could we please get reviews on <@{review_request.slack_id}>'s "
        f"<{review_request.pull_request.html_url}|PR-{review_request.pull_request.number}> "
        f"({review_request.pull_request.title})? A review from the *{review_request.team.split('/')[-1]}* "
        "team is required. Thanks! 🙏"
    )


def process_review_request(  # noqa: PLR0917
    request: Team,
    pull_request: PullRequest,
    slack_id: str,
    dry_run: str,
    github_team_to_slack_channels_path: Path,
    github_team_to_slack_channels_help_msg: str,
) -> tuple[str, bool]:
    """Process a single review request and return the comment and success status."""
    team = f"@{request.organization.login}/{request.slug}"
    channel = get_slack_channel_from_mapping_path(
        team, github_team_to_slack_channels_path
    )

    if channel is None:
        error_msg = f"Slack channel not found for Github team: {team}\n{github_team_to_slack_channels_help_msg}\n"
        logger.error(error_msg)
        return (
            error_msg,
            False,
        )

    if dry_run:
        channel = dry_run

    if channel:
        review_request = ReviewRequest(
            team=team, channel=channel, slack_id=slack_id, pull_request=pull_request
        )
        message = create_slack_message(review_request)
        icon_url, username = get_slack_user_icon_url_and_username(slack_id)

        post_a_slack_message(
            channel=channel,
            text=message,
            icon_url=icon_url,
            username=username,
        )

        success_msg = f"Sent message to [Slack channel](https://try-evergreen.slack.com/archives/{channel}) for reviewer {team}.\n"
        logger.info(
            f"Sent message to https://try-evergreen.slack.com/archives/{channel} for reviewer {team}."
        )
        return success_msg, True

    return "", False


def process_pull_request(  # noqa: PLR0917
    pull_request: PullRequest,
    dry_run: str,
    github_login_to_slack_ids_path: Path,
    github_login_to_slack_ids_help_msg: str,
    github_team_to_slack_channels_path: Path,
    github_team_to_slack_channels_help_msg: str,
    only_notify_team_slug: str | None,
) -> str:
    """Process all review requests for a pull request."""
    author_login = pull_request.user.login
    slack_id = get_slack_channel_from_mapping_path(
        author_login, github_login_to_slack_ids_path
    )
    if slack_id is None:
        comment = f"No author slack_id found for author {author_login}.\n{github_login_to_slack_ids_help_msg}\n"
        logger.error(comment)
        return comment

    accumulated_comments = ""

    for team_requests_list in pull_request.get_review_requests():  # noqa: PLR1702
        for requested_team_obj in team_requests_list:
            if isinstance(requested_team_obj, Team):
                current_team_slug = requested_team_obj.slug
                current_team_full_name = (
                    f"@{requested_team_obj.organization.login}/{current_team_slug}"
                )

                if only_notify_team_slug:
                    if current_team_slug == only_notify_team_slug:
                        single_request_comment, _ = process_review_request(
                            requested_team_obj,
                            pull_request,
                            slack_id,
                            dry_run,
                            github_team_to_slack_channels_path,
                            github_team_to_slack_channels_help_msg,
                        )
                        if single_request_comment:
                            accumulated_comments += single_request_comment
                        # Only process this team if it's the target
                    else:
                        logger.info(
                            f"Skipping notification for team {current_team_full_name} as --only-notify-team is set to {only_notify_team_slug}."
                        )
                else:
                    # No specific team targeted, process all teams
                    single_request_comment, _ = process_review_request(
                        requested_team_obj,
                        pull_request,
                        slack_id,
                        dry_run,
                        github_team_to_slack_channels_path,
                        github_team_to_slack_channels_help_msg,
                    )
                    if single_request_comment:
                        accumulated_comments += single_request_comment

    if len(accumulated_comments) == 0 and not only_notify_team_slug:
        return "No team review requests found."
    return accumulated_comments


def main() -> None:
    parser = ArgumentParser(
        description="Run checks and optionally send Slack DMs on failure."
    )
    parser.add_argument(
        "--dry-run",
        type=str,
        help="Dry run the autofix and send a message to a test Slack channel. Provide a test channel ID.",
        default="",
    )
    parser.add_argument(
        "github_login_to_slack_ids",
        type=Path,
        help="Path to a JSON file containing a mapping from GitHub login to Slack IDs.",
        default=None,
    )
    parser.add_argument(
        "github_login_to_slack_ids_help_msg",
        type=str,
        help="A help message for updating the github_login_to_slack_ids mapping file.",
        default="",
    )
    parser.add_argument(
        "github_team_to_slack_channels",
        type=Path,
        help="Path to a JSON file containing a mapping from GitHub team to Slack channels.",
        default=None,
    )
    parser.add_argument(
        "github_team_to_slack_channels_help_msg",
        type=str,
        help="A help message for updating the github_team_to_slack_channels mapping file.",
        default="",
    )
    parser.add_argument(
        "--only-notify-team",
        type=str,
        help="Only send notification to the specific team slug if they are a requested reviewer.",
        default=None,
    )
    args = parser.parse_args()
    pull = get_pull_request()
    dry_run = args.dry_run
    logger.info(f"Dry run: {dry_run}")

    if pull is None:
        logger.error("No pull request found.")
        sys.exit(1)

    if pull.draft:
        comment = "Pull request is a draft and is not ready for review."
        logger.error(comment)
    else:
        comment = process_pull_request(
            pull,
            args.dry_run,
            args.github_login_to_slack_ids,
            args.github_login_to_slack_ids_help_msg,
            args.github_team_to_slack_channels,
            args.github_team_to_slack_channels_help_msg,
            args.only_notify_team,
        )

    if comment:
        pull.create_issue_comment(body=comment)
    pull.remove_from_labels(LABEL_TO_REMOVE)


if __name__ == "__main__":
    initialize_logging()
    main()
