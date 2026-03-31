from contextlib import contextmanager
from datetime import datetime as real_datetime, timedelta, time
from unittest.mock import Mock, patch

import pytest

from card_automation_server.plugins.types import CardScan, CommServerEventType
from denhac_card_access.double_tap_to_open_house import DoubleTapToOpenHouse

# Wednesday Jan 3, 2024 at 18:30 (weekday() == 2)
NOW = real_datetime(2024, 1, 3, 18, 30, 0)


@contextmanager
def at_time(now):
    # Patches datetime.now() to a fixed value while keeping combine/today using real implementations
    with patch('denhac_card_access.double_tap_to_open_house.datetime') as mock_dt:
        mock_dt.now.return_value = now
        mock_dt.combine.side_effect = real_datetime.combine
        mock_dt.today.return_value = now
        yield mock_dt


def make_card_scan(name_id=1, card_number=12345,
                   event_type=CommServerEventType.ACCESS_GRANTED,
                   device=10, location_id=1, scan_time=None):
    return CardScan(
        name_id=name_id,
        card_number=card_number,
        scan_time=scan_time if scan_time is not None else NOW,
        device=device,
        event_type=event_type,
        location_id=location_id,
    )


def make_open_house_config(day_of_week=2, scan_after_time=time(18, 0), end_time=time(21, 0), door_ids=None):
    oh = Mock()
    oh.day_of_week = day_of_week
    oh.scan_after_time = scan_after_time
    oh.end_time = end_time
    oh.door_ids = door_ids if door_ids is not None else [1]
    return oh


def make_mock_person(open_house_udf=None):
    person = Mock()
    person.first_name = "Alice"
    person.last_name = "Smith"
    person.user_defined_fields = {}
    if open_house_udf is not None:
        person.user_defined_fields["dh_can_open_house"] = open_house_udf
    return person


@pytest.fixture
def mock_door():
    return Mock()


@pytest.fixture
def mock_door_lookup(mock_door):
    lookup = Mock()
    lookup.by_card_scan.return_value = mock_door
    lookup.by_id.return_value = mock_door
    return lookup


@pytest.fixture
def mock_person_lookup():
    lookup = Mock()
    lookup.by_id.return_value = make_mock_person(open_house_udf="True")
    return lookup


@pytest.fixture
def double_tap(mock_config, mock_door_lookup, mock_person_lookup):
    return DoubleTapToOpenHouse(mock_config, mock_door_lookup, mock_person_lookup)


@pytest.fixture
def valid_open_house(mock_config):
    oh = make_open_house_config()
    mock_config.open_houses.items.return_value = {"Wednesday Open House": oh}.items()
    return oh


class TestEarlyReturns:
    def test_no_door_lookup_when_access_denied(self, double_tap, mock_door_lookup):
        double_tap.card_scanned(make_card_scan(event_type=CommServerEventType.DENIED_WRONG_ACCESS_LEVEL))
        mock_door_lookup.by_card_scan.assert_not_called()

    def test_no_door_lookup_when_name_id_is_none(self, double_tap, mock_door_lookup):
        double_tap.card_scanned(make_card_scan(name_id=None))
        mock_door_lookup.by_card_scan.assert_not_called()

    def test_no_person_lookup_when_door_not_found(self, double_tap, mock_door_lookup, mock_person_lookup):
        mock_door_lookup.by_card_scan.return_value = None
        double_tap.card_scanned(make_card_scan())
        mock_person_lookup.by_id.assert_not_called()


class TestSingleScan:
    def test_no_door_action_on_first_scan(self, double_tap, mock_door):
        double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()
        mock_door.timezone.assert_not_called()


class TestDoubleTapDetection:
    def test_double_tap_triggers_on_matching_scan(self, double_tap, mock_door, valid_open_house):
        with at_time(NOW):
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_called_once()

    def test_no_trigger_when_different_person(self, double_tap, mock_person_lookup):
        double_tap.card_scanned(make_card_scan(name_id=1))
        double_tap.card_scanned(make_card_scan(name_id=2))
        mock_person_lookup.by_id.assert_not_called()

    def test_no_trigger_when_different_device(self, double_tap, mock_person_lookup):
        double_tap.card_scanned(make_card_scan(device=10))
        double_tap.card_scanned(make_card_scan(device=20))
        mock_person_lookup.by_id.assert_not_called()

    def test_no_trigger_when_different_location(self, double_tap, mock_person_lookup):
        double_tap.card_scanned(make_card_scan(location_id=1))
        double_tap.card_scanned(make_card_scan(location_id=2))
        mock_person_lookup.by_id.assert_not_called()


class TestPersonGuards:
    def test_no_door_action_when_person_not_found(self, double_tap, mock_person_lookup, mock_door):
        mock_person_lookup.by_id.return_value = None
        double_tap.card_scanned(make_card_scan())
        double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()

    def test_no_door_action_when_open_house_udf_missing(self, double_tap, mock_person_lookup, mock_door):
        mock_person_lookup.by_id.return_value = make_mock_person()
        double_tap.card_scanned(make_card_scan())
        double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()

    def test_no_door_action_when_open_house_udf_not_true(self, double_tap, mock_person_lookup, mock_door):
        mock_person_lookup.by_id.return_value = make_mock_person(open_house_udf="False")
        double_tap.card_scanned(make_card_scan())
        double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()


class TestOpenHouseTiming:
    def test_no_door_action_when_no_open_houses_configured(self, double_tap, mock_config, mock_door):
        mock_config.open_houses.items.return_value = {}.items()
        with at_time(NOW):
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()

    def test_no_door_action_when_wrong_day_of_week(self, double_tap, mock_config, mock_door):
        mock_config.open_houses.items.return_value = {
            "Monday Open House": make_open_house_config(day_of_week=0)
        }.items()
        with at_time(NOW):  # Wednesday
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()

    def test_no_door_action_before_scan_after_time(self, double_tap, mock_config, mock_door):
        mock_config.open_houses.items.return_value = {
            "Late Open House": make_open_house_config(scan_after_time=time(19, 0))
        }.items()
        with at_time(NOW):  # 18:30, before 19:00
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()

    def test_no_door_action_after_end_time(self, double_tap, mock_config, mock_door):
        mock_config.open_houses.items.return_value = {
            "Early Open House": make_open_house_config(end_time=time(18, 0))
        }.items()
        with at_time(NOW):  # 18:30, past 18:00 end_time
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.open.assert_not_called()


class TestOpenHouseDoors:
    def test_door_opened_with_remaining_duration_when_initiating(self, double_tap, mock_door, valid_open_house):
        with at_time(NOW):  # 18:30, open house ends at 21:00 → 2.5 hours remaining
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        expected_duration = real_datetime.combine(NOW, valid_open_house.end_time) - NOW
        mock_door.open.assert_called_once_with(expected_duration)

    def test_door_timezone_called_when_closing(self, double_tap, mock_door, valid_open_house):
        with at_time(NOW):
            # First double-tap initiates open house
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
            # Second double-tap closes it
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        mock_door.timezone.assert_called_once()

    def test_scans_cleared_after_double_tap(self, double_tap, mock_door, valid_open_house):
        with at_time(NOW):
            # First double-tap initiates open house, consuming both scans
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())
        # Third tap is the first of a new sequence — should not close the open house
        double_tap.card_scanned(make_card_scan())
        mock_door.timezone.assert_not_called()


class TestLoop:
    def test_old_scans_cleared(self, double_tap, mock_person_lookup):
        double_tap.card_scanned(make_card_scan(scan_time=NOW))

        # Loop runs 11 seconds later — prior scan is outside the 10-second window
        with at_time(NOW + timedelta(seconds=11)):
            double_tap.loop()

        # Second scan would be a double-tap if first scan were still present
        double_tap.card_scanned(make_card_scan(scan_time=NOW + timedelta(seconds=11)))
        mock_person_lookup.by_id.assert_not_called()

    def test_open_house_cleared_past_end_time(self, double_tap, mock_door, valid_open_house):
        with at_time(NOW):
            double_tap.card_scanned(make_card_scan())
            double_tap.card_scanned(make_card_scan())

        # Loop runs after end_time
        after_end = real_datetime(2024, 1, 3, 21, 1, 0)
        with at_time(after_end):
            double_tap.loop()

        # Next double-tap should initiate again (not close), confirming open house was cleared
        re_init_time = real_datetime(2024, 1, 3, 20, 55, 0)
        with at_time(re_init_time):
            double_tap.card_scanned(make_card_scan(scan_time=re_init_time))
            double_tap.card_scanned(make_card_scan(scan_time=re_init_time))

        assert mock_door.open.call_count == 2
        mock_door.timezone.assert_not_called()
