import enum
import json
from datetime import time
from typing import Optional

import requests
import tomlkit
from card_automation_server.plugins.config import BaseConfig, ConfigHolder, ConfigProperty, TomlConfigType
from requests import Session
from requests.adapters import HTTPAdapter
from urllib3 import Retry


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
    door_ids: ConfigProperty[list[int]]


class _OpenHouseConfigs(ConfigHolder):
    def __init__(self,
                 config: TomlConfigType):
        super().__init__(config)

    def keys(self):
        return self._config.keys()

    def values(self):
        return [OpenHouseConfig(oh) for oh in self._config.values()]

    def items(self):
        result = {
            name: OpenHouseConfig(oh) for (name, oh) in self._config.items()
        }
        return result.items()

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
            raise Exception("Webhooks api key cannot be None")

        session = requests.Session()
        session.headers["Authorization"] = f"Bearer {self.api_key}"
        session.headers["Accept"] = "application/json"

        retries = Retry(total=50,
                        backoff_factor=0.1,
                        status_forcelist=[500, 502, 503, 504])

        session.mount('https://', HTTPAdapter(max_retries=retries))

        return session


class _SlackConfig(ConfigHolder):
    webhook_url: ConfigProperty[str]
    team_id: ConfigProperty[str]
    admin_token: ConfigProperty[str]
    management_token: ConfigProperty[str]

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

    def user_id_by_email(self, email: str) -> Optional[str]:
        if self.management_token is None:
            raise Exception("Slack management token cannot be None")

        response = requests.get(
            "https://denhac.slack.com/api/users.lookupByEmail",
            params={
                "email": email
            },
            headers={
                "Authorization": f"Bearer {self.management_token}"
            }
        )

        response.raise_for_status()

        data = response.json()
        if data["ok"]:
            return data["user"]["id"]

        if data["error"] == "users_not_found":
            return None

        raise Exception(f"Unknown error looking up invite for {email}: {data['error']}")

    def invite_user(self, email: str, invite_type: str, channels: list[str]):
        if self.team_id is None:
            raise Exception("Slack team id cannot be None")
        if self.admin_token is None:
            raise Exception("Slack admin token cannot be None")

        user_invite_data = {
            'email': email,
            'type': invite_type,
            'mode': 'manual',
        }

        response = requests.post(
            "https://denhac.slack.com/api/users.admin.inviteBulk",
            data={
                'token': self.admin_token,
                # This method only invites one user, the endpoint accepts an array
                'invites': json.dumps([user_invite_data]),
                'team_id': self.team_id,
                'restricted': invite_type == 'restricted',
                'ultra_restricted': invite_type == 'ultra_restricted',
                'campaign': 'team_site_admin',
                'channels': ','.join(channels),
                '_x_reason': 'submit-invite-to-workspace-invites',
                '_x_node': 'online',
            }
        )

        response.raise_for_status()

        data = response.json()
        if not data["ok"]:
            raise Exception(f"Got invalid response when inviting {email}: {data['error']}")

        return True


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
    def main_building_access(self) -> str:
        return "MBD Access"

    @property
    def company_id(self) -> int:
        return 14
