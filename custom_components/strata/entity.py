"""Base entity for Strata."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

try:  # Home Assistant 2025.3+
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
except ImportError:  # 2025.1 / 2025.2
    from homeassistant.helpers.entity_platform import (  # type: ignore[assignment]
        AddEntitiesCallback as AddConfigEntryEntitiesCallback,
    )

from . import metrics as m
from .const import DOMAIN
from .coordinator import StrataCoordinator

__all__ = ["AddConfigEntryEntitiesCallback", "StrataEntity"]


class StrataEntity(CoordinatorEntity[StrataCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: StrataCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry = coordinator.config_entry
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        data = coordinator.data or {}
        engine = m.engine(data)
        static = data.get("hardware_static") or {}
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
