from __future__ import annotations

import random
import sys
from argparse import ArgumentParser
from dataclasses import dataclass
from json import loads
from logging import getLogger
from os import environ
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict

from github.Team import Team

from bar_raiser.utils.slack import (
    get_slack_user_icon_url_and_username,
)

if TYPE_CHECKING:
    from github.PullRequest import PullRequest


from bar_raiser.utils.github import get_pull_request, initialize_logging
from bar_raiser.utils.slack import post_a_slack_message

logger = getLogger(__name__)


LABEL_TO_REMOVE = "autofix-notify-reviewer-teams"


def _load_json_mapping(path: Path) -> Any:
    """Read and parse a mapping file once; callers reuse the result per PR."""
    return loads(path.read_text())  # noqa: PLW1514


class OwnedFile(TypedDict):
    name: str
    url: str


class OwnedChanges(TypedDict):
    """One team's entry in the --owned-changes-json file.

    Produced by evergreen's `generate_team_summaries.py`; `summary` may contain
    backtick-quoted code spans.
    """

    summary: str
    files: list[OwnedFile]
    more_files: int
    additions: int
    deletions: int


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
    owned_changes: OwnedChanges | None = None


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


def _escape_mrkdwn(text: str) -> str:
    """Escape the three characters Slack treats as control characters in mrkdwn."""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _reviewer_field(review_request: ReviewRequest, team_slug: str) -> str:
    """Render the reviewer column, labeled by how the reviewers were chosen."""
    if not review_request.reviewers:
        return f"*Reviewer*\nAnyone on {team_slug}"
    mentions = ", ".join(f"<@{reviewer}>" for reviewer in review_request.reviewers)
    if review_request.is_blame_suggestion or review_request.is_random_assignment:
        label = (
            "Suggested reviewer"
            if len(review_request.reviewers) == 1
            else "Suggested reviewers"
        )
    else:
        label = "Assigned"
    return f"*{label}*\n{mentions}"


def _summary_elements(summary: str) -> list[dict[str, Any]]:
    """Split a summary on backticks into rich_text elements.

    rich_text doesn't parse mrkdwn, so backtick spans become code-styled text
    elements instead of showing literal backticks. An unmatched trailing
    backtick is kept as plain text.
    """
    parts = summary.split("`")
    if len(parts) % 2 == 0:
        parts = [*parts[:-2], f"{parts[-2]}`{parts[-1]}"]
    elements: list[dict[str, Any]] = []
    for index, part in enumerate(parts):
        if not part:
            continue
        element: dict[str, Any] = {"type": "text", "text": part}
        if index % 2 == 1:
            element["style"] = {"code": True}
        elements.append(element)
    return elements


def _owned_changes_block(
    owned_changes: OwnedChanges, pull_request_url: str
) -> dict[str, Any]:
    """Render the "Owned-file change" section: summary, linked files, diffstat."""
    elements: list[dict[str, Any]] = [
        {"type": "text", "text": "Owned-file change\n", "style": {"bold": True}},
        *_summary_elements(owned_changes["summary"]),
        {"type": "text", "text": " · "},
    ]
    for index, owned_file in enumerate(owned_changes["files"]):
        if index:
            elements.append({"type": "text", "text": " "})
        elements.append({
            "type": "link",
            "url": owned_file["url"],
            "text": owned_file["name"],
            "style": {"code": True},
        })
    if owned_changes["more_files"]:
        elements.append({
            "type": "link",
            "url": f"{pull_request_url}/files",
            "text": f" +{owned_changes['more_files']} more",
        })
    if owned_changes["files"] or owned_changes["more_files"]:
        elements.append({"type": "text", "text": " "})
    elements.append({
        "type": "text",
        "text": f"+{owned_changes['additions']}/-{owned_changes['deletions']}",
        "style": {"code": True},
    })
    return {
        "type": "rich_text",
        "elements": [{"type": "rich_text_section", "elements": elements}],
    }


def _fallback_text(review_request: ReviewRequest, team_slug: str, title: str) -> str:
    """Build the notification/sidebar/screen-reader fallback for `text`.

    Unlike the headline, this isn't rendered as blocks, so it carries the
    reviewers, a plain PR URL, and the change summary too — the surfaces this
    is shown on don't otherwise expose that content.
    """
    pull_request = review_request.pull_request
    parts = [
        f"Review needed from {team_slug}: {_escape_mrkdwn(title)} "
        f"(PR-{pull_request.number}) {pull_request.html_url}"
    ]
    if review_request.reviewers:
        mentions = ", ".join(f"<@{reviewer}>" for reviewer in review_request.reviewers)
        parts.append(f"Reviewers: {mentions}")
    if review_request.owned_changes:
        parts.append(review_request.owned_changes["summary"])
    return " | ".join(parts)


def create_slack_blocks(
    review_request: ReviewRequest,
) -> tuple[str, list[dict[str, Any]]]:
    """Build the labeled review-ping layout as Block Kit.

    Returns `(fallback_text, blocks)`. The fallback is what Slack shows in
    notifications, the sidebar, and to screen readers, so it repeats the key
    content (reviewers, PR link, summary) outside of the blocks.

    Layout:
    - headline: "Review needed from <team>:" + linked PR title
    - two columns: reviewer(s) and author (author omitted without a Slack ID)
    - "Owned-file change", only when the team has an owned-changes entry
    """
    pull_request = review_request.pull_request
    team_slug = review_request.team.split("/")[-1]
    title = pull_request.title
    headline = (
        f"*Review needed from {team_slug}:* "
        f"<{pull_request.html_url}|{_escape_mrkdwn(title)}> (PR-{pull_request.number})"
    )
    fields = [{"type": "mrkdwn", "text": _reviewer_field(review_request, team_slug)}]
    if review_request.slack_id:
        fields.append({
            "type": "mrkdwn",
            "text": f"*Author*\n<@{review_request.slack_id}>",
        })
    blocks: list[dict[str, Any]] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": headline}},
        {"type": "section", "fields": fields},
    ]
    if review_request.owned_changes:
        blocks.append(
            _owned_changes_block(review_request.owned_changes, pull_request.html_url)
        )
    return _fallback_text(review_request, team_slug, title), blocks


def get_owned_changes_for_team(
    team: str, owned_changes: dict[str, OwnedChanges] | None
) -> OwnedChanges | None:
    """Return the team's owned-changes entry, or None when the team has none."""
    if owned_changes is None:
        return None
    return owned_changes.get(team)


def get_suggested_reviewers_for_team(
    team: str, suggested_reviewers: dict[str, list[str]] | None
) -> list[str]:
    """Return pre-computed suggested reviewer logins for a team, if any.

    `suggested_reviewers` maps a GitHub team (``@org/slug``) to a list of
    GitHub logins (e.g. from git blame). Returns an empty list when it's
    absent or has no entry for this team, so the caller falls back to the
    random pick.
    """
    if suggested_reviewers is None:
        return []
    return suggested_reviewers.get(team, [])


def process_review_request(  # noqa: PLR0912, PLR0914, PLR0917
    request: Team,
    pull_request: PullRequest,
    slack_id: str | None,
    dry_run: str,
    github_team_to_slack_channels: dict[str, str],
    github_team_to_slack_channels_help_msg: str,
    individual_reviewers: list[str],
    github_login_to_slack_ids: dict[str, str],
    summaries: dict[str, str] | None = None,
    suggested_reviewers: dict[str, list[str]] | None = None,
    owned_changes: dict[str, OwnedChanges] | None = None,
) -> tuple[str, bool]:
    """Process a single review request and return the comment and success status.

    The mapping arguments (`github_team_to_slack_channels`,
    `github_login_to_slack_ids`, `summaries`, `suggested_reviewers`,
    `owned_changes`) are loaded once per PR by `process_pull_request` and
    reused across every requested team, instead of each being re-read and
    re-parsed from disk here.
    """
    team = f"@{request.organization.login}/{request.slug}"
    channel = github_team_to_slack_channels.get(team)

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
        team_members = {member.login for member in request.get_members()}

        # git-blame suggestions for this team, filtered to current members and
        # excluding the PR author.
        suggested = [
            login
            for login in get_suggested_reviewers_for_team(team, suggested_reviewers)
            if login in team_members and login != pull_request.user.login
        ]

        # Track how reviewers were chosen, which changes the message wording.
        is_random = False
        is_blame_suggestion = False

        # Reviewer precedence: git blame > GitHub's assigned reviewers > random.
        # Blame overrides the assigned reviewers because GitHub auto-assignment
        # is round-robin/random and weaker than "who last touched these lines";
        # the assigned reviewer already got GitHub's notification and any team
        # member's approval satisfies the CODEOWNERS requirement anyway.
        if suggested:
            is_blame_suggestion = True
            chosen = suggested
            logger.info(f"Suggested reviewers from team {team} via git blame")
        else:
            assigned = [r for r in individual_reviewers if r in team_members]
            if assigned:
                chosen = assigned
            elif team_members:
                is_random = True
                team_members_list = [
                    m for m in team_members if m != pull_request.user.login
                ]
                num_to_pick = min(2, len(team_members_list))
                chosen = random.sample(team_members_list, num_to_pick)
                logger.info(f"Randomly suggested reviewers from team {team}")
            else:
                chosen = []

        reviewer_slack_ids: list[str] = []
        for github_login in chosen:
            reviewer_slack_id = github_login_to_slack_ids.get(github_login)
            if reviewer_slack_id:
                reviewer_slack_ids.append(reviewer_slack_id)

        # The owned-changes mapping opts this run into the labeled Block Kit
        # layout; without it the plain-text message is unchanged.
        # --summary-json-path is ignored in blocks mode: create_slack_blocks
        # doesn't render `summary`, and the two are never combined in
        # evergreen's workflow (which sources them from the same
        # generate_team_summaries.py run), so skip reading it entirely.
        summary = (
            summaries.get(team)
            if summaries is not None and owned_changes is None
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
        blocks: list[dict[str, Any]] | None = None
        if owned_changes is not None:
            review_request.owned_changes = get_owned_changes_for_team(
                team, owned_changes
            )
            message, blocks = create_slack_blocks(review_request)
        else:
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
            blocks=blocks,
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
    owned_changes_json_path: Path | None = None,
) -> str:
    """Process all review requests for a pull request.

    Each mapping file is read and parsed once here, then reused across every
    requested team in `process_review_request`, instead of being re-read per
    team (or, for `github_login_to_slack_ids`, per reviewer).
    """
    github_login_to_slack_ids: dict[str, str] = _load_json_mapping(
        github_login_to_slack_ids_path
    )
    github_team_to_slack_channels: dict[str, str] = _load_json_mapping(
        github_team_to_slack_channels_path
    )
    owned_changes: dict[str, OwnedChanges] | None = (
        _load_json_mapping(owned_changes_json_path)
        if owned_changes_json_path is not None
        else None
    )
    # --summary-json-path is ignored once owned-changes mode is active (see
    # process_review_request), so skip reading it: a stale or malformed
    # legacy summaries file must not block the notification.
    summaries: dict[str, str] | None = (
        _load_json_mapping(summary_json_path)
        if summary_json_path is not None and owned_changes is None
        else None
    )
    suggested_reviewers: dict[str, list[str]] | None = (
        _load_json_mapping(suggested_reviewers_json_path)
        if suggested_reviewers_json_path is not None
        else None
    )

    author_login = pull_request.user.login

    if author_login.endswith("[bot]"):
        # Bot-authored PR: use the label sender (GITHUB_ACTOR) instead
        label_sender = environ.get("GITHUB_ACTOR")
        slack_id = github_login_to_slack_ids.get(label_sender) if label_sender else None
    else:
        slack_id = github_login_to_slack_ids.get(author_login)
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
                            github_team_to_slack_channels,
                            github_team_to_slack_channels_help_msg,
                            individual_reviewers,
                            github_login_to_slack_ids,
                            summaries,
                            suggested_reviewers,
                            owned_changes,
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
                        github_team_to_slack_channels,
                        github_team_to_slack_channels_help_msg,
                        individual_reviewers,
                        github_login_to_slack_ids,
                        summaries,
                        suggested_reviewers,
                        owned_changes,
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
    parser.add_argument(
        "--owned-changes-json",
        type=Path,
        help=(
            "Optional path to a JSON file mapping a GitHub team (e.g. "
            "'@org/slug') to its owned changes: summary, owned files with diff "
            "links, and diffstat. When provided, messages use the labeled "
            "Block Kit layout instead of the plain-text message, and "
            "--summary-json-path is ignored."
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
            args.owned_changes_json,
        )

    if comment:
        pull.create_issue_comment(body=comment)
    if LABEL_TO_REMOVE in [label.name for label in pull.labels]:
        pull.remove_from_labels(LABEL_TO_REMOVE)


if __name__ == "__main__":
    initialize_logging()
    main()
