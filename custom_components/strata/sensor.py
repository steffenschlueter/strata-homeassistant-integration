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
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from .const import REQUEST_FIELDS
from .coordinator import StrataConfigEntry, StrataCoordinator
from .entity import StrataEntity

TOKENS = "tokens"
TOK_S = "tok/s"
ACTIVE = ("reading", "generating")

Data = dict[str, Any]


def _live(d: Data) -> Data:
    return d.get("live") or {}


def _hw(d: Data) -> Data:
    return d.get("hardware") or {}


def _eng(d: Data) -> Data:
    return d.get("engine") or {}


def _tot(d: Data) -> Data:
    return d.get("totals") or {}


def _last(d: Data) -> Data | None:
    reqs = d.get("requests") or []
    return reqs[0] if reqs else None


def _state(d: Data) -> str | None:
    live = _live(d)
    if live.get("queued"):
        return "queued" if live.get("state") == "idle" else live.get("state")
    return live.get("state")


def _round(v: Any, n: int = 1) -> float | None:
    return round(float(v), n) if isinstance(v, (int, float)) else None


def _decode(d: Data) -> float | None:
    """Now while generating, else the last request (as the Monitor's 'Decode last request')."""
    live = _live(d)
    if live.get("state") == "generating" and live.get("tok_s") is not None:
        return _round(live["tok_s"])
    last = _last(d)
    return _round(last.get("decode_tok_s")) if last else None


def _prefill_of(r: Data | None) -> float | None:
    if not r or not r.get("prompt_ms"):
        return None
    fresh = max(0, (r.get("prompt_tokens") or 0) - (r.get("reused") or 0))
    return _round(fresh / (r["prompt_ms"] / 1000), 0) if fresh else None


def _prefill(d: Data) -> float | None:
    live = _live(d)
    if live.get("state") in ACTIVE and live.get("prefill_tok_s_mean") is not None:
        return _round(live["prefill_tok_s_mean"], 0)
    return _prefill_of(_last(d))


def _avg_decode(d: Data) -> float | None:
    t = _tot(d)
    return _round(t["output_tokens"] / (t["decode_ms"] / 1000)) if t.get("decode_ms") and t.get("output_tokens") else None


def _avg_prefill(d: Data) -> float | None:
    t = _tot(d)
    read = (t.get("prompt_tokens") or 0) - (t.get("reused") or 0)
    return _round(read / (t["prompt_ms"] / 1000), 0) if t.get("prompt_ms") and read > 0 else None


def _ctx_used(d: Data) -> int | None:
    live = _live(d)
    if live.get("state") in ACTIVE:
        return (live.get("prompt_tokens") or 0) + (live.get("generated") or 0)
    last = _last(d)
    return (last.get("prompt_tokens") or 0) + (last.get("output_tokens") or 0) if last else None


def _ctx_pct(d: Data) -> float | None:
    used, ctx = _ctx_used(d), _eng(d).get("max_context")
    return _round(min(100.0, 100 * used / ctx), 1) if used is not None and ctx else None


def _pcie_link(d: Data) -> str | None:
    hw = _hw(d)
    gen = hw.get("gpu_pcie_gen_max") or hw.get("gpu_pcie_gen")
    if not gen:
        return None
    return f"Gen{gen} x{hw['gpu_pcie_width']}" if hw.get("gpu_pcie_width") else f"Gen{gen}"


def _expert_cache_bytes(d: Data) -> int | None:
    eng = _eng(d)
    mib = eng.get("expert_cache_mib") or (eng.get("vram") or {}).get("expert_cache_mib")
    return int(mib * 2**20) if mib else None


def _last_field(key: str, scale: float = 1, nd: int | None = None) -> Callable[[Data], Any]:
    def fn(d: Data) -> Any:
        last = _last(d)
        v = last.get(key) if last else None
        if not isinstance(v, (int, float)):
            return None
        v = v * scale
        return round(v, nd) if nd is not None else v
    return fn


@dataclass(frozen=True, kw_only=True)
class StrataSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Data], Any]
    attrs_fn: Callable[[Data], dict[str, Any]] | None = None


SENSORS: tuple[StrataSensorDescription, ...] = (
    # --- model state -------------------------------------------------------------------------------
    StrataSensorDescription(
        key="state", translation_key="state", device_class=SensorDeviceClass.ENUM,
        options=["idle", "reading", "generating", "queued", "unloaded"],
        value_fn=_state,
        attrs_fn=lambda d: {k: _live(d).get(k) for k in
                            ("phase", "queued", "prompt_read", "prompt_total", "generated", "max_tokens", "elapsed_s")},
    ),
    StrataSensorDescription(
        key="queued", translation_key="queued", state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: _live(d).get("queued"),
    ),
    # --- speed -------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="decode_speed", translation_key="decode_speed", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:speedometer",
        value_fn=_decode,
    ),
    StrataSensorDescription(
        key="prefill_speed", translation_key="prefill_speed", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:speedometer-medium",
        value_fn=_prefill,
    ),
    StrataSensorDescription(
        key="decode_speed_avg", translation_key="decode_speed_avg", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:speedometer",
        value_fn=_avg_decode,
    ),
    StrataSensorDescription(
        key="prefill_speed_avg", translation_key="prefill_speed_avg", native_unit_of_measurement=TOK_S,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:speedometer-medium",
        value_fn=_avg_prefill,
    ),
    # --- GPU ---------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="gpu_load", translation_key="gpu_load", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:expansion-card",
        value_fn=lambda d: _round(_hw(d).get("gpu_util")),
    ),
    StrataSensorDescription(
        key="vram_used", translation_key="vram_used", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:memory",
        value_fn=lambda d: _hw(d).get("gpu_mem_used"),
        attrs_fn=lambda d: {"total_bytes": _hw(d).get("gpu_mem_total")},
    ),
    StrataSensorDescription(
        key="gpu_temperature", translation_key="gpu_temperature", device_class=SensorDeviceClass.TEMPERATURE,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: _round(_hw(d).get("gpu_temp")),
    ),
    StrataSensorDescription(
        key="gpu_power", translation_key="gpu_power", device_class=SensorDeviceClass.POWER,
        native_unit_of_measurement=UnitOfPower.WATT, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=0,
        value_fn=lambda d: _round(_hw(d).get("gpu_power")),
        attrs_fn=lambda d: {"power_limit_w": _hw(d).get("gpu_power_limit")},
    ),
    StrataSensorDescription(
        key="pcie_link", translation_key="pcie_link", icon="mdi:expansion-card-variant",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_pcie_link,
        attrs_fn=lambda d: {"current_gen": _hw(d).get("gpu_pcie_gen")},
    ),
    StrataSensorDescription(
        key="pcie_rx", translation_key="pcie_rx", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1, entity_registry_enabled_default=False,
        value_fn=lambda d: _round(_hw(d).get("gpu_pcie_rx_mb"), 2),
    ),
    # --- host --------------------------------------------------------------------------------------
    StrataSensorDescription(
        key="cpu", translation_key="cpu", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:cpu-64-bit",
        value_fn=lambda d: _round(_hw(d).get("cpu")),
    ),
    StrataSensorDescription(
        key="ram_used", translation_key="ram_used", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:memory",
        value_fn=lambda d: _hw(d).get("ram_used"),
        attrs_fn=lambda d: {"total_bytes": _hw(d).get("ram_total")},
    ),
    StrataSensorDescription(
        key="disk_read", translation_key="disk_read", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: _round(_hw(d).get("disk_read_mb"), 2),
    ),
    StrataSensorDescription(
        key="disk_write", translation_key="disk_write", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEBIBYTES_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=lambda d: _round(_hw(d).get("disk_write_mb"), 2),
    ),
    # --- context / experts -------------------------------------------------------------------------
    StrataSensorDescription(
        key="context_used", translation_key="context_used", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:text-box-outline",
        value_fn=_ctx_used,
    ),
    StrataSensorDescription(
        key="context_fill", translation_key="context_fill", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, icon="mdi:gauge",
        value_fn=_ctx_pct,
    ),
    StrataSensorDescription(
        key="max_context", translation_key="max_context", native_unit_of_measurement=TOKENS,
        entity_category=EntityCategory.DIAGNOSTIC, icon="mdi:text-box-multiple-outline",
        value_fn=lambda d: _eng(d).get("max_context"),
    ),
    StrataSensorDescription(
        key="experts_cached", translation_key="experts_cached", state_class=SensorStateClass.MEASUREMENT,
        icon="mdi:layers-triple",
        value_fn=lambda d: _eng(d).get("expert_slots"),
    ),
    StrataSensorDescription(
        key="expert_cache_size", translation_key="expert_cache_size", device_class=SensorDeviceClass.DATA_SIZE,
        native_unit_of_measurement=UnitOfInformation.BYTES, suggested_unit_of_measurement=UnitOfInformation.GIBIBYTES,
        suggested_display_precision=1, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_expert_cache_bytes,
    ),
    StrataSensorDescription(
        key="model", translation_key="model", entity_category=EntityCategory.DIAGNOSTIC, icon="mdi:brain",
        value_fn=lambda d: _eng(d).get("model"),
        attrs_fn=lambda d: {"images": _eng(d).get("images")},
    ),
    # --- last request ------------------------------------------------------------------------------
    StrataSensorDescription(
        key="last_prompt_tokens", translation_key="last_prompt_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:import",
        value_fn=_last_field("prompt_tokens"),
        attrs_fn=lambda d: {"reused": (_last(d) or {}).get("reused")},
    ),
    StrataSensorDescription(
        key="last_output_tokens", translation_key="last_output_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.MEASUREMENT, icon="mdi:export",
        value_fn=_last_field("output_tokens"),
        attrs_fn=lambda d: {"finish": (_last(d) or {}).get("finish")},
    ),
    StrataSensorDescription(
        key="last_duration", translation_key="last_duration", device_class=SensorDeviceClass.DURATION,
        native_unit_of_measurement=UnitOfTime.SECONDS, state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=1,
        value_fn=_last_field("duration_s"),
    ),
    StrataSensorDescription(
        key="last_vram_hit_rate", translation_key="last_vram_hit_rate", native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1, icon="mdi:target",
        value_fn=_last_field("hit_rate", 100, 1),
        attrs_fn=lambda d: {"pcie_share_pct": _last_field("pcie_share", 100, 1)(d)},
    ),
    # --- totals since server start (reset on restart: total_increasing handles that) ---------------
    StrataSensorDescription(
        key="requests_total", translation_key="requests_total", state_class=SensorStateClass.TOTAL_INCREASING,
        icon="mdi:counter",
        value_fn=lambda d: _tot(d).get("requests"),
    ),
    StrataSensorDescription(
        key="prompt_tokens_read", translation_key="prompt_tokens_read", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:import",
        value_fn=lambda d: ((_tot(d).get("prompt_tokens") or 0) - (_tot(d).get("reused") or 0)) if _tot(d) else None,
    ),
    StrataSensorDescription(
        key="prompt_tokens_reused", translation_key="prompt_tokens_reused", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:recycle",
        value_fn=lambda d: _tot(d).get("reused"),
    ),
    StrataSensorDescription(
        key="output_tokens", translation_key="output_tokens", native_unit_of_measurement=TOKENS,
        state_class=SensorStateClass.TOTAL_INCREASING, icon="mdi:export",
        value_fn=lambda d: _tot(d).get("output_tokens"),
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
        return _state(self.coordinator.data or {})

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.data or {}
        eng = _eng(d)
        return {
            "engine": {
                "model": eng.get("model"),
                "max_context": eng.get("max_context"),
                "expert_slots": eng.get("expert_slots"),
                "expert_cache_mib": eng.get("expert_cache_mib") or (eng.get("vram") or {}).get("expert_cache_mib"),
            },
            "live": _live(d),
            "hardware": _hw(d),
            "hardware_static": d.get("hardware_static") or {},
            "history": d.get("history") or {},
            "requests": [{k: r.get(k) for k in REQUEST_FIELDS} for r in (d.get("requests") or [])],
            "requests_kept": d.get("requests_kept"),
            "totals": _tot(d),
            "server_time": d.get("time"),
        }
