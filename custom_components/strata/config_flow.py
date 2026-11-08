"""Config flow for Strata LLM: host (IP or domain), optional port, HTTPS, API key."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from yarl import URL

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SCAN_INTERVAL, CONF_SSL
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import StrataAuthError, StrataClient, StrataConnectionError
from .const import (
    CONF_VERIFY_SSL,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    LOGGER,
    MAX_SCAN_INTERVAL,
    MIN_SCAN_INTERVAL,
)
from .coordinator import build_url


class InvalidHost(Exception):
    """The host field could not be read."""


def parse_input(user_input: dict[str, Any]) -> dict[str, Any]:
    """Accepts '192.168.50.70', '192.168.50.70:8080', 'strata.example.net', 'https://strata.example.net/',
    with the port either in the host field or in the port field (the port field wins)."""
    raw = str(user_input.get(CONF_HOST) or "").strip()
    if not raw:
        raise InvalidHost
    ssl = bool(user_input.get(CONF_SSL, False))
    if "://" in raw:
        try:
            url = URL(raw)
        except ValueError as err:
            raise InvalidHost from err
        ssl = url.scheme == "https" or ssl
    else:
        try:
            url = URL(f"http://{raw}")
        except ValueError as err:
            raise InvalidHost from err
    host = url.host
    if not host or " " in host:
        raise InvalidHost
    port = user_input.get(CONF_PORT)
    port = int(port) if port not in (None, "") else url.explicit_port
    if port is not None and not 0 < port < 65536:
        raise InvalidHost
    return {
        CONF_HOST: host,
        CONF_PORT: port,
        CONF_SSL: ssl,
        CONF_VERIFY_SSL: bool(user_input.get(CONF_VERIFY_SSL, True)),
        CONF_API_KEY: (user_input.get(CONF_API_KEY) or "").strip() or None,
    }


def _unique_id(data: dict[str, Any]) -> str:
    port = data[CONF_PORT] or (443 if data[CONF_SSL] else 80)
    return f"{data[CONF_HOST].lower()}:{port}"


async def _validate(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Raise on failure; return /health."""
    verify = data[CONF_VERIFY_SSL]
    client = StrataClient(async_get_clientsession(hass, verify_ssl=verify), build_url(data),
                          data[CONF_API_KEY], verify)
    health = await client.health()
    if health.get("service") != "strata":
        raise StrataConnectionError("not a Strata server")
    await client.metrics()  # /metrics is key-protected; a wrong key shows here
    return health


def _schema(defaults: dict[str, Any], with_key: bool = True) -> vol.Schema:
    port = defaults.get(CONF_PORT)
    fields: dict[Any, Any] = {
        vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): TextSelector(),
        vol.Optional(CONF_PORT, description={"suggested_value": port} if port else None): NumberSelector(
            NumberSelectorConfig(min=1, max=65535, step=1, mode=NumberSelectorMode.BOX)
        ),
        vol.Optional(CONF_SSL, default=defaults.get(CONF_SSL, False)): bool,
        vol.Optional(CONF_VERIFY_SSL, default=defaults.get(CONF_VERIFY_SSL, True)): bool,
    }
    if with_key:
        fields[vol.Optional(CONF_API_KEY)] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
    return vol.Schema(fields)


async def _try(hass: HomeAssistant, user_input: dict[str, Any], errors: dict[str, str]) -> dict[str, Any] | None:
    try:
        data = parse_input(user_input)
    except InvalidHost:
        errors[CONF_HOST] = "invalid_host"
        return None
    try:
        await _validate(hass, data)
    except StrataAuthError:
        errors["base"] = "invalid_auth"
    except StrataConnectionError as err:
        LOGGER.debug("Strata validation failed for %s: %s", build_url(data), err)
        errors["base"] = "cannot_connect"
    except Exception:  # noqa: BLE001
        LOGGER.exception("Unexpected error validating Strata")
        errors["base"] = "unknown"
    else:
        return data
    return None


class StrataConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None and (data := await _try(self.hass, user_input, errors)):
            await self.async_set_unique_id(_unique_id(data))
            self._abort_if_unique_id_configured()
            return self.async_create_entry(title=f"Strata ({data[CONF_HOST]})", data=data)
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=errors)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Change host, port or HTTPS later; the API key stays unless a new one is entered."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            merged = {**user_input}
            if not (merged.get(CONF_API_KEY) or "").strip():
                merged[CONF_API_KEY] = entry.data.get(CONF_API_KEY)
            if data := await _try(self.hass, merged, errors):
                uid = _unique_id(data)
                if uid != entry.unique_id and any(
                    e.unique_id == uid for e in self._async_current_entries(include_ignore=False)
                ):
                    return self.async_abort(reason="already_configured")
                return self.async_update_reload_and_abort(
                    entry, unique_id=uid, title=f"Strata ({data[CONF_HOST]})", data=data,
                )
        return self.async_show_form(
            step_id="reconfigure", data_schema=_schema(user_input or dict(entry.data)), errors=errors,
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            data = {**entry.data, CONF_API_KEY: (user_input.get(CONF_API_KEY) or "").strip() or None}
            try:
                await _validate(self.hass, data)
            except StrataAuthError:
                errors["base"] = "invalid_auth"
            except StrataConnectionError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(entry, data_updates={CONF_API_KEY: data[CONF_API_KEY]})
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Optional(CONF_API_KEY): TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD)),
            }),
            errors=errors,
            description_placeholders={"url": build_url(entry.data)},
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return StrataOptionsFlow()


class StrataOptionsFlow(OptionsFlow):
    """Polling interval."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={CONF_SCAN_INTERVAL: int(user_input[CONF_SCAN_INTERVAL])})
        current = self.config_entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Required(CONF_SCAN_INTERVAL, default=current): NumberSelector(
                    NumberSelectorConfig(min=MIN_SCAN_INTERVAL, max=MAX_SCAN_INTERVAL, step=1,
                                         unit_of_measurement="s", mode=NumberSelectorMode.BOX)
                ),
            }),
        )
