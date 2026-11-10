"""Polling coordinator for Strata."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import StrataAuthError, StrataClient, StrataError, build_url
from .const import CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER


def entry_url(data: Mapping[str, Any]) -> str:
    return build_url(str(data[CONF_HOST]), data.get(CONF_PORT), bool(data.get(CONF_SSL)))


def create_client(hass: HomeAssistant, data: Mapping[str, Any]) -> StrataClient:
    """A client for config entry data (or the config flow's parsed input)."""
    verify = data.get(CONF_VERIFY_SSL, True)
    return StrataClient(async_get_clientsession(hass, verify_ssl=verify), entry_url(data),
                        data.get(CONF_API_KEY), verify)


type StrataConfigEntry = ConfigEntry[StrataCoordinator]


class StrataCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Fetches /metrics on an interval."""

    config_entry: StrataConfigEntry

    def __init__(self, hass: HomeAssistant, entry: StrataConfigEntry) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass, LOGGER, config_entry=entry, name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = create_client(hass, entry.data)

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.metrics()
        except StrataAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except StrataError as err:
            raise UpdateFailed(str(err)) from err
