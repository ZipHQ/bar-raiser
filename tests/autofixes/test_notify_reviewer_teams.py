from __future__ import annotations

from json import dumps
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from github.Label import Label
from github.PullRequest import PullRequest
from github.Team import Team as GithubTeam

from bar_raiser.autofixes.notify_reviewer_teams import (
    LABEL_TO_REMOVE,
    ReviewRequest,
    create_slack_message,
    main,
    process_pull_request,
    process_review_request,
)


@pytest.fixture
def mock_pull_request() -> PullRequest:
    mock = MagicMock(spec=PullRequest)
    mock.user.login = "testuser"
    mock.html_url = "https://github.com/test/pr/1"
    mock.number = 1
    mock.title = "Test PR"
    return mock


@pytest.fixture
def mock_team() -> GithubTeam:
    mock = MagicMock(spec=GithubTeam)
    mock.organization.login = "Greenbax"
    mock.slug = "test-team"
    return mock


def test_create_slack_message(mock_pull_request: PullRequest) -> None:
    review_request = ReviewRequest(
        team="@Greenbax/test-team",
        channel="test-channel",
        slack_id="U123",
        pull_request=mock_pull_request,
        reviewers=[],
    )
    message = create_slack_message(review_request)
    assert "U123" in message
    assert "PR-1" in message
    assert "Test PR" in message
    assert "test-team" in message
    assert "Assigned reviewers" not in message


def test_create_slack_message_with_reviewers(mock_pull_request: PullRequest) -> None:
    review_request = ReviewRequest(
        team="@Greenbax/test-team",
        channel="test-channel",
        slack_id="U123",
        pull_request=mock_pull_request,
        reviewers=["U_ALICE", "U_BOB"],
    )
    message = create_slack_message(review_request)
    assert "U123" in message
    assert "PR-1" in message
    assert "Test PR" in message
    assert "test-team" in message
    assert "Assigned reviewers: <@U_ALICE>, <@U_BOB>" in message


def test_create_slack_message_with_single_reviewer(
    mock_pull_request: PullRequest,
) -> None:
    review_request = ReviewRequest(
        team="@Greenbax/test-team",
        channel="test-channel",
        slack_id="U123",
        pull_request=mock_pull_request,
        reviewers=["U_CHARLIE"],
    )
    message = create_slack_message(review_request)
    assert "Assigned reviewers: <@U_CHARLIE>" in message


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_success(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    mock_get_user_info.return_value = ("icon_url", "username")
    mock_team.get_members = MagicMock(return_value=[])  # type: ignore[method-assign]

    with patch(
        "pathlib.Path.read_text",
        return_value=dumps({"@Greenbax/test-team": "test-channel"}),
    ):
        comment, success = process_review_request(
            mock_team,
            mock_pull_request,
            "U123",
            dry_run="test-channel",
            github_team_to_slack_channels_path=Path("test-path"),
            github_team_to_slack_channels_help_msg="",
            individual_reviewers=[],
            github_login_to_slack_ids_path=Path("test-path-login"),
        )
    assert success
    assert "test-channel" in comment
    mock_post_message.assert_called_once()


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_none_channel(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    mock_get_user_info.return_value = ("icon_url", "username")
    mock_team.get_members = MagicMock(return_value=[])  # type: ignore[method-assign]

    with patch(
        "pathlib.Path.read_text",
        return_value=dumps({}),
    ):
        comment, success = process_review_request(
            mock_team,
            mock_pull_request,
            "U123",
            dry_run="test-channel",
            github_team_to_slack_channels_path=Path("test-path"),
            github_team_to_slack_channels_help_msg="",
            individual_reviewers=[],
            github_login_to_slack_ids_path=Path("test-path-login"),
        )
    assert not success
    assert "Slack channel not found" in comment
    mock_post_message.assert_not_called()


@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_dry_run(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    mock_get_user_info.return_value = ("icon_url", "username")
    mock_team.get_members = MagicMock(return_value=[])  # type: ignore[method-assign]

    with patch(
        "pathlib.Path.read_text",
        return_value=dumps({"@Greenbax/test-team": "test-channel"}),
    ):
        comment, success = process_review_request(
            mock_team,
            mock_pull_request,
            "U123",
            dry_run="test-channel",
            github_team_to_slack_channels_path=Path("test-path"),
            github_team_to_slack_channels_help_msg="",
            individual_reviewers=[],
            github_login_to_slack_ids_path=Path("test-path-login"),
        )
    assert success
    assert "test-team" in comment
    mock_post_message.assert_called_once()


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_filters_reviewers_by_team_membership(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_get_slack_id: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    """Test that only reviewers who are members of the team are included."""
    mock_get_user_info.return_value = ("icon_url", "username")

    # Create mock team members
    member1 = MagicMock()
    member1.login = "alice"
    member2 = MagicMock()
    member2.login = "bob"

    mock_team.get_members = MagicMock(return_value=[member1, member2])  # type: ignore[method-assign]

    # alice and bob are team members, charlie is not
    individual_reviewers = ["alice", "bob", "charlie"]

    # Mock Slack ID lookups - return Slack IDs for team members
    def slack_id_lookup(github_login: str, _path: Path) -> str | None:
        mapping = {
            "@Greenbax/test-team": "test-channel",
            "alice": "U_ALICE",
            "bob": "U_BOB",
            "charlie": "U_CHARLIE",
        }
        return mapping.get(github_login)

    mock_get_slack_id.side_effect = slack_id_lookup

    comment, success = process_review_request(
        mock_team,
        mock_pull_request,
        "U123",
        dry_run="test-channel",
        github_team_to_slack_channels_path=Path("test-path"),
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=individual_reviewers,
        github_login_to_slack_ids_path=Path("test-path-login"),
    )

    assert success
    assert "test-team" in comment
    mock_post_message.assert_called_once()

    # Check that the message includes only team members (alice and bob) as Slack mentions
    call_args = mock_post_message.call_args
    message_text = call_args.kwargs["text"]
    assert "<@U_ALICE>" in message_text
    assert "<@U_BOB>" in message_text
    assert "U_CHARLIE" not in message_text
    assert "Assigned reviewers" in message_text


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_no_matching_team_members(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_get_slack_id: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    """Test that when no reviewers match team membership, no reviewers are shown."""
    mock_get_user_info.return_value = ("icon_url", "username")

    # Create mock team members
    member1 = MagicMock()
    member1.login = "alice"
    member2 = MagicMock()
    member2.login = "bob"

    mock_team.get_members = MagicMock(return_value=[member1, member2])  # type: ignore[method-assign]

    # charlie and david are NOT team members
    individual_reviewers = ["charlie", "david"]

    # Mock Slack ID lookups
    def slack_id_lookup(github_login: str, _path: Path) -> str | None:
        mapping = {
            "@Greenbax/test-team": "test-channel",
            "charlie": "U_CHARLIE",
            "david": "U_DAVID",
        }
        return mapping.get(github_login)

    mock_get_slack_id.side_effect = slack_id_lookup

    _comment, success = process_review_request(
        mock_team,
        mock_pull_request,
        "U123",
        dry_run="test-channel",
        github_team_to_slack_channels_path=Path("test-path"),
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=individual_reviewers,
        github_login_to_slack_ids_path=Path("test-path-login"),
    )

    assert success
    mock_post_message.assert_called_once()

    # Check that the message does NOT include reviewer information
    call_args = mock_post_message.call_args
    message_text = call_args.kwargs["text"]
    assert "Assigned reviewers" not in message_text
    assert "U_CHARLIE" not in message_text
    assert "U_DAVID" not in message_text


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
@patch(
    "bar_raiser.autofixes.notify_reviewer_teams.get_slack_user_icon_url_and_username"
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.post_a_slack_message")
def test_process_review_request_with_team_member_reviewers(
    mock_post_message: MagicMock,
    mock_get_user_info: MagicMock,
    mock_get_slack_id: MagicMock,
    mock_team: GithubTeam,
    mock_pull_request: PullRequest,
) -> None:
    """Test that all matching team member reviewers are included."""
    mock_get_user_info.return_value = ("icon_url", "username")

    # Create mock team members
    member1 = MagicMock()
    member1.login = "alice"
    member2 = MagicMock()
    member2.login = "bob"
    member3 = MagicMock()
    member3.login = "charlie"

    mock_team.get_members = MagicMock(return_value=[member1, member2, member3])  # type: ignore[method-assign]

    # All three are team members
    individual_reviewers = ["alice", "bob", "charlie"]

    # Mock Slack ID lookups
    def slack_id_lookup(github_login: str, _path: Path) -> str | None:
        mapping = {
            "@Greenbax/test-team": "test-channel",
            "alice": "U_ALICE",
            "bob": "U_BOB",
            "charlie": "U_CHARLIE",
        }
        return mapping.get(github_login)

    mock_get_slack_id.side_effect = slack_id_lookup

    _comment, success = process_review_request(
        mock_team,
        mock_pull_request,
        "U123",
        dry_run="test-channel",
        github_team_to_slack_channels_path=Path("test-path"),
        github_team_to_slack_channels_help_msg="",
        individual_reviewers=individual_reviewers,
        github_login_to_slack_ids_path=Path("test-path-login"),
    )

    assert success
    mock_post_message.assert_called_once()

    # Check that all three team members are in the message as Slack mentions
    call_args = mock_post_message.call_args
    message_text = call_args.kwargs["text"]
    assert "Assigned reviewers: <@U_ALICE>, <@U_BOB>, <@U_CHARLIE>" in message_text


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
def test_process_pull_request_no_slack_id(
    mock_get_slack_id: MagicMock,
    mock_pull_request: PullRequest,
) -> None:
    mock_get_slack_id.return_value = None

    comment = process_pull_request(
        mock_pull_request,
        dry_run="test-channel",
        github_login_to_slack_ids_path=Path("test-path-1"),
        github_login_to_slack_ids_help_msg="Please update the mapping in `test-path-1`",
        github_team_to_slack_channels_path=Path("test-path-2"),
        github_team_to_slack_channels_help_msg="Please update the mapping in `test-path-2`",
        only_notify_team_slug=None,
    )
    assert (
        comment
        == "No author slack_id found for author testuser.\nPlease update the mapping in `test-path-1`\n"
    )


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
@patch("bar_raiser.autofixes.notify_reviewer_teams.process_review_request")
def test_process_pull_request_success(
    mock_process_request: MagicMock,
    mock_get_slack_id: MagicMock,
    mock_pull_request: PullRequest,
    mock_team: GithubTeam,
) -> None:
    mock_get_slack_id.return_value = "U123"
    mock_process_request.return_value = ("Test comment", True)

    mock_pull_request.get_review_requests = MagicMock(return_value=[[mock_team]])

    comment = process_pull_request(
        mock_pull_request,
        dry_run="test-channel",
        github_login_to_slack_ids_path=Path("test-path-1"),
        github_login_to_slack_ids_help_msg="",
        github_team_to_slack_channels_path=Path("test-path-2"),
        github_team_to_slack_channels_help_msg="",
        only_notify_team_slug=None,
    )
    assert comment == "Test comment"
    mock_process_request.assert_called_once()


@pytest.mark.parametrize(
    (
        "only_notify_team_slug_arg",
        "requested_teams_slugs",
        "process_review_request_return_value",
        "expected_comment",
        "expected_calls_to_process_review_request",
    ),
    [
        (
            "target-team",  # Test 1: Target team is a reviewer
            ["target-team", "other-team"],
            ("Comment for target-team", True),
            "Comment for target-team",
            1,
        ),
        (
            "non-existent-team",  # Test 2: Target team is NOT a reviewer
            ["team-a", "team-b"],
            ("Should not be called", True),
            "",
            0,
        ),
        (
            None,  # Test 3: only_notify_team_slug is None (all teams)
            ["team-1", "team-2"],
            ("Comment for team", True),
            "Comment for teamComment for team",  # Called for both teams
            2,
        ),
        (
            "target-team-no-channel",  # Test 4: Target team is reviewer, but process_review_request returns empty (e.g. no channel)
            ["target-team-no-channel", "another-team"],
            (
                "",
                False,
            ),  # Simulates an issue like a missing Slack channel mapping for the target team
            "",
            1,
        ),
        (
            "target-team",  # Test 5: Target team is a reviewer, no other reviewers
            ["target-team"],
            ("Comment for target-team", True),
            "Comment for target-team",
            1,
        ),
        (
            "not-a-reviewer",  # Test 6: Target team specified, but PR has no reviewers
            [],
            ("Should not be called", False),
            "",
            0,
        ),
        (
            None,  # Test 7: No target team, no reviewers
            [],
            ("Should not be called", False),
            "No team review requests found.",  # Updated expected message based on recent changes
            0,
        ),
    ],
)
@patch("bar_raiser.autofixes.notify_reviewer_teams.get_slack_channel_from_mapping_path")
@patch("bar_raiser.autofixes.notify_reviewer_teams.process_review_request")
def test_process_pull_request_only_notify_team(  # noqa: PLR0917
    mock_process_review_request: MagicMock,
    mock_get_author_slack_id: MagicMock,
    mock_pull_request: PullRequest,
    only_notify_team_slug_arg: str | None,
    requested_teams_slugs: list[str],
    process_review_request_return_value: tuple[str, bool],
    expected_comment: str,
    expected_calls_to_process_review_request: int,
) -> None:
    mock_get_author_slack_id.return_value = "U_AUTHOR123"  # For author lookup
    mock_process_review_request.return_value = process_review_request_return_value

    # Setup mock teams based on requested_teams_slugs
    mock_teams: list[MagicMock] = []
    for slug in requested_teams_slugs:
        team = MagicMock(spec=GithubTeam)
        team.organization.login = "Greenbax"
        team.slug = slug
        mock_teams.append(team)

    mock_pull_request.get_review_requests = MagicMock(return_value=[mock_teams])

    comment = process_pull_request(
        pull_request=mock_pull_request,
        dry_run="",  # Dry run channel not relevant for this focused test
        github_login_to_slack_ids_path=Path("dummy_login_to_slack.json"),
        github_login_to_slack_ids_help_msg="login help",
        github_team_to_slack_channels_path=Path("dummy_team_to_channels.json"),
        github_team_to_slack_channels_help_msg="team help",
        only_notify_team_slug=only_notify_team_slug_arg,
    )

    assert comment == expected_comment
    assert (
        mock_process_review_request.call_count
        == expected_calls_to_process_review_request
    )

    if expected_calls_to_process_review_request == 1 and only_notify_team_slug_arg:
        # Check that process_review_request was called with the correct target team
        called_team_arg = mock_process_review_request.call_args[0][0]
        assert called_team_arg.slug == only_notify_team_slug_arg


@patch("bar_raiser.autofixes.notify_reviewer_teams.get_pull_request")
def test_main(mock_get_pull_request: MagicMock) -> None:
    mock_get_pull_request.return_value = None
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 2

    mock_pull_request = MagicMock(spec=PullRequest)
    mock_pull_request.labels = []
    mock_pull_request.draft = False
    mock_get_pull_request.return_value = mock_pull_request
    mock_label = MagicMock(spec=Label)
    mock_label.name = LABEL_TO_REMOVE
    mock_pull_request.labels = [mock_label]
    with (
        patch(
            "bar_raiser.autofixes.notify_reviewer_teams.process_pull_request",
            return_value="Test comment",
        ),
        patch(
            "sys.argv",
            [
                "notify_reviewer_teams.py",
                "github_login_to_slack_ids.json",
                "github_login_to_slack_ids_help_msg",
                "github_team_to_slack_channels.json",
                "github_team_to_slack_channels_help_msg",
            ],
        ),
    ):
        main()
    mock_pull_request.remove_from_labels.assert_called_once_with(LABEL_TO_REMOVE)
