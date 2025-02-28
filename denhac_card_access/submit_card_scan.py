from typing import Optional

from card_automation_server.plugins.interfaces import PluginCardScanned
from card_automation_server.plugins.types import CardScan, CardScanEventType
from card_automation_server.windsx.lookup.door_lookup import DoorLookup, Door
from card_automation_server.windsx.lookup.person import Person, PersonLookup

from denhac_card_access.config import Config


class SubmitCardScan(PluginCardScanned):
    def __init__(self,
                 config: Config,
                 door_lookup: DoorLookup,
                 person_lookup: PersonLookup
                 ):
        self._config = config
        self._logger = config.logger

        if self._config.webhooks.base_url is None:
            raise Exception("Webhooks base url cannot be None")
        self._api_base = self._config.webhooks.base_url
        self._session = self._config.webhooks.session

        self._door_lookup = door_lookup
        self._person_lookup = person_lookup

    def card_scanned(self, card_scan: CardScan) -> None:
        # If it's one of our doors, the door lookup will have it. Otherwise, it wasn't at one of our doors and we don't
        # care
        door: Optional[Door] = self._door_lookup.by_card_scan(card_scan)
        if door is None:
            return

        access_granted: bool = card_scan.event_type == CardScanEventType.ACCESS_GRANTED
        person: Person = self._person_lookup.by_id(card_scan.name_id)

        if access_granted:
            self._logger.info(f"ACCESS GRANTED Loc={door.location_id} Door={door.device_id} Name=`{door.name}`")
        else:
            self._logger.info(f"ACCESS DENIED Loc={door.location_id} Door={door.device_id} Name=`{door.name}`")

        url = f"{self._api_base}/events/card_scanned"
        self._logger.info(url)
        response = self._session.post(url, json={
            "first_name": person.first_name,
            "last_name": person.last_name,
            "card_num": card_scan.card_number,
            "scan_time": card_scan.scan_time.isoformat(),
            "access_allowed": access_granted,
            "device": door.device_id,
        })

        if response.ok:
            return
        else:
            self._logger.info(f"card scanned response from API server was {response.status_code} which is not ok!")
            raise Exception(f"Submit status returned {response.status_code}")
