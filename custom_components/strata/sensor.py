"""Sensors for Strata: the KPIs of the web app's Monitor tab."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    EntityCategory,
    UnitOfDataRate,
    UnitOfInformation,
    UnitOfPower,
    UnitOfTemperature,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant

from . import metrics as m
from .const import REQUEST_FIELDS
from .coordinator import StrataConfigEntry, StrataCoordinator
from .entity import AddConfigEntryEntitiesCallback, StrataEntity

TOKENS = "tokens"
TOK_S = "tok/s"


@dataclass(frozen=True, kw_only=True)
class StrataSensorDescription(SensorEntityDescription):
    value_fn: Callable[[m.Data], Any]
    attrs_fn: Callable[[m.Data], dict[str, Any]] | None = None


SENSORS: tuple[StrataSensorDescription, ...] = (
    # --- model state -------------------------------------------------------------------------------
    StrataSensorDescription(
        key="state", translation_key="state", device_class=SensorDeviceClass.ENUM,
        options=m.STATES,
        value_fn=m.state,
        attrs_fn=lambda d: {k: m.live(d).get(k) for k in
                            ("phase", "queued", "prompt_read", "prompt_total", "generated", "max_tokens", "elapsed_s")},
    ),
    StrataSensorDescription(
        key="queued", translation_key="queued", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: m.live(d).get("queued"),
    ),
    # --- speed -------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="decode_speed", translation_key="decode_speed", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:speedometer",
        value_fn=m.decode_speed,
    ),
    StrataSensorDescription(
        key="prefill_speed", translation_key="prefill_speed", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:speedometer-medium",
        value_fn=m.prefill_speed,
    ),
    StrataSensorDescription(
        key="decode_speed_avg", translation_key="decode_speed_avg", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:speedometer",
        value_fn=m.decode_speed_avg,
    ),
    StrataSensorDescription(
        key="prefill_speed_avg", translation_key="prefill_speed_avg", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:speedometer-medium",
        value_fn=m.prefill_speed_avg,
    ),
    # --- GPU ---------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="gpu_load", translation_key="gpu_load", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:expansion-card",
        value_fn=m.hw_value("gpu_util"),
    ),
    StrataSensorDescription(
        key="vram_used", translation_key="vram_used", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:memory",
        value_fn=lambda d: m.hardware(d).get("gpu_mem_used"),
        attrs_fn=lambda d: {"total_bytes": m.hardware(d).get("gpu_mem_total")},
    ),
    StrataSensorDescription(
        key="gpu_temperature", translation_key="gpu_temperature", device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=m.hw_value("gpu_temp"),
    ),
    StrataSensorDescription(
        key="gpu_power", translation_key="gpu_power", device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=m.hw_value("gpu_power"),
        attrs_fn=lambda d: {"power_limit_w": m.hardware(d).get("gpu_power_limit")},
    ),
    StrataSensorDescription(
        key="pcie_link", translation_key="pcie_link", icon="mdi:expansion-card-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=m.pcie_link,
        attrs_fn=lambda d: {"current_gen": m.hardware(d).get("gpu_pcie_gen")},
    ),
    StrataSensorDescription(
        key="pcie_rx", translation_key="pcie_rx", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, entity_registry_enabled_default=False,
        value_fn=m.hw_value("gpu_pcie_rx_mb", 2),
    ),
    # --- host --------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="cpu", translation_key="cpu", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:cpu-64-bit",
        value_fn=m.hw_value("cpu"),
    ),
    StrataSensorDescription(
        key="ram_used", translation_key="ram_used", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:memory",
        value_fn=lambda d: m.hardware(d).get("ram_used"),
        attrs_fn=lambda d: {"total_bytes": m.hardware(d).get("ram_total")},
    ),
    StrataSensorDescription(
        key="disk_read", translation_key="disk_read", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=m.hw_value("disk_read_mb", 2),
    ),
    StrataSensorDescription(
        key="disk_write", translation_key="disk_write", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=m.hw_value("disk_write_mb", 2),
    ),
    # --- context / experts -------------------------------------------------------------------------
    StrataSensorDescription(
        key="context_used", translation_key="context_used", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:text-box-outline",
        value_fn=m.context_used,
    ),
    StrataSensorDescription(
        key="context_fill", translation_key="context_fill", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:gauge",
        value_fn=m.context_fill,
    ),
    StrataSensorDescription(
        key="max_context", translation_key="max_context", native_unit_of_measurement=TOKENS,
        entity_category=EntityCategory.DIAGNOSTIC, icon="mdi:text-box-multiple-outline",
        value_fn=lambda d: m.engine(d).get("max_context"),
    ),
    StrataSensorDescription(
        key="experts_cached", translation_key="experts_cached", state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:layers-triple",
        value_fn=lambda d: m.engine(d).get("expert_slots"),
    ),
    StrataSensorDescription(
        key="expert_cache_size", translation_key="expert_cache_size", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=m.expert_cache_bytes,
    ),
    StrataSensorDescription(
        key="model", translation_key="model", entity_category=EntityCategory.DIAGNOSTIC, icon="mdi:brain",
        value_fn=lambda d: m.engine(d).get("model"),
        attrs_fn=lambda d: {"images": m.engine(d).get("images")},
    ),
    # --- last request ------------------------------------------------------------------------------
    StrataSensorDescription(
        key="last_prompt_tokens", translation_key="last_prompt_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:import",
        value_fn=m.last_value("prompt_tokens"),
        attrs_fn=lambda d: {"reused": (m.last_request(d) or {}).get("reused")},
    ),
    StrataSensorDescription(
        key="last_output_tokens", translation_key="last_output_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:export",
        value_fn=m.last_value("output_tokens"),
        attrs_fn=lambda d: {"finish": (m.last_request(d) or {}).get("finish")},
    ),
    StrataSensorDescription(
        key="last_duration", translation_key="last_duration", device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=m.last_value("duration_s"),
    ),
    StrataSensorDescription(
        key="last_vram_hit_rate", translation_key="last_vram_hit_rate", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:target",
        value_fn=m.last_value("hit_rate", 100, 1),
        attrs_fn=lambda d: {"pcie_share_pct": m.last_value("pcie_share", 100, 1)(d)},
    ),
    # --- totals since server start (reset on restart: total_increasing handles that) ---------------
    StrataSensorDescription(
        key="requests_total", translation_key="requests_total", state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: m.totals(d).get("requests"),
    ),
    StrataSensorDescription(
        key="prompt_tokens_read", translation_key="prompt_tokens_read", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:import",
        value_fn=m.prompt_tokens_read,
    ),
    StrataSensorDescription(
        key="prompt_tokens_reused", translation_key="prompt_tokens_reused", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:recycle",
        value_fn=lambda d: m.totals(d).get("reused"),
    ),
    StrataSensorDescription(
        key="output_tokens", translation_key="output_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:export",
        value_fn=lambda d: m.totals(d).get("output_tokens"),
    ),
)


async def async_setup_entry(hass: HomeAssistant, entry: StrataConfigEntry,
                            async_add_entities: AddConfigEntryEntitiesCallback) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [StrataSensor(coordinator, desc) for desc in SENSORS]
    entities.append(StrataMonitorSensor(coordinator))
    async_add_entities(entities)


class StrataSensor(StrataEntity, SensorEntity):
    entity_description: StrataSensorDescription

    def __init__(self, coordinator: StrataCoordinator, description: StrataSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        return self.entity_description.value_fn(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        fn = self.entity_description.attrs_fn
        return fn(self.coordinator.data or {}) if fn else None


_MONITOR_ATTRS = frozenset({
    "engine", "live", "hardware", "hardware_static", "history", "requests", "requests_kept", "totals",
    "server_time",
})


class StrataMonitorSensor(StrataEntity, SensorEntity):
    """Feeds the Strata card: the /metrics snapshot as attributes (never written to the recorder)."""

    _attr_translation_key = "monitor"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:monitor-dashboard"
    _unrecorded_attributes = _MONITOR_ATTRS

    def __init__(self, coordinator: StrataCoordinator) -> None:
        super().__init__(coordinator, "monitor")

    @property
    def native_value(self) -> Any:
        return m.state(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        eng = m.engine(d)
        return {
            "engine": {
                "model": eng.get("model"),
                "max_context": eng.get("max_context"),
                "expert_slots": eng.get("expert_slots"),
                "expert_cache_mib": m.expert_cache_mib(d),
            },
            "live": m.live(d),
            "hardware": m.hardware(d),
            "hardware_static": d.get("hardware_static") or {},
            "history": d.get("history") or {},
            "requests": [{k: r.get(k) for k in REQUEST_FIELDS} for r in (d.get("requests") or [])],
            "requests_kept": d.get("requests_kept"),
            "totals": m.totals(d),
            "server_time": d.get("time"),
        }
