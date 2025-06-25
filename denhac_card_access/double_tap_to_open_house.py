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
        self._card_scans = [x for x in self._card_scans if x.scan_time >= before]

        if self._current_open_house is not None:
            now = datetime.now()
            end_time = datetime.combine(now, self._current_open_house.end_time)
            if now > end_time:
                self._current_open_house = None

        return int(timedelta(minutes=1).total_seconds())

    def card_scanned(self, card_scan: CardScan) -> None:
        self._logger.info(f"Card scan: {card_scan}")
        # Not one of the doors denhac has access to
        door: Optional[Door] = self._door_lookup.by_card_scan(card_scan)
        if door is None:
            return

        now = datetime.now()
        before = now - self._scan_within

        self._logger.info(f"Before: {before}")
        self._logger.info(f"# Card scans: {len(self._card_scans)}")
        for cs in self._card_scans:
            self._logger.info(f"Card Scans: {cs}")

        matching_scans = [
            x for x in self._card_scans
            if x.name_id == card_scan.name_id
               and x.device == card_scan.device
               and x.location_id == card_scan.location_id
               and x.scan_time >= card_scan.scan_time
        ]

        self._card_scans.append(card_scan)

        if len(matching_scans) == 0:
            self._logger.info("No matching scans")
            return  # Nothing more to do, we didn't get a matching scan within the last `_scan_within`

        # Remove the card scans so 3 taps isn't open and then immediately close
        for scan in matching_scans:
            self._card_scans.remove(scan)

        person: Person = self._person_lookup.by_id(card_scan.name_id)
        self._logger.info(f"{person.first_name} {person.last_name} double tapped for an open house")

        if self._config.udf_key_can_open_house not in person.user_defined_fields:
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
        open_house_name = sorted(valid_open_houses.items(), key=lambda x: x[1].end_time)[0][0]
        open_house: OpenHouseConfig = valid_open_houses[open_house_name]

        time_difference: timedelta = datetime.combine(datetime.today(), open_house.end_time) - now

        # Are we initiating or closing open house mode?
        initiating = self._current_open_house is None
        self._current_open_house = open_house if initiating else None

        if initiating:
            self._logger.info(
                f"{person.first_name} {person.last_name} initiated open house mode `{open_house_name}` at {now}"
            )
        else:
            self._logger.info(
                f"{person.first_name} {person.last_name} stopped open house mode `{open_house_name}` at {now}"
            )

        self._logger.info(f"There are {len(open_house.door_ids)} doors we can open")

        for door_id in open_house.door_ids:
            self._logger.info(f"Lookup up door with id {door_id}")
            door: Optional[Door] = self._door_lookup.by_id(door_id)

            if door is None:
                continue

            self._logger.info("Found the door!")

            if initiating:
                self._logger.info(f"Opening it up for {time_difference}")
                door.open(time_difference)
            else:
                self._logger.info("Time zoned!")
                door.timezone()
