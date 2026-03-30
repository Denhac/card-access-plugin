import uuid
from dataclasses import dataclass, field
from typing import Callable

from card_automation_server.windsx.lookup.access_card import AccessCardLookup, AccessCard
from card_automation_server.windsx.lookup.person import PersonLookup, Person

from denhac_card_access.config import Config


@dataclass(frozen=True)
class CardSetting:
    card: int
    first_name: str
    last_name: str
    company: str
    customer_id: int
    enable_denhac: bool = field(default=False)
    enable_server_room: bool = field(default=False)
    can_open_house: bool = field(default=False)


Callback = Callable[[CardSetting], None]


class CardUpdateHelper:
    def __init__(self,
                 config: Config,
                 person_lookup: PersonLookup,
                 access_card_lookup: AccessCardLookup):
        self._config = config
        self._logger = config.logger
        if self._config.slack.webhook_url is None:
            raise Exception("Slack webhook url cannot be None")

        self._person_lookup = person_lookup
        self._access_card_lookup = access_card_lookup

        self._callbacks: set[Callback] = set()
        self._pending_settings: set[CardSetting] = set()

    def register(self, cb: Callback) -> None:
        self._callbacks.add(cb)

    def handle(self, setting: CardSetting) -> None:
        customer_uuid = str(uuid.uuid5(uuid.NAMESPACE_OID, str(setting.customer_id)))

        people = self._person_lookup.by_udf(self._config.udf_key_denhac_id, customer_uuid).find()

        person: Person
        if len(people) == 0:
            person = self._person_lookup.new()
            person.first_name = setting.first_name
            person.last_name = setting.last_name
            person.company_id = self._config.company_id
            person.user_defined_fields[self._config.udf_key_denhac_id] = customer_uuid
            person.write()
            self._logger.info(f"Created person {person.id}: {person.first_name} {person.last_name}")
        else:
            person = people[0]
            self._logger.info(f"Found person {person.id}: {person.first_name} {person.last_name}")

        # We've got the person now. Time for the card

        card_number = setting.card
        card = self._access_card_lookup.by_card_number(card_number)
        if card is None:
            card = self._access_card_lookup.new(card_number)

        card.person = person

        updates: set[str] = set()
        if self._update_access(card, self._config.denhac_access, setting.enable_denhac):
            updates.add(("Adding" if setting.enable_denhac else "Removing") + " denhac")
        if self._update_access(card, self._config.server_room_access, setting.enable_server_room):
            updates.add(("Adding" if setting.enable_server_room else "Removing") + " server room")

        # denhac cards should not also get main building access
        if self._update_access(card, self._config.main_building_access, False):
            updates.add("Removing extra MBD")

        if self._update_udf(card, self._config.udf_key_can_open_house, setting.can_open_house):
            updates.add(("Adding" if setting.can_open_house else "Removing") + " open house")

        update_msg = self._join_with_and(list(updates))
        self._config.slack.emit(
            f"Updating card {setting.card} for {setting.first_name} {setting.last_name}: {update_msg}"
        )

        self._pending_settings.add(setting)

        if len(updates):
            self._logger.info("Writing Card")
            card.write()
        else:
            self._logger.info("Card already updated, marking as updated")
            self.card_updated(card)

    def _update_access(self, card: AccessCard, access: str, should_be_active: bool) -> bool:
        card_is_active = card.active and access in card.access
        if should_be_active and not card_is_active:
            self._logger.info(f"Adding `{access}` access level to {card.card_number}")
            card.with_access(access)
            return True

        if not should_be_active and card_is_active:
            self._logger.info(f"Removing `{access}` from {card.card_number}")
            card.without_access(access)
            return True

        return False

    def _update_udf(self, card: AccessCard, udf: str, should_be_active: bool) -> bool:
        person = card.person
        if udf in person.user_defined_fields and not should_be_active:
            self._logger.info(f"Removing `{udf}` udf")
            del person.user_defined_fields[udf]
            return True

        if udf not in person.user_defined_fields and should_be_active:
            self._logger.info(f"Adding `{udf}` udf")
            person.user_defined_fields[udf] = "True"
            return True

        return False

    @staticmethod
    def _join_with_and(items):
        if len(items) <= 1:
            return "".join(items)
        return ", ".join(items[:-1]) + " and " + items[-1]

    def card_updated(self, access_card: AccessCard) -> None:
        person = access_card.person
        known_settings = [
            s for s in self._pending_settings
            if s.card == access_card.card_number and s.customer_id == person.id
        ]
        if len(known_settings) == 0:
            self._logger.info(f"Could not find pending settings based on ({access_card.card_number}, {person.id})")
            return

        setting = known_settings.pop()

        self._config.slack.emit(
            f"Card {access_card.card_number} updated for {person.first_name} {person.last_name}"
        )

        for cb in self._callbacks:
            cb(setting)
