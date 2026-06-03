from datetime import datetime, timedelta
from typing import TypedDict, Literal, Optional, Tuple

from card_automation_server.plugins.interfaces import PluginLoop, PluginCardDataPushed
from card_automation_server.windsx.lookup.access_card import AccessCard

from denhac_card_access.card_update_helper import CardUpdateHelper, CardSetting
from denhac_card_access.config import Config
from denhac_card_access.plugin import CardSyncMutex


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
                 card_update_helper: CardUpdateHelper,
                 card_sync_mutex: CardSyncMutex
                 ):
        self._config = config
        self._logger = config.logger
        self._card_sync_mutex = card_sync_mutex

        if self._config.slack.webhook_url is None:
            raise Exception("Slack webhook url cannot be None")
        if self._config.webhooks.base_url is None:
            raise Exception("Webhooks base url cannot be None")
        self._api_base = self._config.webhooks.base_url

        self._card_update_helper = card_update_helper
        self._card_update_helper.register(self._mark_complete)

        self._known_requests: set[int] = set()
        self._name_card_to_request: dict[Tuple[int, int], int] = {}

    def loop(self) -> Optional[int]:
        with self._card_sync_mutex:
            self._loop_locked()

        return int(timedelta(minutes=1).total_seconds())

    def _loop_locked(self):
        for command in self._get_commands():
            try:
                self._maybe_handle_request(command)
            finally:
                self._known_requests.add(command["id"])

    def _get_commands(self) -> list[_CardCommand]:
        response = self._config.webhooks.session.get(f"{self._api_base}/card_updates")

        response.raise_for_status()
        json_response = response.json()

        if "data" not in json_response:
            return []

        return json_response["data"]

    def _maybe_handle_request(self, command: _CardCommand):
        update_id = command["id"]
        if update_id in self._known_requests:
            return

        self._logger.info(f"Processing update {update_id}")

        setting = CardSetting(
            card=int(command['card']),
            first_name=command['first_name'],
            last_name=command['last_name'],
            company=command['company'],
            customer_id=command['woo_id'],
            enable_denhac=command['method'] == "enable"
        )

        item = int(setting.customer_id), int(setting.card)
        self._name_card_to_request[item] = update_id

        self._card_update_helper.handle(setting)

    def card_data_pushed(self, access_card: AccessCard) -> None:
        self._card_update_helper.card_updated(access_card)

    def _mark_complete(self, setting: CardSetting) -> None:
        item = int(setting.customer_id), int(setting.card)
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
