"""Binary sensors for Strata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .coordinator import StrataConfigEntry, StrataCoordinator
from .entity import StrataEntity


@dataclass(frozen=True, kw_only=True)
class StrataBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[dict[str, Any]], bool | None]


def _st(d: dict[str, Any]) -> str | None:
    return (d.get("live") or {}).get("state")


BINARY_SENSORS: tuple[StrataBinaryDescription, ...] = (
    StrataBinaryDescription(
        key="model_loaded", translation_key="model_loaded", icon="mdi:brain",
        value_fn=lambda d: None if _st(d) is None else _st(d) != "unloaded",
    ),
    StrataBinaryDescription(
        key="busy", translation_key="busy", device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=lambda d: None if _st(d) is None else
        (_st(d) in ("reading", "generating") or bool((d.get("live") or {}).get("queued"))),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: StrataConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    async_add_entities(StrataBinarySensor(entry.runtime_data, desc) for desc in BINARY_SENSORS)


class StrataBinarySensor(StrataEntity, BinarySensorEntity):
    entity_description: StrataBinaryDescription

    def __init__(self, coordinator: StrataCoordinator, description: StrataBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        return self.entity_description.value_fn(self.coordinator.data or {})
