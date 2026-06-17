from __future__ import annotations

import random
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from json import loads
from logging import getLogger
from os import environ
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
    get_id_from_mapping_path,
    post_a_slack_message,
)

logger = getLogger(__name__)


LABEL_TO_REMOVE = "autofix-notify-reviewer-teams"


@dataclass
class ReviewRequest:
    team: str
    channel: str | None
    slack_id: str | None
    pull_request: PullRequest
    reviewers: list[str]
    is_random_assignment: bool = False
    is_blame_suggestion: bool = False
    summary: str | None = None


def create_slack_message(review_request: ReviewRequest) -> str:
    """Create a Slack message for a review request."""
    if review_request.reviewers:
        reviewer_mentions = [f"<@{reviewer}>" for reviewer in review_request.reviewers]

        if review_request.is_blame_suggestion:
            # Suggested from git blame: "maybe @alice or @bob since they
            # recently touched these lines"
            reviewer_text = (
                f"maybe {' or '.join(reviewer_mentions)} "
                "since they recently touched these lines"
            )
        elif review_request.is_random_assignment:
            # Randomly assigned reviewers: "maybe @alice or @bob"
            reviewer_text = f"maybe {' or '.join(reviewer_mentions)}"
        else:
            # Explicitly assigned reviewers: "assigned to @alice" or "assigned to @alice, @bob"
            reviewer_text = f"assigned to {', '.join(reviewer_mentions)}"
    else:
        reviewer_text = "none assigned"

    pr_link = f"<{review_request.pull_request.html_url}|PR-{review_request.pull_request.number}>"

    if review_request.slack_id:
        pr_reference = f"<@{review_request.slack_id}>'s {pr_link}"
    else:
        pr_reference = pr_link

    message = (
        f"Hi team, Could we please get reviews on {pr_reference} "
        f"({review_request.pull_request.title})? A review from the *{review_request.team.split('/')[-1]}* "
        f"team ({reviewer_text}) is required. Thanks! 🙏"
    )

    if review_request.summary:
        message += f"\n{review_request.summary}"

    return message


def get_suggested_reviewers_for_team(
    team: str, suggested_reviewers_json_path: Path | None
) -> list[str]:
    """Return pre-computed suggested reviewer logins for a team, if any.

    The JSON maps a GitHub team (``@org/slug``) to a list of GitHub logins
    (e.g. from git blame). Returns an empty list when the file or key is
    absent so the caller falls back to the random pick.
    """
    if suggested_reviewers_json_path is None:
        return []
    mapping: dict[str, list[str]] = loads(  # noqa: PLW1514
        suggested_reviewers_json_path.read_text()
    )
    return mapping.get(team, [])


def process_review_request(  # noqa: PLR0917, PLR0914
    request: Team,
    pull_request: PullRequest,
    slack_id: str | None,
    dry_run: str,
    github_team_to_slack_channels_path: Path,
    github_team_to_slack_channels_help_msg: str,
    individual_reviewers: list[str],
    github_login_to_slack_ids_path: Path,
    summary_json_path: Path | None = None,
    suggested_reviewers_json_path: Path | None = None,
) -> tuple[str, bool]:
    """Process a single review request and return the comment and success status."""
    team = f"@{request.organization.login}/{request.slug}"
    channel = get_id_from_mapping_path(team, github_team_to_slack_channels_path)

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
        # Filter reviewers to only include members of this team
        team_members = {member.login for member in request.get_members()}
        filtered_github_reviewers = [
            r for r in individual_reviewers if r in team_members
        ]

        # Convert GitHub logins to Slack IDs
        reviewer_slack_ids: list[str] = []
        for github_login in filtered_github_reviewers:
            reviewer_slack_id = get_id_from_mapping_path(
                github_login, github_login_to_slack_ids_path
            )
            if reviewer_slack_id:
                reviewer_slack_ids.append(reviewer_slack_id)

        # Track how reviewers were chosen, which changes the message wording.
        is_random = False
        is_blame_suggestion = False

        # If no reviewers assigned, prefer pre-computed suggestions (e.g. from
        # git blame), filtered to current team members; otherwise pick randomly.
        if not reviewer_slack_ids and team_members:
            team_members_list = [
                m for m in team_members if m != pull_request.user.login
            ]
            suggested = [
                login
                for login in get_suggested_reviewers_for_team(
                    team, suggested_reviewers_json_path
                )
                if login in team_members and login != pull_request.user.login
            ]

            if suggested:
                is_blame_suggestion = True
                chosen = suggested
                logger.info(f"Suggested reviewers from team {team} via git blame")
            else:
                is_random = True
                num_to_pick = min(2, len(team_members_list))
                chosen = random.sample(team_members_list, num_to_pick)
                logger.info(f"Randomly suggested reviewers from team {team}")

            for github_login in chosen:
                reviewer_slack_id = get_id_from_mapping_path(
                    github_login, github_login_to_slack_ids_path
                )
                if reviewer_slack_id:
                    reviewer_slack_ids.append(reviewer_slack_id)

        summary = (
            get_id_from_mapping_path(team, summary_json_path)
            if summary_json_path is not None
            else None
        )

        review_request = ReviewRequest(
            team=team,
            channel=channel,
            slack_id=slack_id,
            pull_request=pull_request,
            reviewers=reviewer_slack_ids,
            is_random_assignment=is_random,
            is_blame_suggestion=is_blame_suggestion,
            summary=summary,
        )
        message = create_slack_message(review_request)
        if slack_id:
            icon_url, username = get_slack_user_icon_url_and_username(slack_id)
        else:
            icon_url, username = None, None

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


def process_pull_request(  # noqa: PLR0917, PLR0912
    pull_request: PullRequest,
    dry_run: str,
    github_login_to_slack_ids_path: Path,
    github_login_to_slack_ids_help_msg: str,
    github_team_to_slack_channels_path: Path,
    github_team_to_slack_channels_help_msg: str,
    only_notify_team_slug: str | None,
    summary_json_path: Path | None = None,
    suggested_reviewers_json_path: Path | None = None,
) -> str:
    """Process all review requests for a pull request."""
    author_login = pull_request.user.login

    if author_login.endswith("[bot]"):
        # Bot-authored PR: use the label sender (GITHUB_ACTOR) instead
        label_sender = environ.get("GITHUB_ACTOR")
        if label_sender:
            slack_id = get_id_from_mapping_path(
                label_sender, github_login_to_slack_ids_path
            )
        else:
            slack_id = None
    else:
        slack_id = get_id_from_mapping_path(
            author_login, github_login_to_slack_ids_path
        )
        if slack_id is None:
            comment = f"No author slack_id found for author {author_login}.\n{github_login_to_slack_ids_help_msg}\n"
            logger.error(comment)
            return comment

    accumulated_comments = ""

    # Get review requests - returns (teams, users)
    review_requests = pull_request.get_review_requests()

    # Collect individual reviewer logins
    individual_reviewers = [
        item.login
        for item_list in review_requests
        for item in item_list
        if not isinstance(item, Team)
    ]

    for team_requests_list in review_requests:  # noqa: PLR1702
        for requested_team_obj in team_requests_list:
            if isinstance(requested_team_obj, Team):
                current_team_slug = requested_team_obj.slug

                if only_notify_team_slug:
                    if current_team_slug == only_notify_team_slug:
                        single_request_comment, _ = process_review_request(
                            requested_team_obj,
                            pull_request,
                            slack_id,
                            dry_run,
                            github_team_to_slack_channels_path,
                            github_team_to_slack_channels_help_msg,
                            individual_reviewers,
                            github_login_to_slack_ids_path,
                            summary_json_path,
                            suggested_reviewers_json_path,
                        )
                        if single_request_comment:
                            accumulated_comments += single_request_comment
                        # Only process this team if it's the target
                    else:
                        logger.info(
                            f"Skipping notification for team {current_team_slug} as --only-notify-team is set to {only_notify_team_slug}."
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
                        individual_reviewers,
                        github_login_to_slack_ids_path,
                        summary_json_path,
                        suggested_reviewers_json_path,
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
    parser.add_argument(
        "--summary-json-path",
        type=Path,
        help=(
            "Optional path to a JSON file mapping a GitHub team (e.g. "
            "'@org/slug') to a summary string. When provided, the summary is "
            "appended to that team's Slack message verbatim."
        ),
        default=None,
    )
    parser.add_argument(
        "--suggested-reviewers-json",
        type=Path,
        help=(
            "Optional path to a JSON file mapping a GitHub team (e.g. "
            "'@org/slug') to a list of GitHub logins to suggest as reviewers "
            "(e.g. from git blame). When a team has suggestions and no explicit "
            "reviewer, these are used instead of a random pick and the message "
            "reads 'maybe @x or @y since they recently touched these lines'."
        ),
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
            args.summary_json_path,
            args.suggested_reviewers_json,
        )

    if comment:
        pull.create_issue_comment(body=comment)
    if LABEL_TO_REMOVE in [label.name for label in pull.labels]:
        pull.remove_from_labels(LABEL_TO_REMOVE)


if __name__ == "__main__":
    initialize_logging()
    main()
