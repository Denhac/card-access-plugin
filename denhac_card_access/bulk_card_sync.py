import uuid
from datetime import timedelta
from typing import Optional

from card_automation_server.plugins.interfaces import PluginLoop, PluginCardDataPushed
from card_automation_server.windsx.lookup.access_card import AccessCard
from card_automation_server.windsx.lookup.person import PersonLookup

from denhac_card_access.card_update_helper import CardUpdateHelper, CardSetting
from denhac_card_access.config import Config


class BulkCardSync(PluginLoop, PluginCardDataPushed):
    def __init__(self,
                 config: Config,
                 card_update_helper: CardUpdateHelper,
                 person_lookup: PersonLookup):
        self._config = config
        self._logger = config.logger
        self._card_update_helper = card_update_helper
        self._person_lookup = person_lookup

    def loop(self) -> int:
        all_settings: list[CardSetting] = []
        can_open_house_ids: set[int] = set()

        url: Optional[str] = f"{self._config.webhooks.base_url}/all_cards"
        while url is not None:
            response = self._config.webhooks.session.get(url)
            response.raise_for_status()
            data = response.json()

            for person_data in data["data"]:
                customer_id = person_data["id"]

                if self._config.udf_key_can_open_house in person_data.get("extra", []):
                    can_open_house_ids.add(customer_id)

                for card_data in person_data["cards"]:
                    access = card_data["access"]
                    all_settings.append(CardSetting(
                        card=int(card_data["card_num"]),
                        first_name=person_data["first_name"],
                        last_name=person_data["last_name"],
                        company=person_data["company"],
                        customer_id=customer_id,
                        enable_denhac=self._config.denhac_access in access,
                        enable_server_room=self._config.server_room_access in access,
                    ))

            url = data.get("next_page_url")

        self._card_update_helper.handle(*all_settings)
        self._update_can_open_house(can_open_house_ids)

        return int(timedelta(hours=6).total_seconds())

    def card_data_pushed(self, access_card: AccessCard) -> None:
        self._card_update_helper.card_updated(access_card)

    def _update_can_open_house(self, can_open_house_ids: set[int]) -> None:
        should_have_uuids = {
            str(uuid.uuid5(uuid.NAMESPACE_OID, str(cid)))
            for cid in can_open_house_ids
        }

        for cid in can_open_house_ids:
            cid_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, str(cid)))
            people = self._person_lookup.by_udf(self._config.udf_key_denhac_id, cid_uuid).find()
            if not people:
                continue
            person = people[0]
            if person.user_defined_fields.get(self._config.udf_key_can_open_house) != "True":
                person.user_defined_fields[self._config.udf_key_can_open_house] = "True"
                person.write()
                self._config.slack.emit(
                    f"Allowing {person.first_name} {person.last_name} to initiate open house mode"
                )

        people_with_udf = self._person_lookup.by_udf(self._config.udf_key_can_open_house).find()
        for person in people_with_udf:
            denhac_uuid = person.user_defined_fields.get(self._config.udf_key_denhac_id)
            if denhac_uuid not in should_have_uuids:
                del person.user_defined_fields[self._config.udf_key_can_open_house]
                person.write()
                self._config.slack.emit(
                    f"Removing ability for {person.first_name} {person.last_name} to issue open house mode"
                )
