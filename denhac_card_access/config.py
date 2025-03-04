import enum
from datetime import time

import requests
import tomlkit
from card_automation_server.plugins.config import BaseConfig, ConfigHolder, ConfigPath, ConfigProperty, TomlConfigType
from requests import Session


# Enum values match weekday() from datetime.weekday()
class Weekday(enum.IntEnum):
    Monday = 0
    Tuesday = 1
    Wednesday = 2
    Thursday = 3
    Friday = 4
    Saturday = 5
    Sunday = 6


class OpenHouseConfig(ConfigHolder):
    day_of_week: ConfigProperty[Weekday]
    scan_after_time: ConfigProperty[time]
    end_time: ConfigProperty[time]
    door_ids: list[int]


class _OpenHouseConfigs(ConfigHolder):
    def __init__(self,
                 config: TomlConfigType):
        super().__init__(config)

    def keys(self):
        return self._config.keys()

    def values(self):
        return self._config.values()

    def items(self):
        return self._config.items()

    def __len__(self):
        return len(self._config.items())

    def __getitem__(self, item: str) -> OpenHouseConfig:
        if item not in self._config:
            self._config[item] = tomlkit.table()

        return OpenHouseConfig(self._config[item])

    def __contains__(self, item: str) -> bool:
        return item in self._config

    def __repr__(self):
        return self._config.__repr__()


class _SentryConfig(ConfigHolder):
    dsn: ConfigProperty[str]


class _WebhookConfig(ConfigHolder):
    base_url: ConfigProperty[str]
    api_key: ConfigProperty[str]

    @property
    def session(self) -> Session:
        if self.api_key is None:
            raise Exception("Webhooks base url cannot be None")

        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {self.api_key}"
        session.headers["Accept"] = "application/json"

        # TODO Retry logic

        return session


class _SlackConfig(ConfigHolder):
    webhook_url: ConfigProperty[str]

    def emit(self, message: str) -> None:
        if self.webhook_url is None:
            raise Exception("Slack webhook url cannot be None")

        payload = {
            "blocks": [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"{message}"
                    }
                }
            ]
        }

        requests.post(self.webhook_url, json=payload)


class Config(BaseConfig):
    sentry: _SentryConfig
    webhooks: _WebhookConfig
    open_houses: _OpenHouseConfigs
    slack: _SlackConfig

    @property
    def udf_key_can_open_house(self) -> str:
        return 'dh_can_open_house'

    @property
    def udf_key_denhac_id(self) -> str:
        return 'DENHAC_ID'

    @property
    def denhac_access(self) -> str:
        return "denhac"

    @property
    def server_room_access(self) -> str:
        return "Server Room"

    @property
    def company_id(self) -> int:
        return 14
