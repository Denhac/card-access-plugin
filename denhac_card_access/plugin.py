import threading
from typing import NewType

from card_automation_server.plugins.error_handling import ErrorHandler, SentryErrorHandler
from card_automation_server.plugins.setup import AutoDiscoverPlugins, HasErrorHandler
from ioc import Resolver

from denhac_card_access.config import Config

CardSyncMutex = NewType('CardSyncMutex', threading.Lock)


class LoadDenhacPlugin(HasErrorHandler, AutoDiscoverPlugins):
    def __init__(self, resolver: Resolver):
        self._resolver = resolver
        super().__init__(resolver)
        self._config = self._resolver.singleton(Config)

        # The plugin loader doesn't need the result, but we must make sure it's a singleton for it to work.
        self._resolver.singleton(CardSyncMutex)

    def error_handler(self) -> ErrorHandler:
        if self._config.sentry.dsn is None:
            raise Exception("Denhac Config did not have sentry dsn")

        return SentryErrorHandler(self._config.sentry.dsn)
