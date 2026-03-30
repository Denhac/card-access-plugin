from unittest.mock import patch, Mock

import pytest
import tomlkit

from denhac_card_access.config import _WebhookConfig, _SlackConfig


@pytest.fixture
def webhook_table():
    return tomlkit.table()


@pytest.fixture
def slack_table():
    return tomlkit.table()


class TestWebhookConfig:
    def test_session_raises_when_api_key_is_none(self, webhook_table):
        config = _WebhookConfig(webhook_table)

        with pytest.raises(Exception):
            _ = config.session

    def test_session_sets_correct_authorization_header(self, webhook_table):
        webhook_table['api_key'] = 'my-test-key'
        config = _WebhookConfig(webhook_table)

        session = config.session

        assert session.headers['Authorization'] == 'Bearer my-test-key'


class TestSlackConfig:
    def test_emit_raises_when_webhook_url_is_none(self, slack_table):
        config = _SlackConfig(slack_table)

        with pytest.raises(Exception):
            config.emit("test message")

    def test_emit_posts_correct_block_payload(self, slack_table):
        slack_table['webhook_url'] = 'https://hooks.slack.com/test'
        config = _SlackConfig(slack_table)

        with patch('requests.post') as mock_post:
            config.emit("hello world")

        mock_post.assert_called_once()
        url = mock_post.call_args.args[0]
        blocks = mock_post.call_args.kwargs['json']['blocks']
        assert url == 'https://hooks.slack.com/test'
        assert len(blocks) == 1
        assert blocks[0]['type'] == 'section'
        assert blocks[0]['text']['type'] == 'mrkdwn'
        assert blocks[0]['text']['text'] == 'hello world'

    def test_user_id_by_email_raises_when_management_token_is_none(self, slack_table):
        config = _SlackConfig(slack_table)

        with pytest.raises(Exception):
            config.user_id_by_email("test@example.com")

    def test_user_id_by_email_returns_id_when_user_found(self, slack_table):
        slack_table['management_token'] = 'xoxp-test'
        config = _SlackConfig(slack_table)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"ok": True, "user": {"id": "U123456"}}

        with patch('requests.get', return_value=mock_response):
            result = config.user_id_by_email("test@example.com")

        assert result == "U123456"

    def test_user_id_by_email_returns_none_when_not_found(self, slack_table):
        slack_table['management_token'] = 'xoxp-test'
        config = _SlackConfig(slack_table)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"ok": False, "error": "users_not_found"}

        with patch('requests.get', return_value=mock_response):
            result = config.user_id_by_email("test@example.com")

        assert result is None

    def test_user_id_by_email_raises_on_unknown_error(self, slack_table):
        slack_table['management_token'] = 'xoxp-test'
        config = _SlackConfig(slack_table)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"ok": False, "error": "account_inactive"}

        with patch('requests.get', return_value=mock_response):
            with pytest.raises(Exception):
                config.user_id_by_email("test@example.com")

    def test_invite_user_raises_when_team_id_is_none(self, slack_table):
        slack_table['admin_token'] = 'xoxp-admin'
        config = _SlackConfig(slack_table)

        with pytest.raises(Exception):
            config.invite_user("test@example.com", "regular", [])

    def test_invite_user_raises_when_admin_token_is_none(self, slack_table):
        slack_table['team_id'] = 'T123'
        config = _SlackConfig(slack_table)

        with pytest.raises(Exception):
            config.invite_user("test@example.com", "regular", [])

    def test_invite_user_returns_true_on_success(self, slack_table):
        slack_table['team_id'] = 'T123'
        slack_table['admin_token'] = 'xoxp-admin'
        config = _SlackConfig(slack_table)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"ok": True}

        with patch('requests.post', return_value=mock_response):
            result = config.invite_user("test@example.com", "regular", ["C123"])

        assert result is True

    def test_invite_user_raises_when_response_not_ok(self, slack_table):
        slack_table['team_id'] = 'T123'
        slack_table['admin_token'] = 'xoxp-admin'
        config = _SlackConfig(slack_table)

        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        mock_response.json.return_value = {"ok": False, "error": "already_invited"}

        with patch('requests.post', return_value=mock_response):
            with pytest.raises(Exception):
                config.invite_user("test@example.com", "regular", [])
