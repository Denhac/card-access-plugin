from datetime import timedelta, datetime
from typing import Optional

from card_automation_server.plugins.interfaces import PluginCardScanned, PluginLoop
from card_automation_server.plugins.types import CardScan
from card_automation_server.windsx.lookup.door_lookup import DoorLookup, Door
from card_automation_server.windsx.lookup.person import PersonLookup, Person

from denhac_card_access.config import Config, OpenHouseConfig


class DoubleTapToOpenHouse(PluginCardScanned, PluginLoop):
    _scan_within = timedelta(seconds=10)

    def __init__(self,
                 config: Config,
                 door_lookup: DoorLookup,
                 person_lookup: PersonLookup
                 ):
        self._config = config

        self._door_lookup = door_lookup
        self._person_lookup = person_lookup

        self._logger = config.logger

        self._card_scans: list[CardScan] = []

        self._current_open_house: Optional[OpenHouseConfig] = None

    def loop(self) -> int:
        # Every minute, clear out all the card scans older than `_scan_within` time before now.
        before = datetime.now() - self._scan_within
        # self._card_scans = [x for x in self._card_scans if x.scan_time >= before]

        return 60

    def card_scanned(self, card_scan: CardScan) -> None:
        self._logger.info(f"Card scan: {card_scan}")
        # Not one of the doors denhac has access to
        door: Optional[Door] = self._door_lookup.by_card_scan(card_scan)
        if door is None:
            return

        self._logger.info(f"Got a card scan from name id {card_scan.name_id}")

        now = datetime.now()
        before = now - self._scan_within

        self._logger.info(f"Before: {before}")
        for cs in self._card_scans:
            self._logger.info(f"Card Scans: {cs}")

        matching_scans = [
            x for x in self._card_scans
            if x.name_id == card_scan.name_id
               and x.device == card_scan.device
               and x.location_id == card_scan.location_id
               and x.scan_time >= before
        ]

        self._card_scans.append(card_scan)

        if len(matching_scans) == 0:
            self._logger.info("No matching scans")
            return  # Nothing more to do, we didn't get a matching scan within the last `_scan_within`

        person: Person = self._person_lookup.by_id(card_scan.name_id)
        self._logger.info(f"{person.first_name} {person.last_name} double tapped for an open house")

        if self._config.udf_key_can_open_house not in person:
            self._logger.info(f"They are not allowed to activate open house")
            return  # They definitely can't open house

        if person.user_defined_fields[self._config.udf_key_can_open_house] == "False":
            self._logger.info(f"They are not allowed to activate open house")
            return  # They also can't open house

        # This person can open house! Let's see if they can do it right now

        now = datetime.now()

        valid_open_houses = {
            name: oh for (name, oh) in self._config.open_houses.items()
            if oh.day_of_week == now.weekday()
               and oh.scan_after_time <= now.time() < oh.end_time
        }

        if len(valid_open_houses) == 0:
            self._logger.info("No valid open houses available right now")
            return  # It's a bad time to try and open house

        # We shouldn't have multiple overlapping open houses, but if we do, we pick the one with the closest end time
        open_house_name = sorted(valid_open_houses.items(), key=lambda x: x[1][x.end_time])[0][0]
        open_house: OpenHouseConfig = valid_open_houses[open_house_name]

        time_difference: timedelta = datetime.combine(now.today(), open_house.end_time) - now

        # Are we initiating or closing open house mode?
        initiating = self._current_open_house = None
        self._current_open_house = open_house if initiating else None

        if initiating:
            self._logger.info(
                f"{person.first_name} {person.last_name} initiated open house mode `{open_house_name}` at {now}"
            )
        else:
            self._logger.info(
                f"{person.first_name} {person.last_name} stopped open house mode `{open_house_name}` at {now}"
            )

        for door_id in open_house.door_ids:
            door: Optional[Door] = self._door_lookup.by_id(door_id)

            if door is None:
                continue

            if initiating:
                door.open(time_difference)
            else:
                door.timezone()
