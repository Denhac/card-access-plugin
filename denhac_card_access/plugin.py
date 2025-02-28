from card_automation_server.ioc import Resolver
from card_automation_server.plugins.error_handling import ErrorHandler, SentryErrorHandler
from card_automation_server.plugins.setup import AutoDiscoverPlugins, HasErrorHandler

from denhac_card_access.config import Config


class LoadDenhacPlugin(HasErrorHandler, AutoDiscoverPlugins):
    def __init__(self, resolver: Resolver):
        self._resolver = resolver
        super().__init__(resolver)
        self._config = self._resolver.singleton(Config)

    def error_handler(self) -> ErrorHandler:
        if self._config.sentry.dsn is None:
            raise Exception("Denhac Config did not have sentry dsn")

        return SentryErrorHandler(self._config.sentry.dsn)