import uuid
from unittest.mock import Mock

import pytest

from denhac_card_access.card_update_helper import CardSetting, CardUpdateHelper

UDF_KEY = 'DENHAC_ID'  # Must match mock_config.udf_key_denhac_id


def customer_uuid(customer_id: int) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_OID, str(customer_id)))


def make_setting(card=12345, customer_id=100, first_name="John", last_name="Doe",
                 company="denhac", enable_denhac=True, enable_server_room=False):
    return CardSetting(
        card=card,
        first_name=first_name,
        last_name=last_name,
        company=company,
        customer_id=customer_id,
        enable_denhac=enable_denhac,
        enable_server_room=enable_server_room,
    )


def make_mock_person(name_id=1, customer_id=100, first_name="John", last_name="Doe"):
    person = Mock()
    person.id = name_id
    person.in_db = True
    person.first_name = first_name
    person.last_name = last_name
    person.user_defined_fields = {UDF_KEY: customer_uuid(customer_id)}
    return person


def make_mock_card(card_number=12345, name_id=None, active=False, access=None, person=None):
    card = Mock()
    card.card_number = card_number
    card.name_id = name_id
    card.active = active
    card.access = frozenset(access or [])
    card.person = person
    return card


@pytest.fixture
def mock_person_lookup():
    lookup = Mock()
    search_builder = Mock()
    search_builder.find.return_value = []
    lookup.by_udf.return_value = search_builder

    new_person = Mock()
    new_person.id = None
    new_person.in_db = False
    new_person.user_defined_fields = {}

    def write_person():
        new_person.id = 99
        new_person.in_db = True

    new_person.write.side_effect = write_person
    lookup.new.return_value = new_person
    return lookup


@pytest.fixture
def mock_access_card_lookup():
    lookup = Mock()
    lookup.with_people.return_value = lookup
    lookup.by_card_numbers.return_value = []

    new_card = Mock()
    new_card.active = False
    new_card.access = frozenset()
    lookup.new.return_value = new_card
    return lookup


@pytest.fixture
def helper(mock_config, mock_person_lookup, mock_access_card_lookup):
    return CardUpdateHelper(mock_config, mock_person_lookup, mock_access_card_lookup)


class TestBatchCardLookup:
    def test_with_people_called_on_batch_lookup(self, helper, mock_access_card_lookup):
        helper.handle(make_setting(card=100))
        mock_access_card_lookup.with_people.assert_called_once()

    def test_by_card_numbers_called_with_all_card_numbers(self, helper, mock_access_card_lookup):
        helper.handle(make_setting(card=100), make_setting(card=200, customer_id=101))
        mock_access_card_lookup.by_card_numbers.assert_called_once_with(100, 200)

    def test_duplicate_card_number_skips_both_settings(self, helper, mock_access_card_lookup, mock_config):
        s1 = make_setting(card=100, customer_id=100)
        s2 = make_setting(card=100, customer_id=101)
        helper.handle(s1, s2)
        mock_access_card_lookup.new.assert_not_called()
        mock_config.logger.error.assert_called()

    def test_non_duplicate_settings_still_processed_alongside_duplicates(
            self, helper, mock_access_card_lookup):
        duplicate1 = make_setting(card=100, customer_id=100)
        duplicate2 = make_setting(card=100, customer_id=101)
        good_setting = make_setting(card=200, customer_id=102)
        helper.handle(duplicate1, duplicate2, good_setting)
        mock_access_card_lookup.new.assert_called_once_with(200)


class TestPersonLookup:
    def test_new_person_created_when_not_found(self, helper, mock_person_lookup):
        helper.handle(make_setting(customer_id=100))
        mock_person_lookup.new.assert_called_once()

    def test_new_person_has_correct_name(self, helper, mock_person_lookup):
        helper.handle(make_setting(customer_id=100, first_name="Alice", last_name="Smith"))
        new_person = mock_person_lookup.new.return_value
        assert new_person.first_name == "Alice"
        assert new_person.last_name == "Smith"

    def test_new_person_has_correct_company(self, helper, mock_person_lookup, mock_config):
        helper.handle(make_setting(customer_id=100))
        new_person = mock_person_lookup.new.return_value
        assert new_person.company_id == mock_config.company_id

    def test_new_person_has_correct_udf(self, helper, mock_person_lookup):
        helper.handle(make_setting(customer_id=100))
        new_person = mock_person_lookup.new.return_value
        assert new_person.user_defined_fields.get(UDF_KEY) == customer_uuid(100)

    def test_new_person_is_written(self, helper, mock_person_lookup):
        helper.handle(make_setting(customer_id=100))
        mock_person_lookup.new.return_value.write.assert_called_once()

    def test_existing_person_used_when_found_via_udf(self, helper, mock_person_lookup):
        existing = make_mock_person(name_id=42, customer_id=100)
        mock_person_lookup.by_udf.return_value.find.return_value = [existing]
        helper.handle(make_setting(customer_id=100))
        mock_person_lookup.new.assert_not_called()

    def test_existing_person_first_name_not_modified(self, helper, mock_person_lookup):
        existing = make_mock_person(name_id=42, customer_id=100, first_name="OldFirst")
        mock_person_lookup.by_udf.return_value.find.return_value = [existing]
        helper.handle(make_setting(customer_id=100, first_name="NewFirst"))
        assert existing.first_name == "OldFirst"

    def test_existing_person_last_name_not_modified(self, helper, mock_person_lookup):
        existing = make_mock_person(name_id=42, customer_id=100, last_name="OldLast")
        mock_person_lookup.by_udf.return_value.find.return_value = [existing]
        helper.handle(make_setting(customer_id=100, last_name="NewLast"))
        assert existing.last_name == "OldLast"

    def test_same_customer_id_only_looked_up_once(self, helper, mock_person_lookup):
        existing = make_mock_person(name_id=42, customer_id=100)
        mock_person_lookup.by_udf.return_value.find.return_value = [existing]
        helper.handle(make_setting(card=100, customer_id=100), make_setting(card=200, customer_id=100))
        mock_person_lookup.by_udf.assert_called_once()

    def test_same_customer_id_only_creates_one_new_person(self, helper, mock_person_lookup):
        helper.handle(make_setting(card=100, customer_id=100), make_setting(card=200, customer_id=100))
        mock_person_lookup.new.assert_called_once()

    def test_udf_lookup_skipped_when_person_found_via_eager_load(
            self, helper, mock_access_card_lookup, mock_person_lookup):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100))
        mock_person_lookup.by_udf.assert_not_called()


class TestCardHandling:
    def test_new_card_created_when_not_in_batch_results(self, helper, mock_access_card_lookup):
        helper.handle(make_setting(card=12345))
        mock_access_card_lookup.new.assert_called_once_with(12345)

    def test_existing_card_not_recreated(self, helper, mock_access_card_lookup):
        person = make_mock_person(name_id=42, customer_id=100)
        existing_card = make_mock_card(card_number=12345, name_id=42, person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [existing_card]
        helper.handle(make_setting(card=12345, customer_id=100))
        mock_access_card_lookup.new.assert_not_called()

    def test_card_assigned_to_person(self, helper, mock_person_lookup, mock_access_card_lookup):
        person = make_mock_person(name_id=42, customer_id=100)
        mock_person_lookup.by_udf.return_value.find.return_value = [person]
        helper.handle(make_setting(card=12345, customer_id=100))
        new_card = mock_access_card_lookup.new.return_value
        assert new_card.person == person

    def test_card_reassigned_when_on_wrong_person(self, helper, mock_access_card_lookup, mock_person_lookup):
        correct_person = make_mock_person(name_id=42, customer_id=100)
        mock_person_lookup.by_udf.return_value.find.return_value = [correct_person]
        wrong_person = make_mock_person(name_id=99, customer_id=999)
        card_on_wrong_person = make_mock_card(card_number=12345, name_id=99, person=wrong_person)
        mock_access_card_lookup.by_card_numbers.return_value = [card_on_wrong_person]
        helper.handle(make_setting(card=12345, customer_id=100))
        assert card_on_wrong_person.person == correct_person

    def test_card_written_when_only_owner_changes(
            self, helper, mock_access_card_lookup, mock_person_lookup, mock_config):
        correct_person = make_mock_person(name_id=42, customer_id=100)
        mock_person_lookup.by_udf.return_value.find.return_value = [correct_person]
        wrong_person = make_mock_person(name_id=99, customer_id=999)
        card = make_mock_card(card_number=12345, name_id=99, active=True,
                              access=[mock_config.denhac_access], person=wrong_person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100, enable_denhac=True))
        card.write.assert_called_once()


class TestAccessUpdates:
    def test_denhac_access_added_when_enable_denhac_true(self, helper, mock_access_card_lookup, mock_config):
        card = mock_access_card_lookup.new.return_value
        card.active = False
        card.access = frozenset()
        helper.handle(make_setting(card=12345, enable_denhac=True))
        card.with_access.assert_called_with(mock_config.denhac_access)

    def test_denhac_access_removed_when_card_has_it_and_disabled(
            self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, active=True,
                              access=['denhac'], person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100, enable_denhac=False))
        card.without_access.assert_called_with(mock_config.denhac_access)

    def test_server_room_access_added_when_enabled(self, helper, mock_access_card_lookup, mock_config):
        card = mock_access_card_lookup.new.return_value
        card.active = False
        card.access = frozenset()
        helper.handle(make_setting(card=12345, enable_server_room=True))
        card.with_access.assert_called_with(mock_config.server_room_access)

    def test_mbd_access_removed_when_card_has_it(
            self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, active=True,
                              access=[mock_config.main_building_access], person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100))
        card.without_access.assert_called_with(mock_config.main_building_access)

    def test_card_written_when_access_changes(self, helper, mock_access_card_lookup):
        card = mock_access_card_lookup.new.return_value
        card.active = False
        card.access = frozenset()
        helper.handle(make_setting(card=12345, enable_denhac=True))
        card.write.assert_called_once()

    def test_card_not_written_when_no_access_changes(
            self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, active=True,
                              access=[mock_config.denhac_access], person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100, enable_denhac=True))
        card.write.assert_not_called()

    def test_callback_invoked_when_no_changes_needed(
            self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, active=True,
                              access=[mock_config.denhac_access], person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        callback = Mock()
        helper.register(callback)
        setting = make_setting(card=12345, customer_id=100, enable_denhac=True)
        helper.handle(setting)
        callback.assert_called_once_with(setting)

    def test_slack_emitted_when_access_changes(self, helper, mock_access_card_lookup, mock_config):
        card = mock_access_card_lookup.new.return_value
        card.active = False
        card.access = frozenset()
        helper.handle(make_setting(card=12345, enable_denhac=True))
        mock_config.slack.emit.assert_called_once()

    def test_slack_not_emitted_when_no_access_changes(
            self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, name_id=42, active=True,
                              access=[mock_config.denhac_access], person=person)
        mock_access_card_lookup.by_card_numbers.return_value = [card]
        helper.handle(make_setting(card=12345, customer_id=100, enable_denhac=True))
        mock_config.slack.emit.assert_not_called()


class TestCardUpdated:
    def test_card_updated_sends_slack(self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, access=[], person=person)
        helper.handle(make_setting(card=12345, enable_denhac=True))
        mock_config.slack.emit.reset_mock()

        helper.card_updated(card)

        mock_config.slack.emit.assert_called_once()

    def test_card_updated_twice_only_sends_slack_once(self, helper, mock_access_card_lookup, mock_config):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, access=[], person=person)
        helper.handle(make_setting(card=12345, enable_denhac=True))
        mock_config.slack.emit.reset_mock()

        helper.card_updated(card)
        helper.card_updated(card)

        mock_config.slack.emit.assert_called_once()

    def test_card_updated_twice_only_fires_callback_once(self, helper, mock_access_card_lookup):
        person = make_mock_person(name_id=42, customer_id=100)
        card = make_mock_card(card_number=12345, access=[], person=person)
        callback = Mock()
        helper.register(callback)
        helper.handle(make_setting(card=12345, enable_denhac=True))

        helper.card_updated(card)
        helper.card_updated(card)

        callback.assert_called_once()
