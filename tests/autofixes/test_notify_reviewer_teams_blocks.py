from __future__ import annotations

import json
from typing import TYPE_CHECKING
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

if TYPE_CHECKING:
    from pathlib import Path

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


def test_headline_fields_and_fallback() -> None:
    fallback, blocks = create_slack_blocks(_request())

    assert fallback == (
        "Review needed from p2p-po: [CO MCP] Preview draft intake CO changes "
        "(PR-133091)"
    )
    assert blocks[0]["text"]["text"] == (
        f"*Review needed from p2p-po:* <{PR_URL}|[CO MCP] Preview draft intake CO "
        "changes> (PR-133091)"
    )
    assert [field["text"] for field in blocks[1]["fields"]] == [
        "*Suggested reviewers*\n<@UREV1>, <@UREV2>",
        "*Author*\n<@UAUTHOR>",
    ]


def test_reviewer_label_follows_how_reviewers_were_chosen() -> None:
    def label(request: ReviewRequest) -> str:
        return create_slack_blocks(request)[1][1]["fields"][0]["text"]

    assert label(_request(reviewers=["UREV1"])) == "*Suggested reviewer*\n<@UREV1>"
    assert label(
        _request(is_blame_suggestion=False, is_random_assignment=True)
    ).startswith("*Suggested reviewers*")
    assert label(_request(is_blame_suggestion=False)) == (
        "*Assigned*\n<@UREV1>, <@UREV2>"
    )
    assert label(_request(reviewers=[])) == "*Reviewer*\nAnyone on p2p-po"


def test_author_column_omitted_without_slack_id() -> None:
    _, blocks = create_slack_blocks(_request(slack_id=None))
    assert len(blocks[1]["fields"]) == 1


def test_title_is_escaped() -> None:
    request = _request(pull_request=_pull_request(title="Fix <Foo> & bar"))
    fallback, blocks = create_slack_blocks(request)
    assert "Fix &lt;Foo&gt; &amp; bar" in blocks[0]["text"]["text"]
    assert "Fix &lt;Foo&gt; &amp; bar" in fallback


def test_owned_change_block_links_each_file() -> None:
    _, blocks = create_slack_blocks(_request())
    elements = blocks[2]["elements"][0]["elements"]

    assert elements[0] == {
        "type": "text",
        "text": "Owned-file change\n",
        "style": {"bold": True},
    }
    links = [e for e in elements if e["type"] == "link"]
    assert [(link["text"], link["url"]) for link in links] == [
        ("change_order_api_utils.py", f"{PR_URL}/files#diff-a1"),
        ("headless_change_order.py", f"{PR_URL}/files#diff-b5"),
    ]
    assert all(link["style"] == {"code": True} for link in links)
    assert elements[-1] == {"type": "text", "text": "+469/-25", "style": {"code": True}}


def test_more_files_links_to_files_tab() -> None:
    _, blocks = create_slack_blocks(
        _request(owned_changes=_owned_changes(more_files=2))
    )
    elements = blocks[2]["elements"][0]["elements"]
    assert {"type": "link", "url": f"{PR_URL}/files", "text": " +2 more"} in elements


def test_only_test_files_owned_shows_just_the_diffstat() -> None:
    owned = _owned_changes(files=[], additions=0, deletions=0)
    _, blocks = create_slack_blocks(_request(owned_changes=owned))
    elements = blocks[2]["elements"][0]["elements"]
    assert not [e for e in elements if e["type"] == "link"]
    assert elements[-2:] == [
        {"type": "text", "text": " · "},
        {"type": "text", "text": "+0/-0", "style": {"code": True}},
    ]


def test_no_owned_changes_leaves_out_the_block() -> None:
    _, blocks = create_slack_blocks(_request(owned_changes=None))
    assert len(blocks) == 2


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


def _write(path: Path, data: object) -> Path:
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_posts_blocks_with_owned_changes(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    tmp_path: Path,
) -> None:
    channels = _write(tmp_path / "channels.json", {"@Greenbax/p2p-po": "C123"})
    logins = _write(tmp_path / "logins.json", {"reviewer": "UREV1"})
    owned = _write(
        tmp_path / "owned.json", {"@Greenbax/p2p-po": dict(_owned_changes())}
    )
    mock_get_user_info.return_value = ("icon", "Author Name")

    _, ok = process_review_request(
        _team(),
        _pull_request(),
        "UAUTHOR",
        dry_run="",
        github_team_to_slack_channels_path=channels,
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=["reviewer"],
        github_login_to_slack_ids_path=logins,
        owned_changes_json_path=owned,
    )

    assert ok
    kwargs = mock_post_message.call_args.kwargs
    assert kwargs["text"].startswith("Review needed from p2p-po:")
    assert kwargs["blocks"][1]["fields"][0]["text"] == "*Assigned*\n<@UREV1>"
    assert kwargs["blocks"][2]["type"] == "rich_text"


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_without_flag_keeps_plain_text(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    tmp_path: Path,
) -> None:
    channels = _write(tmp_path / "channels.json", {"@Greenbax/p2p-po": "C123"})
    logins = _write(tmp_path / "logins.json", {"reviewer": "UREV1"})
    mock_get_user_info.return_value = ("icon", "Author Name")

    process_review_request(
        _team(),
        _pull_request(),
        "UAUTHOR",
        dry_run="",
        github_team_to_slack_channels_path=channels,
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=["reviewer"],
        github_login_to_slack_ids_path=logins,
    )

    kwargs = mock_post_message.call_args.kwargs
    assert kwargs["blocks"] is None
    assert kwargs["text"].startswith("Hi team, Could we please get reviews on")
