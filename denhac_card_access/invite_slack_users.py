import time
from collections import Counter
from datetime import datetime, timedelta

from card_automation_server.plugins.interfaces import PluginLoop

from denhac_card_access.config import Config


class InviteSlackUsers(PluginLoop):
    _time_between_same_invite: timedelta = timedelta(minutes=5)

    def __init__(self,
                 config: Config
                 ):
        self._config = config
        self._logger = config.logger

        if self._config.webhooks.base_url is None:
            raise Exception("Webhooks base url cannot be None")
        self._api_base = self._config.webhooks.base_url

        # Key is email
        self._failed_invite_count: Counter = Counter()
        self._invite_time: dict[str, datetime] = {}

    def loop(self) -> int:
        now = datetime.now()
        for invite in self._get_invites():
            email = invite['email']

            if self._handle_existing_user(email):
                continue

            if email in self._invite_time:
                next_time = self._invite_time[email] + self._time_between_same_invite
                if next_time > now:
                    continue  # Not time to retry yet

            channels = invite['channels']
            invite_type = invite['type']

            try:
                self._logger.info(f"[Slack] Inviting user for {email}")
                if self._config.slack.invite_user(email, invite_type, channels):
                    # We probably don't need the sleep here, but it gives the systems a chance to figure themselves out
                    # Worst case, we can't find the user and the next loop should find it.
                    time.sleep(1)
                    self._handle_existing_user(email)
            except Exception as ex:
                self._invite_time[email] = now + self._time_between_same_invite
                self._failed_invite_count[email] += 1

                if self._failed_invite_count[email] == 100:
                    raise ex

        return int(timedelta(minutes=1).total_seconds())

    def _get_invites(self):
        response = self._config.webhooks.session.get(f"{self._api_base}/slack/invites")

        response.raise_for_status()

        return response.json()

    def _handle_existing_user(self, email: str) -> bool:
        # Let's first try to find the slack id by email
        slack_user_id = self._config.slack.user_id_by_email(email)

        if slack_user_id is None:
            return False

        self._logger.info(f"[Slack] Find existing user for {email}")

        response = self._config.webhooks.session.post(
            f"{self._api_base}/slack/invites",
            json={
                'email': email,
                'slack_id': slack_user_id,
            }
        )

        response.raise_for_status()

        self._cleanup_failed_invites(email)

        return True

    def _cleanup_failed_invites(self, email: str):
        if email in self._time_between_same_invite:
            del self._time_between_same_invite

        if email in self._failed_invite_count:
            del self._failed_invite_count
