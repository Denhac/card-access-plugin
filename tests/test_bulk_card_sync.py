import uuid
from unittest.mock import Mock

import pytest

from denhac_card_access.bulk_card_sync import BulkCardSync

UDF_KEY = 'DENHAC_ID'
CAN_OPEN_HOUSE_KEY = 'dh_can_open_house'


def customer_uuid(customer_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, str(customer_id)))


def make_api_person(customer_id=100, first_name="John", last_name="Doe",
                    company="DenHac", cards=None, extra=None):
    return {
        "id": customer_id,
        "first_name": first_name,
        "last_name": last_name,
        "company": company,
        "cards": cards if cards is not None else [],
        "extra": extra if extra is not None else [],
    }


def make_api_card(card_num="12345", access=None):
    return {"card_num": card_num, "access": access if access is not None else []}


def make_api_response(data, next_page_url=None):
    response = Mock()
    response.raise_for_status = Mock()
    response.json.return_value = {"data": data, "next_page_url": next_page_url}
    return response


def make_search_builder(results=None):
    builder = Mock()
    builder.find.return_value = results or []
    return builder


def make_mock_person(customer_id=100, has_can_open_house=False, first_name="John", last_name="Doe"):
    person = Mock()
    person.first_name = first_name
    person.last_name = last_name
    person.user_defined_fields = {UDF_KEY: customer_uuid(customer_id)}
    if has_can_open_house:
        person.user_defined_fields[CAN_OPEN_HOUSE_KEY] = "True"
    return person


@pytest.fixture
def mock_card_update_helper():
    return Mock()


@pytest.fixture
def mock_person_lookup():
    lookup = Mock()
    lookup.by_udf.return_value = make_search_builder([])
    return lookup


@pytest.fixture
def bulk_sync(mock_config, mock_card_update_helper, mock_person_lookup):
    return BulkCardSync(mock_config, mock_card_update_helper, mock_person_lookup)


class TestPagination:
    def test_first_page_fetched_from_base_url(self, bulk_sync, mock_webhook_session):
        mock_webhook_session.get.return_value = make_api_response([])
        bulk_sync.loop()
        mock_webhook_session.get.assert_called_with('https://api.example.com/all_cards')

    def test_next_page_fetched_when_url_present(self, bulk_sync, mock_webhook_session):
        mock_webhook_session.get.side_effect = [
            make_api_response([], next_page_url='https://api.example.com/all_cards?page=2'),
            make_api_response([]),
        ]
        bulk_sync.loop()
        assert mock_webhook_session.get.call_count == 2
        mock_webhook_session.get.assert_called_with('https://api.example.com/all_cards?page=2')

    def test_stops_when_next_page_url_is_null(self, bulk_sync, mock_webhook_session):
        mock_webhook_session.get.return_value = make_api_response([])
        bulk_sync.loop()
        mock_webhook_session.get.assert_called_once()

    def test_handle_called_once_after_all_pages_fetched(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper):
        mock_webhook_session.get.side_effect = [
            make_api_response(
                [make_api_person(customer_id=100, cards=[make_api_card("111")])],
                next_page_url='https://api.example.com/all_cards?page=2'
            ),
            make_api_response(
                [make_api_person(customer_id=101, cards=[make_api_card("222")])]
            ),
        ]
        bulk_sync.loop()
        mock_card_update_helper.handle.assert_called_once()
        assert len(mock_card_update_helper.handle.call_args[0]) == 2


class TestCardSettingBuilding:
    def test_setting_fields_from_person_data(self, bulk_sync, mock_webhook_session, mock_card_update_helper):
        person = make_api_person(
            customer_id=100, first_name="Alice", last_name="Smith",
            company="DenHac", cards=[make_api_card("12345")]
        )
        mock_webhook_session.get.return_value = make_api_response([person])
        bulk_sync.loop()
        setting = mock_card_update_helper.handle.call_args[0][0]
        assert setting.card == 12345
        assert setting.first_name == "Alice"
        assert setting.last_name == "Smith"
        assert setting.company == "DenHac"
        assert setting.customer_id == 100

    def test_enable_denhac_true_when_in_access(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper, mock_config):
        person = make_api_person(cards=[make_api_card(access=[mock_config.denhac_access])])
        mock_webhook_session.get.return_value = make_api_response([person])
        bulk_sync.loop()
        assert mock_card_update_helper.handle.call_args[0][0].enable_denhac is True

    def test_enable_denhac_false_when_not_in_access(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper):
        person = make_api_person(cards=[make_api_card(access=[])])
        mock_webhook_session.get.return_value = make_api_response([person])
        bulk_sync.loop()
        assert mock_card_update_helper.handle.call_args[0][0].enable_denhac is False

    def test_enable_server_room_true_when_in_access(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper, mock_config):
        person = make_api_person(cards=[make_api_card(access=[mock_config.server_room_access])])
        mock_webhook_session.get.return_value = make_api_response([person])
        bulk_sync.loop()
        assert mock_card_update_helper.handle.call_args[0][0].enable_server_room is True

    def test_multiple_cards_produce_multiple_settings(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper):
        person = make_api_person(cards=[make_api_card("111"), make_api_card("222")])
        mock_webhook_session.get.return_value = make_api_response([person])
        bulk_sync.loop()
        assert len(mock_card_update_helper.handle.call_args[0]) == 2

    def test_person_with_no_cards_produces_no_settings(
            self, bulk_sync, mock_webhook_session, mock_card_update_helper):
        mock_webhook_session.get.return_value = make_api_response([make_api_person(cards=[])])
        bulk_sync.loop()
        assert len(mock_card_update_helper.handle.call_args[0]) == 0


class TestCanOpenHouse:
    def test_udf_set_to_true_when_in_extra(
            self, bulk_sync, mock_webhook_session, mock_config, mock_person_lookup):
        person = make_api_person(customer_id=100, extra=[CAN_OPEN_HOUSE_KEY])
        mock_webhook_session.get.return_value = make_api_response([person])
        mock_person = make_mock_person(customer_id=100, first_name="Alice", last_name="Smith")

        def by_udf_side_effect(key, value=None):
            if key == UDF_KEY and value == customer_uuid(100):
                return make_search_builder([mock_person])
            return make_search_builder([])

        mock_person_lookup.by_udf.side_effect = by_udf_side_effect
        bulk_sync.loop()
        assert mock_person.user_defined_fields[CAN_OPEN_HOUSE_KEY] == "True"
        mock_person.write.assert_called()
        mock_config.slack.emit.assert_called_once_with("Allowing Alice Smith to initiate open house mode")

    def test_udf_not_written_when_already_true(
            self, bulk_sync, mock_webhook_session, mock_config, mock_person_lookup):
        person = make_api_person(customer_id=100, extra=[CAN_OPEN_HOUSE_KEY])
        mock_webhook_session.get.return_value = make_api_response([person])
        mock_person = make_mock_person(customer_id=100, has_can_open_house=True)

        def by_udf_side_effect(key, value=None):
            return make_search_builder([mock_person])

        mock_person_lookup.by_udf.side_effect = by_udf_side_effect
        bulk_sync.loop()
        mock_person.write.assert_not_called()
        mock_config.slack.emit.assert_not_called()

    def test_udf_cleared_when_person_has_it_but_shouldnt(
            self, bulk_sync, mock_webhook_session, mock_config, mock_person_lookup):
        mock_webhook_session.get.return_value = make_api_response(
            [make_api_person(customer_id=100, extra=[])]
        )
        mock_person = make_mock_person(customer_id=999, has_can_open_house=True,
                                       first_name="Bob", last_name="Jones")

        def by_udf_side_effect(key, value=None):
            if key == CAN_OPEN_HOUSE_KEY and value is None:
                return make_search_builder([mock_person])
            return make_search_builder([])

        mock_person_lookup.by_udf.side_effect = by_udf_side_effect
        bulk_sync.loop()
        assert CAN_OPEN_HOUSE_KEY not in mock_person.user_defined_fields
        mock_person.write.assert_called()
        mock_config.slack.emit.assert_called_once_with("Removing ability for Bob Jones to issue open house mode")

    def test_udf_not_cleared_when_person_should_have_it(
            self, bulk_sync, mock_webhook_session, mock_config, mock_person_lookup):
        person = make_api_person(customer_id=100, extra=[CAN_OPEN_HOUSE_KEY])
        mock_webhook_session.get.return_value = make_api_response([person])
        mock_person = make_mock_person(customer_id=100, has_can_open_house=True)

        def by_udf_side_effect(key, value=None):
            return make_search_builder([mock_person])

        mock_person_lookup.by_udf.side_effect = by_udf_side_effect
        bulk_sync.loop()
        assert CAN_OPEN_HOUSE_KEY in mock_person.user_defined_fields
        mock_person.write.assert_not_called()
        mock_config.slack.emit.assert_not_called()
