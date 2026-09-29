from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from github.PullRequest import PullRequest
from github.Team import Team as GithubTeam

from bar_raiser.autofixes.notify_reviewer_teams import (
    OwnedChanges,
    OwnedFile,
    ReviewRequest,
    _summary_elements,
    create_slack_blocks,
    process_review_request,
)

PR_URL = "https://github.com/Greenbax/evergreen/pull/133091"


def _pull_request(title: str = "[CO MCP] Preview draft intake CO changes") -> MagicMock:
    pull_request = MagicMock(spec=PullRequest)
    pull_request.html_url = PR_URL
    pull_request.number = 133091
    pull_request.title = title
    pull_request.user.login = "author"
    return pull_request


def _owned_changes(
    summary: str = "Split the builders, with `include_draft` controlling drafts",
    files: list[OwnedFile] | None = None,
    more_files: int = 0,
    additions: int = 469,
    deletions: int = 25,
) -> OwnedChanges:
    return {
        "summary": summary,
        "files": (
            files
            if files is not None
            else [
                {"name": "change_order_api_utils.py", "url": f"{PR_URL}/files#diff-a1"},
                {"name": "headless_change_order.py", "url": f"{PR_URL}/files#diff-b5"},
            ]
        ),
        "more_files": more_files,
        "additions": additions,
        "deletions": deletions,
    }


class _Unset:
    """Sentinel distinguishing "not passed" from an explicit `None`."""


_UNSET = _Unset()


def _request(
    *,
    team: str = "@Greenbax/p2p-po",
    channel: str | None = "C123",
    slack_id: str | None = "UAUTHOR",
    pull_request: PullRequest | None = None,
    reviewers: list[str] | None = None,
    is_random_assignment: bool = False,
    is_blame_suggestion: bool = True,
    summary: str | None = None,
    owned_changes: OwnedChanges | _Unset | None = _UNSET,
) -> ReviewRequest:
    return ReviewRequest(
        team=team,
        channel=channel,
        slack_id=slack_id,
        pull_request=pull_request if pull_request is not None else _pull_request(),
        reviewers=reviewers if reviewers is not None else ["UREV1", "UREV2"],
        is_random_assignment=is_random_assignment,
        is_blame_suggestion=is_blame_suggestion,
        summary=summary,
        owned_changes=(
            _owned_changes() if isinstance(owned_changes, _Unset) else owned_changes
        ),
    )


def _elements(request: ReviewRequest) -> list[dict[str, Any]]:
    """The elements of the single rich_text section the layout is built from."""
    _, blocks = create_slack_blocks(request)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "rich_text"
    return blocks[0]["elements"][0]["elements"]


def test_headline_reviewers_author_and_fallback() -> None:
    fallback, blocks = create_slack_blocks(_request())
    elements = blocks[0]["elements"][0]["elements"]

    assert fallback == (
        f"Review needed from p2p-po: [CO MCP] Preview draft intake CO changes "
        f"(PR-133091) {PR_URL} | Reviewers: <@UREV1>, <@UREV2> | "
        "Author: <@UAUTHOR> | "
        "Split the builders, with `include_draft` controlling drafts"
    )
    assert elements[:6] == [
        {"type": "text", "text": "Review needed: ", "style": {"bold": True}},
        {
            "type": "link",
            "url": PR_URL,
            "text": "[CO MCP] Preview draft intake CO changes",
        },
        {"type": "text", "text": " (PR-133091)\nfrom p2p-po\n"},
        {"type": "text", "text": "Suggested reviewers: ", "style": {"bold": True}},
        {"type": "user", "user_id": "UREV1"},
        {"type": "text", "text": ", "},
    ]
    assert elements[6:10] == [
        {"type": "user", "user_id": "UREV2"},
        {"type": "text", "text": "  ·  "},
        {"type": "text", "text": "Author: ", "style": {"bold": True}},
        {"type": "user", "user_id": "UAUTHOR"},
    ]


def test_fallback_includes_author_mention() -> None:
    """The author mention must be in the fallback `text`, not only in blocks.

    Slack's notification pipeline appears to key off the plain `text` field
    when `blocks` is set: a mention that only appears inside blocks (e.g. the
    Author section field) highlights fine in-channel but doesn't notify the
    mentioned person. Confirmed by an actual missed notification in
    production (evergreen PR #134947) before this fallback carried it.
    """
    fallback, _ = create_slack_blocks(_request(reviewers=[], owned_changes=None))
    assert "Author: <@UAUTHOR>" in fallback


def test_fallback_omits_reviewers_author_and_summary_when_absent() -> None:
    fallback, _ = create_slack_blocks(
        _request(reviewers=[], owned_changes=None, slack_id=None)
    )
    assert (
        fallback
        == f"Review needed from p2p-po: [CO MCP] Preview draft intake CO changes (PR-133091) {PR_URL}"
    )


def test_reviewer_label_follows_how_reviewers_were_chosen() -> None:
    def label(request: ReviewRequest) -> str:
        return _elements(request)[3]["text"]

    assert label(_request(reviewers=["UREV1"])) == "Suggested reviewer: "
    assert (
        label(_request(is_blame_suggestion=False, is_random_assignment=True))
        == "Suggested reviewers: "
    )
    assert label(_request(is_blame_suggestion=False)) == "Assigned: "
    no_reviewers = _elements(_request(reviewers=[]))
    assert no_reviewers[3:5] == [
        {"type": "text", "text": "Reviewer: ", "style": {"bold": True}},
        {"type": "text", "text": "Anyone on p2p-po"},
    ]


def test_author_omitted_without_slack_id() -> None:
    elements = _elements(_request(slack_id=None, owned_changes=None))
    assert not [e for e in elements if e.get("text") == "Author: "]
    assert elements[-1] == {"type": "user", "user_id": "UREV2"}


def test_title_is_escaped_only_in_fallback() -> None:
    """rich_text doesn't parse mrkdwn, so the link text stays raw; the plain-text
    fallback does, so it must be escaped."""
    request = _request(pull_request=_pull_request(title="Fix <Foo> & bar"))
    fallback, blocks = create_slack_blocks(request)
    assert blocks[0]["elements"][0]["elements"][1]["text"] == "Fix <Foo> & bar"
    assert "Fix &lt;Foo&gt; &amp; bar" in fallback


def test_owned_change_block_links_each_file() -> None:
    elements = _elements(_request())

    assert {
        "type": "text",
        "text": "Owned-file change\n",
        "style": {"bold": True},
    } in elements
    links = [e for e in elements if e["type"] == "link"][1:]  # skip the PR title
    assert [(link["text"], link["url"]) for link in links] == [
        ("change_order_api_utils.py", f"{PR_URL}/files#diff-a1"),
        ("headless_change_order.py", f"{PR_URL}/files#diff-b5"),
    ]
    assert all("style" not in link for link in links)  # plain links look clickable
    assert {"type": "text", "text": ", "} in elements
    assert elements[-1] == {"type": "text", "text": "+469/-25", "style": {"code": True}}


def test_more_files_links_to_files_tab() -> None:
    elements = _elements(_request(owned_changes=_owned_changes(more_files=2)))
    assert {"type": "link", "url": f"{PR_URL}/files", "text": " +2 more"} in elements


def test_only_test_files_owned_shows_just_the_diffstat() -> None:
    owned = _owned_changes(files=[], additions=0, deletions=0)
    elements = _elements(_request(owned_changes=owned))
    assert [e for e in elements if e["type"] == "link"] == elements[1:2]  # title only
    assert elements[-2:] == [
        {"type": "text", "text": " · "},
        {"type": "text", "text": "+0/-0", "style": {"code": True}},
    ]


def test_no_owned_changes_leaves_out_the_block() -> None:
    elements = _elements(_request(owned_changes=None))
    assert not [e for e in elements if e.get("text") == "Owned-file change\n"]


def test_summary_backticks_become_code_elements() -> None:
    assert _summary_elements("Set `a` and `b`.") == [
        {"type": "text", "text": "Set "},
        {"type": "text", "text": "a", "style": {"code": True}},
        {"type": "text", "text": " and "},
        {"type": "text", "text": "b", "style": {"code": True}},
        {"type": "text", "text": "."},
    ]
    assert _summary_elements("Odd ` tick") == [{"type": "text", "text": "Odd ` tick"}]


def _team(slug: str = "p2p-po") -> MagicMock:
    team = MagicMock(spec=GithubTeam)
    team.organization.login = "Greenbax"
    team.slug = slug
    member = MagicMock()
    member.login = "reviewer"
    team.get_members = MagicMock(return_value=[member])
    return team


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_posts_blocks_with_owned_changes(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
) -> None:
    mock_get_user_info.return_value = ("icon", "Author Name")

    _, ok = process_review_request(
        _team(),
        _pull_request(),
        "UAUTHOR",
        dry_run="",
        github_team_to_slack_channels={"@Greenbax/p2p-po": "C123"},
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=["reviewer"],
        github_login_to_slack_ids={"reviewer": "UREV1"},
        owned_changes={"@Greenbax/p2p-po": _owned_changes()},
    )

    assert ok
    kwargs = mock_post_message.call_args.kwargs
    assert kwargs["text"].startswith("Review needed from p2p-po:")
    elements = kwargs["blocks"][0]["elements"][0]["elements"]
    assert {"type": "text", "text": "Assigned: ", "style": {"bold": True}} in elements
    assert {"type": "user", "user_id": "UREV1"} in elements
    assert {
        "type": "text",
        "text": "Owned-file change\n",
        "style": {"bold": True},
    } in elements


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_without_flag_keeps_plain_text(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
) -> None:
    mock_get_user_info.return_value = ("icon", "Author Name")

    process_review_request(
        _team(),
        _pull_request(),
        "UAUTHOR",
        dry_run="",
        github_team_to_slack_channels={"@Greenbax/p2p-po": "C123"},
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=["reviewer"],
        github_login_to_slack_ids={"reviewer": "UREV1"},
    )

    kwargs = mock_post_message.call_args.kwargs
    assert kwargs["blocks"] is None
    assert kwargs["text"].startswith("Hi team, Could we please get reviews on")
