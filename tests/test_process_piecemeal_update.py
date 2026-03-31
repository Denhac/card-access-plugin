from unittest.mock import Mock

import pytest

from denhac_card_access.card_update_helper import CardSetting
from denhac_card_access.process_piecemeal_update import ProcessPiecemealUpdate


def make_command(id=1, method="enable", card=12345, company="denhac", woo_id=100,
                 first_name="John", last_name="Doe"):
    return {
        "id": id,
        "method": method,
        "card": card,
        "company": company,
        "woo_id": woo_id,
        "first_name": first_name,
        "last_name": last_name,
    }


def make_commands_response(commands):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"data": commands}
    return response


def make_status_response():
    response = Mock()
    response.raise_for_status = Mock()
    return response


@pytest.fixture
def mock_card_update_helper():
    return Mock()


@pytest.fixture
def process_piecemeal_update(mock_config, mock_card_update_helper):
    return ProcessPiecemealUpdate(mock_config, mock_card_update_helper)


@pytest.fixture
def mark_complete(mock_card_update_helper):
    return mock_card_update_helper.register.call_args[0][0]


class TestConstructor:
    def test_raises_if_slack_webhook_url_is_none(self, mock_config, mock_card_update_helper):
        mock_config.slack.webhook_url = None
        with pytest.raises(Exception):
            ProcessPiecemealUpdate(mock_config, mock_card_update_helper)

    def test_raises_if_base_url_is_none(self, mock_config, mock_card_update_helper):
        mock_config.webhooks.base_url = None
        with pytest.raises(Exception):
            ProcessPiecemealUpdate(mock_config, mock_card_update_helper)

    def test_registers_mark_complete_callback(self, mock_card_update_helper, process_piecemeal_update):
        mock_card_update_helper.register.assert_called_once()


class TestGetCommands:
    def test_fetches_commands_from_api(self, process_piecemeal_update, mock_webhook_session):
        mock_webhook_session.get.return_value = make_commands_response([])
        process_piecemeal_update.loop()
        mock_webhook_session.get.assert_called_with("https://api.example.com/card_updates")

    def test_no_commands_when_data_key_missing(self, process_piecemeal_update, mock_webhook_session,
                                               mock_card_update_helper):
        response = Mock()
        response.raise_for_status = Mock()
        response.json.return_value = {}
        mock_webhook_session.get.return_value = response

        process_piecemeal_update.loop()

        mock_card_update_helper.handle.assert_not_called()


class TestCommandHandling:
    def test_handle_called_with_correct_card_setting(self, process_piecemeal_update, mock_webhook_session,
                                                     mock_card_update_helper):
        command = make_command(card=12345, first_name="Alice", last_name="Smith",
                               company="denhac", woo_id=200)
        mock_webhook_session.get.return_value = make_commands_response([command])

        process_piecemeal_update.loop()

        setting: CardSetting = mock_card_update_helper.handle.call_args[0][0]
        assert setting.card == 12345
        assert setting.first_name == "Alice"
        assert setting.last_name == "Smith"
        assert setting.company == "denhac"
        assert setting.customer_id == 200

    def test_enable_denhac_true_when_method_is_enable(self, process_piecemeal_update, mock_webhook_session,
                                                      mock_card_update_helper):
        mock_webhook_session.get.return_value = make_commands_response([make_command(method="enable")])
        process_piecemeal_update.loop()
        assert mock_card_update_helper.handle.call_args[0][0].enable_denhac is True

    def test_enable_denhac_false_when_method_is_disable(self, process_piecemeal_update, mock_webhook_session,
                                                        mock_card_update_helper):
        mock_webhook_session.get.return_value = make_commands_response([make_command(method="disable")])
        process_piecemeal_update.loop()
        assert mock_card_update_helper.handle.call_args[0][0].enable_denhac is False

    def test_known_id_skipped_on_second_loop(self, process_piecemeal_update, mock_webhook_session,
                                             mock_card_update_helper):
        mock_webhook_session.get.return_value = make_commands_response([make_command(id=42)])
        process_piecemeal_update.loop()
        process_piecemeal_update.loop()
        mock_card_update_helper.handle.assert_called_once()


class TestCardDataPushed:
    def test_delegates_to_card_update_helper(self, process_piecemeal_update, mock_card_update_helper):
        access_card = Mock()
        process_piecemeal_update.card_data_pushed(access_card)
        mock_card_update_helper.card_updated.assert_called_once_with(access_card)


class TestMarkComplete:
    def test_posts_success_status_for_command(self, process_piecemeal_update, mock_webhook_session,
                                              mock_card_update_helper, mark_complete):
        mock_webhook_session.get.return_value = make_commands_response([make_command(id=7)])
        mock_webhook_session.post.return_value = make_status_response()
        process_piecemeal_update.loop()

        setting = mock_card_update_helper.handle.call_args[0][0]
        mark_complete(setting)

        mock_webhook_session.post.assert_called_once_with(
            "https://api.example.com/card_updates/7/status",
            json={"status": "success"},
        )
