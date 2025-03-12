import uuid
from datetime import datetime
from typing import TypedDict, Literal, Optional

from card_automation_server.plugins.interfaces import PluginLoop, PluginCardDataPushed
from card_automation_server.windsx.lookup.access_card import AccessCardLookup, AccessCard
from card_automation_server.windsx.lookup.person import PersonLookup, Person

from denhac_card_access.config import Config


class _CardCommand(TypedDict):
    id: int
    method: Literal["enable", "disable", "unknown"]
    card: int
    company: str
    woo_id: int
    created_at: datetime
    first_name: str
    last_name: str


class ProcessPiecemealUpdate(PluginLoop, PluginCardDataPushed):
    def __init__(self,
                 config: Config,
                 person_lookup: PersonLookup,
                 access_card_lookup: AccessCardLookup
                 ):
        self._config = config
        self._logger = config.logger

        if self._config.slack.webhook_url is None:
            raise Exception("Slack webhook url cannot be None")
        if self._config.webhooks.base_url is None:
            raise Exception("Webhooks base url cannot be None")
        self._api_base = self._config.webhooks.base_url

        self._person_lookup = person_lookup
        self._access_card_lookup = access_card_lookup
        self._known_requests: set[int] = set()
        self._name_card_to_request: dict[(int, int), int] = {}

    def loop(self) -> Optional[int]:
        for command in self._get_commands():
            try:
                self._maybe_handle_request(command)
            finally:
                self._known_requests.add(command["id"])

        return 60

    def _maybe_handle_request(self, command: _CardCommand):
        update_id = command["id"]
        if update_id in self._known_requests:
            return

        self._logger.info(f"Processing update {update_id}")

        customer_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, str(command["woo_id"])))

        people = self._person_lookup.by_udf(self._config.udf_key_denhac_id, customer_uuid).find()

        person: Person
        if len(people) == 0:
            person = self._person_lookup.new()
            person.first_name = command["first_name"]
            person.last_name = command["last_name"]
            person.company_id = self._config.company_id
            person.user_defined_fields[self._config.udf_key_denhac_id] = customer_uuid
            person.write()
            self._logger.info(f"Created person {person.id}: {person.first_name} {person.last_name}")
        else:
            person = people[0]
            self._logger.info(f"Found person {person.id}: {person.first_name} {person.last_name}")

        # We've got the person now. Time for the card

        card = self._access_card_lookup.by_card_number(command["card"])
        card.person = person

        activating_or_deactivating: str

        anything_updated = False

        if command["method"] == "enable":
            activating_or_deactivating = "Activating"
            if not card.active or self._config.denhac_access not in card.access:
                self._logger.info(f"Adding `{self._config.denhac_access}` access level to {card.card_number}")
                card.with_access(self._config.denhac_access)
                anything_updated = True
        elif command["method"] == "disable":
            activating_or_deactivating = "Deactivating"
            # A member could have any of these. We're de-activating their entire card for anything we might control.
            to_remove = [
                self._config.denhac_access,
                self._config.server_room_access,
                self._config.main_building_access,
            ]

            for access in to_remove:
                if access not in card.access:
                    continue

                self._logger.info(f"Removing `{access}` from {card.card_number}")
                card.without_access(access)
                anything_updated = True
        else:
            raise Exception(f"Unknown update method for {update_id}")

        self._config.slack.emit(
            f"{activating_or_deactivating} card {command['card']} for {command['first_name']} {command['last_name']}"
        )
        item = person.id, int(card.card_number)

        self._logger.info(f"Setting update {update_id} to `{person.id}` and `{card.card_number}`: {item}")
        self._name_card_to_request[item] = update_id

        if anything_updated:
            self._logger.info("Writing Card")
            card.write()
        else:
            self._mark_complete(card)

    def _get_commands(self) -> list[_CardCommand]:
        response = self._config.webhooks.session.get(f"{self._api_base}/card_updates")

        response.raise_for_status()
        json_response = response.json()

        if "data" not in json_response:
            return []

        return json_response["data"]

    def card_data_pushed(self, access_card: AccessCard) -> None:
        self._mark_complete(access_card)

    def _mark_complete(self, access_card: AccessCard) -> None:
        person = access_card.person
        item = person.id, access_card.card_number
        self._logger.info(f"Update was for `{person.id}` and `{access_card.card_number}`: {item}")

        if item not in self._name_card_to_request:
            self._logger.info("Could not find update")
            return  # We didn't submit this request or have forgotten about it. Don't notify anyone

        activated_or_deactivated = "activated" if self._config.denhac_access in access_card.access else "deactivated"

        self._config.slack.emit(
            f"Card {access_card.card_number} {activated_or_deactivated} for {person.first_name} {person.last_name}"
        )

        update_id = self._name_card_to_request[item]

        self._logger.info(f"Processed update {update_id}")
        del self._name_card_to_request[item]
        if update_id in self._known_requests:
            self._known_requests.remove(update_id)

        self._submit_status(update_id, "success")

    def _submit_status(self, update_id: int, status: str):
        url = f"{self._api_base}/card_updates/{update_id}/status"
        response = self._config.webhooks.session.post(url, json={
            "status": status
        })

        response.raise_for_status()
