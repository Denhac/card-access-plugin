from unittest.mock import Mock, MagicMock

import pytest


@pytest.fixture
def mock_webhook_session() -> Mock:
    return Mock()


@pytest.fixture
def mock_config(mock_webhook_session: Mock) -> MagicMock:
    config = MagicMock()
    config.webhooks.base_url = 'https://api.example.com'
    config.webhooks.session = mock_webhook_session
    config.slack.webhook_url = 'https://hooks.slack.com/test'
    config.logger = MagicMock()
    config.udf_key_denhac_id = 'DENHAC_ID'
    config.udf_key_can_open_house = 'dh_can_open_house'
    config.denhac_access = 'denhac'
    config.server_room_access = 'Server Room'
    config.main_building_access = 'MBD Access'
    config.company_id = 14
    return config
