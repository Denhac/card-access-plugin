from datetime import datetime
from unittest.mock import Mock

import pytest

from card_automation_server.plugins.types import CardScan, CommServerEventType
from denhac_card_access.submit_card_scan import SubmitCardScan


def make_card_scan(name_id=1, card_number=12345, event_type: CommServerEventType = CommServerEventType.ACCESS_GRANTED,
                   device=10, location_id=1):
    return CardScan(
        name_id=name_id,
        card_number=card_number,
        scan_time=datetime(2024, 1, 1, 12, 0, 0),
        device=device,
        event_type=event_type,
        location_id=location_id,
    )


def make_mock_door(location_id=1, device_id=10, name="Front Door"):
    door = Mock()
    door.location_id = location_id
    door.device_id = device_id
    door.name = name
    return door


def make_mock_person(first_name="John", last_name="Doe", is_denhac_member=True):
    person = Mock()
    person.first_name = first_name
    person.last_name = last_name
    person.user_defined_fields = {"DENHAC_ID": "some-uuid"} if is_denhac_member else {}
    return person


def make_post_response(ok=True, status_code=200):
    response = Mock()
    response.ok = ok
    response.status_code = status_code
    return response


@pytest.fixture
def mock_door_lookup():
    lookup = Mock()
    lookup.by_card_scan.return_value = make_mock_door()
    return lookup


@pytest.fixture
def mock_person_lookup():
    lookup = Mock()
    lookup.by_id.return_value = make_mock_person()
    return lookup


@pytest.fixture
def submit_card_scan(mock_config, mock_door_lookup, mock_person_lookup):
    return SubmitCardScan(mock_config, mock_door_lookup, mock_person_lookup)


class TestConstructor:
    def test_raises_if_base_url_is_none(self, mock_config, mock_door_lookup, mock_person_lookup):
        mock_config.webhooks.base_url = None
        with pytest.raises(Exception):
            SubmitCardScan(mock_config, mock_door_lookup, mock_person_lookup)


class TestEarlyReturns:
    def test_no_post_when_door_not_found(self, submit_card_scan, mock_door_lookup, mock_webhook_session):
        mock_door_lookup.by_card_scan.return_value = None
        submit_card_scan.card_scanned(make_card_scan())
        mock_webhook_session.post.assert_not_called()

    def test_no_post_when_not_denhac_member(self, submit_card_scan, mock_person_lookup, mock_webhook_session):
        mock_person_lookup.by_id.return_value = make_mock_person(is_denhac_member=False)
        submit_card_scan.card_scanned(make_card_scan())
        mock_webhook_session.post.assert_not_called()


class TestCardScanPost:
    def test_posts_to_card_scanned_endpoint(self, submit_card_scan, mock_webhook_session):
        mock_webhook_session.post.return_value = make_post_response()
        submit_card_scan.card_scanned(make_card_scan())
        url = mock_webhook_session.post.call_args[0][0]
        assert url == "https://api.example.com/events/card_scanned"

    def test_post_payload_fields(self, submit_card_scan, mock_door_lookup, mock_person_lookup, mock_webhook_session):
        mock_door_lookup.by_card_scan.return_value = make_mock_door(device_id=42)
        mock_person_lookup.by_id.return_value = make_mock_person(first_name="Alice", last_name="Smith")
        mock_webhook_session.post.return_value = make_post_response()
        scan = make_card_scan(card_number=99999)

        submit_card_scan.card_scanned(scan)

        payload = mock_webhook_session.post.call_args[1]["json"]
        assert payload["first_name"] == "Alice"
        assert payload["last_name"] == "Smith"
        assert payload["card_num"] == 99999
        assert payload["scan_time"] == scan.scan_time.isoformat()
        assert payload["device"] == 42

    def test_access_allowed_true_when_granted(self, submit_card_scan, mock_webhook_session):
        mock_webhook_session.post.return_value = make_post_response()
        submit_card_scan.card_scanned(make_card_scan(event_type=CommServerEventType.ACCESS_GRANTED))
        payload = mock_webhook_session.post.call_args[1]["json"]
        assert payload["access_allowed"] is True

    def test_access_allowed_false_when_denied(self, submit_card_scan, mock_webhook_session):
        mock_webhook_session.post.return_value = make_post_response()
        submit_card_scan.card_scanned(make_card_scan(event_type=CommServerEventType.DENIED_WRONG_ACCESS_LEVEL))
        payload = mock_webhook_session.post.call_args[1]["json"]
        assert payload["access_allowed"] is False

    def test_raises_when_response_not_ok(self, submit_card_scan, mock_webhook_session):
        mock_webhook_session.post.return_value = make_post_response(ok=False, status_code=500)
        with pytest.raises(Exception):
            submit_card_scan.card_scanned(make_card_scan())
