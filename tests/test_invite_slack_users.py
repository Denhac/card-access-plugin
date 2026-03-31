from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from denhac_card_access.invite_slack_users import InviteSlackUsers


def make_invite(email="user@example.com", channels=None, invite_type="full_member"):
    return {
        "email": email,
        "channels": channels if channels is not None else ["C123"],
        "type": invite_type,
    }


def make_invites_response(invites):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = invites
    return response


def make_post_response():
    response = Mock()
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def invite_slack_users(mock_config):
    return InviteSlackUsers(mock_config)


class TestConstructor:
    def test_raises_if_base_url_is_none(self, mock_config):
        mock_config.webhooks.base_url = None
        with pytest.raises(Exception):
            InviteSlackUsers(mock_config)


class TestGetInvites:
    def test_fetches_invites_from_api(self, invite_slack_users, mock_webhook_session):
        mock_webhook_session.get.return_value = make_invites_response([])
        invite_slack_users.loop()
        mock_webhook_session.get.assert_any_call("https://api.example.com/slack/invites")


class TestExistingUser:
    def test_posts_slack_id_when_user_found(self, invite_slack_users, mock_config, mock_webhook_session):
        mock_webhook_session.get.return_value = make_invites_response([make_invite(email="user@example.com")])
        mock_webhook_session.post.return_value = make_post_response()
        mock_config.slack.user_id_by_email.return_value = "U123"

        invite_slack_users.loop()

        mock_webhook_session.post.assert_called_once_with(
            "https://api.example.com/slack/invites",
            json={"email": "user@example.com", "slack_id": "U123"},
        )


class TestNewUserInvite:
    def test_invite_user_called_when_not_yet_in_slack(self, invite_slack_users, mock_config, mock_webhook_session):
        invite = make_invite(email="new@example.com", channels=["C1", "C2"], invite_type="restricted")
        mock_webhook_session.get.return_value = make_invites_response([invite])
        mock_config.slack.user_id_by_email.return_value = None
        mock_config.slack.invite_user.return_value = True

        # Patching time.sleep to avoid actually waiting the 1-second pause
        # the implementation uses to give Slack time to register the new user
        with patch("denhac_card_access.invite_slack_users.time.sleep"):
            invite_slack_users.loop()

        mock_config.slack.invite_user.assert_called_once_with("new@example.com", "restricted", ["C1", "C2"])

    def test_after_invite_sleep_and_check_for_existing(self, invite_slack_users, mock_config, mock_webhook_session):
        mock_webhook_session.get.return_value = make_invites_response([make_invite()])
        mock_webhook_session.post.return_value = make_post_response()
        mock_config.slack.invite_user.return_value = True
        mock_config.slack.user_id_by_email.side_effect = [None, "U999"]

        # Patching time.sleep to avoid actually waiting the 1-second pause
        # the implementation uses to give Slack time to register the new user
        with patch("denhac_card_access.invite_slack_users.time.sleep") as mock_sleep:
            invite_slack_users.loop()

        mock_sleep.assert_called_once_with(1)
        assert mock_config.slack.user_id_by_email.call_count == 2


class TestFailureHandling:
    def test_exception_sets_cooldown_and_increments_count(self, invite_slack_users, mock_config, mock_webhook_session):
        email = "fail@example.com"
        mock_webhook_session.get.return_value = make_invites_response([make_invite(email=email)])
        mock_config.slack.user_id_by_email.return_value = None
        mock_config.slack.invite_user.side_effect = Exception("Slack error")

        now = datetime(2024, 1, 1, 12, 0, 0)
        with patch("denhac_card_access.invite_slack_users.datetime") as mock_dt:
            mock_dt.now.return_value = now
            invite_slack_users.loop()

        assert invite_slack_users._failed_invite_count[email] == 1
        assert invite_slack_users._invite_time[email] == now + timedelta(minutes=5)

    def test_cooldown_skips_email_until_time_passes(self, invite_slack_users, mock_config, mock_webhook_session):
        email = "user@example.com"
        # Cooldown was set recently, expires 5 minutes later; we're checking before it expires
        invite_slack_users._invite_time[email] = datetime(2024, 1, 1, 12, 0, 0)

        mock_webhook_session.get.return_value = make_invites_response([make_invite(email=email)])
        mock_config.slack.user_id_by_email.return_value = None

        # "now" is only 2 minutes after the cooldown was set, so next_time (12:05) > now (12:02)
        with patch("denhac_card_access.invite_slack_users.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 12, 2, 0)
            invite_slack_users.loop()

        mock_config.slack.invite_user.assert_not_called()

    def test_invite_retried_after_cooldown_expires(self, invite_slack_users, mock_config, mock_webhook_session):
        email = "user@example.com"
        # Cooldown was set long ago
        invite_slack_users._invite_time[email] = datetime(2024, 1, 1, 11, 0, 0)

        mock_webhook_session.get.return_value = make_invites_response([make_invite(email=email)])
        mock_config.slack.user_id_by_email.return_value = None
        mock_config.slack.invite_user.return_value = True

        with patch("denhac_card_access.invite_slack_users.datetime") as mock_dt:
            mock_dt.now.return_value = datetime(2024, 1, 1, 12, 0, 0)
            # Patching time.sleep to avoid actually waiting the 1-second pause
            # the implementation uses to give Slack time to register the new user
            with patch("denhac_card_access.invite_slack_users.time.sleep"):
                invite_slack_users.loop()

        mock_config.slack.invite_user.assert_called_once()

    def test_raises_on_tenth_failure(self, invite_slack_users, mock_config, mock_webhook_session):
        email = "fail@example.com"
        invite_slack_users._failed_invite_count[email] = 9

        mock_webhook_session.get.return_value = make_invites_response([make_invite(email=email)])
        mock_config.slack.user_id_by_email.return_value = None
        error = Exception("Final failure")
        mock_config.slack.invite_user.side_effect = error

        with patch("denhac_card_access.invite_slack_users.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.now()
            with pytest.raises(Exception) as exc_info:
                invite_slack_users.loop()

        assert exc_info.value is error

    def test_does_not_raise_before_tenth_failure(self, invite_slack_users, mock_config, mock_webhook_session):
        email = "fail@example.com"
        invite_slack_users._failed_invite_count[email] = 8

        mock_webhook_session.get.return_value = make_invites_response([make_invite(email=email)])
        mock_config.slack.user_id_by_email.return_value = None
        mock_config.slack.invite_user.side_effect = Exception("Failure")

        with patch("denhac_card_access.invite_slack_users.datetime") as mock_dt:
            mock_dt.now.return_value = datetime.now()
            invite_slack_users.loop()  # Should not raise
