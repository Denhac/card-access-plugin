import uuid
from collections import Counter
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

    def handle(self, *settings: CardSetting) -> None:
        card_counts = Counter(s.card for s in settings)
        duplicate_cards = {card for card, count in card_counts.items() if count > 1}
        for card_num in duplicate_cards:
            self._logger.error(
                f"Card number {card_num} appears more than once in the same handle call, skipping"
            )

        valid_settings = [s for s in settings if s.card not in duplicate_cards]

        if not valid_settings:
            return

        unique_customer_ids = {s.customer_id for s in valid_settings}
        uuid_by_customer_id = {
            cid: str(uuid.uuid5(uuid.NAMESPACE_OID, str(cid)))
            for cid in unique_customer_ids
        }
        uuid_to_customer_id = {v: k for k, v in uuid_by_customer_id.items()}

        card_numbers = [s.card for s in valid_settings]
        existing_cards: dict[int, AccessCard] = {
            card.card_number: card
            for card in self._access_card_lookup.with_people().by_card_numbers(*card_numbers)
        }

        # Build person map from eager-loaded card people where possible
        person_by_customer_id: dict[int, Person] = {}
        for card in existing_cards.values():
            udf_value = card.person.user_defined_fields.get(self._config.udf_key_denhac_id)
            if udf_value not in uuid_to_customer_id:
                continue

            customer_id = uuid_to_customer_id[udf_value]
            if customer_id not in person_by_customer_id:
                person_by_customer_id[customer_id] = card.person

        # UDF lookup only for customer_ids not found via eager load
        for customer_id in unique_customer_ids:
            if customer_id in person_by_customer_id:
                continue

            customer_uuid = uuid_by_customer_id[customer_id]
            setting_for_person = next(s for s in valid_settings if s.customer_id == customer_id)
            people = self._person_lookup.by_udf(self._config.udf_key_denhac_id, customer_uuid).find()

            if len(people) == 0:
                person = self._person_lookup.new()
                person.first_name = setting_for_person.first_name
                person.last_name = setting_for_person.last_name
                person.company_id = self._config.company_id
                person.user_defined_fields[self._config.udf_key_denhac_id] = customer_uuid
                person.write()
                self._logger.info(f"Created person {person.id}: {person.first_name} {person.last_name}")
            else:
                person = people[0]
                self._logger.info(f"Found person {person.id}: {person.first_name} {person.last_name}")

            person_by_customer_id[customer_id] = person

        for setting in valid_settings:
            person = person_by_customer_id[setting.customer_id]
            card_number = setting.card

            updates: set[str] = set()

            if card_number in existing_cards:
                card = existing_cards[card_number]
                if card.name_id != person.id:
                    updates.add("Changing owner")
            else:
                card = self._access_card_lookup.new(card_number)

            card.person = person

            if self._update_access(card, self._config.denhac_access, setting.enable_denhac):
                updates.add(("Adding" if setting.enable_denhac else "Removing") + " denhac")

            if self._update_access(card, self._config.server_room_access, setting.enable_server_room):
                updates.add(("Adding" if setting.enable_server_room else "Removing") + " server room")

            # denhac cards should not also get main building access
            if self._update_access(card, self._config.main_building_access, False):
                updates.add("Removing extra MBD")

            self._pending_settings.add(setting)

            if len(updates):
                update_msg = self._join_with_and(list(updates))
                self._config.slack.emit(
                    f"Updating card {setting.card} for {setting.first_name} {setting.last_name}: {update_msg}"
                )
                self._logger.info(f"Writing Card {setting.card}")
                card.write()
            else:
                self.card_updated(card, send_notice=False)

    def _update_access(self, card: AccessCard, access: str, should_be_active: bool) -> bool:
        has_access = access in card.access
        if should_be_active and not has_access:
            self._logger.info(f"Adding `{access}` access level to {card.card_number}")
            card.with_access(access)
            return True

        if not should_be_active and has_access:
            self._logger.info(f"Removing `{access}` from {card.card_number}")
            card.without_access(access)
            return True

        return False

    @staticmethod
    def _join_with_and(items):
        if len(items) <= 1:
            return "".join(items)
        return ", ".join(items[:-1]) + " and " + items[-1]

    def card_updated(self, access_card: AccessCard, send_notice: bool = True) -> None:
        person = access_card.person
        known_settings = [
            s for s in self._pending_settings
            if s.card == access_card.card_number
        ]
        if len(known_settings) == 0:
            return

        setting = known_settings.pop()

        if send_notice:
            self._config.slack.emit(
                f"Card {access_card.card_number} updated for {person.first_name} {person.last_name}"
            )

        for cb in self._callbacks:
            cb(setting)
