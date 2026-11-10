"""Binary sensors for Strata."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.core import HomeAssistant

from . import metrics as m
from .coordinator import StrataConfigEntry, StrataCoordinator
from .entity import AddConfigEntryEntitiesCallback, StrataEntity


@dataclass(frozen=True, kw_only=True)
class StrataBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[m.Data], bool | None]


BINARY_SENSORS: tuple[StrataBinaryDescription, ...] = (
    StrataBinaryDescription(
        key="model_loaded", translation_key="model_loaded", icon="mdi:brain",
        value_fn=m.model_loaded,
    ),
    StrataBinaryDescription(
        key="busy", translation_key="busy", device_class=BinarySensorDeviceClass.RUNNING,
        value_fn=m.busy,
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
