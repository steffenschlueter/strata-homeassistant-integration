"""Base entity for Strata."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import StrataCoordinator


class StrataEntity(CoordinatorEntity[StrataCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: StrataCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        engine = (coordinator.data or {}).get("engine") or {}
        static = (coordinator.data or {}).get("hardware_static") or {}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name="Strata",
            manufacturer="Strata",
            model=engine.get("model"),
            sw_version=engine.get("version"),
            hw_version=static.get("gpu_name"),
            entry_type=DeviceEntryType.SERVICE,
            configuration_url=coordinator.client.url,
        )
