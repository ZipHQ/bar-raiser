from __future__ import annotations

from json import dumps
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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
    )
    message = create_slack_message(review_request)
    assert "U123" in message
    assert "PR-1" in message
    assert "Test PR" in message
    assert "test-team" in message


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
        )
    assert success
    assert "test-team" in comment
    mock_post_message.assert_called_once()


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
    )
    assert comment == "Test comment"
    mock_process_request.assert_called_once()


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

    mock_pull_request.labels = [MagicMock(name=LABEL_TO_REMOVE)]
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
