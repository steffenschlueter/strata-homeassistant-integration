"""Polling coordinator for Strata."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_SSL
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import StrataAuthError, StrataClient, StrataError
from .const import CONF_VERIFY_SSL, DEFAULT_SCAN_INTERVAL, DOMAIN, LOGGER

def build_url(data: dict[str, Any]) -> str:
    """http(s)://host[:port] from the entry data. No port: the scheme's default (a reverse proxy on 80/443)."""
    host = str(data[CONF_HOST]).strip()
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"  # IPv6
    port = data.get(CONF_PORT)
    return f"{'https' if data.get(CONF_SSL) else 'http'}://{host}" + (f":{int(port)}" if port else "")


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
        verify = entry.data.get(CONF_VERIFY_SSL, True)
        self.client = StrataClient(
            async_get_clientsession(hass, verify_ssl=verify),
            build_url(entry.data), entry.data.get(CONF_API_KEY), verify,
        )

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.client.metrics()
        except StrataAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except StrataError as err:
            raise UpdateFailed(str(err)) from err
