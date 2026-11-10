"""Readers for the GET /metrics payload, shared by the sensor platforms.

Formulas follow Strata's Monitor tab (serve/web/app.js): prefill excludes reused tokens, live values while a
request runs and the last request otherwise.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

Data = dict[str, Any]

ACTIVE_STATES = ("reading", "generating")
STATES = ["idle", "reading", "generating", "queued", "unloaded"]


# --- sections -----------------------------------------------------------------------------------------

def live(d: Data) -> Data:
    return d.get("live") or {}


def hardware(d: Data) -> Data:
    return d.get("hardware") or {}


def engine(d: Data) -> Data:
    return d.get("engine") or {}


def totals(d: Data) -> Data:
    return d.get("totals") or {}


def last_request(d: Data) -> Data | None:
    reqs = d.get("requests") or []
    return reqs[0] if reqs else None


def round_num(v: Any, n: int = 1) -> float | None:
    return round(float(v), n) if isinstance(v, (int, float)) else None


# --- state --------------------------------------------------------------------------------------------

def raw_state(d: Data) -> str | None:
    return live(d).get("state")


def state(d: Data) -> str | None:
    """The server's state, with 'queued' when requests wait and nothing runs."""
    lv = live(d)
    if lv.get("queued") and lv.get("state") == "idle":
        return "queued"
    return lv.get("state")


def model_loaded(d: Data) -> bool | None:
    st = raw_state(d)
    return None if st is None else st != "unloaded"


def busy(d: Data) -> bool | None:
    st = raw_state(d)
    return None if st is None else (st in ACTIVE_STATES or bool(live(d).get("queued")))


# --- speed --------------------------------------------------------------------------------------------

def decode_speed(d: Data) -> float | None:
    """Now while generating, else the last request (the Monitor's 'Decode last request')."""
    lv = live(d)
    if lv.get("state") == "generating" and lv.get("tok_s") is not None:
        return round_num(lv["tok_s"])
    last = last_request(d)
    return round_num(last.get("decode_tok_s")) if last else None


def _prefill_of(r: Data | None) -> float | None:
    if not r or not r.get("prompt_ms"):
        return None
    fresh = max(0, (r.get("prompt_tokens") or 0) - (r.get("reused") or 0))
    return round_num(fresh / (r["prompt_ms"] / 1000), 0) if fresh else None


def prefill_speed(d: Data) -> float | None:
    lv = live(d)
    if lv.get("state") in ACTIVE_STATES and lv.get("prefill_tok_s_mean") is not None:
        return round_num(lv["prefill_tok_s_mean"], 0)
    return _prefill_of(last_request(d))


def decode_speed_avg(d: Data) -> float | None:
    t = totals(d)
    if not (t.get("decode_ms") and t.get("output_tokens")):
        return None
    return round_num(t["output_tokens"] / (t["decode_ms"] / 1000))


def prompt_tokens_read(d: Data) -> int | None:
    t = totals(d)
    return (t.get("prompt_tokens") or 0) - (t.get("reused") or 0) if t else None


def prefill_speed_avg(d: Data) -> float | None:
    t = totals(d)
    read = prompt_tokens_read(d) or 0
    return round_num(read / (t["prompt_ms"] / 1000), 0) if t.get("prompt_ms") and read > 0 else None


# --- context / hardware -------------------------------------------------------------------------------

def context_used(d: Data) -> int | None:
    lv = live(d)
    if lv.get("state") in ACTIVE_STATES:
        return (lv.get("prompt_tokens") or 0) + (lv.get("generated") or 0)
    last = last_request(d)
    return (last.get("prompt_tokens") or 0) + (last.get("output_tokens") or 0) if last else None


def context_fill(d: Data) -> float | None:
    used, ctx = context_used(d), engine(d).get("max_context")
    return round_num(min(100.0, 100 * used / ctx), 1) if used is not None and ctx else None


def pcie_link(d: Data) -> str | None:
    hw = hardware(d)
    gen = hw.get("gpu_pcie_gen_max") or hw.get("gpu_pcie_gen")
    if not gen:
        return None
    return f"Gen{gen} x{hw['gpu_pcie_width']}" if hw.get("gpu_pcie_width") else f"Gen{gen}"


def expert_cache_mib(d: Data) -> float | None:
    eng = engine(d)
    return eng.get("expert_cache_mib") or (eng.get("vram") or {}).get("expert_cache_mib")


def expert_cache_bytes(d: Data) -> int | None:
    mib = expert_cache_mib(d)
    return int(mib * 2**20) if mib else None


# --- factories ----------------------------------------------------------------------------------------

def hw_value(key: str, nd: int = 1) -> Callable[[Data], float | None]:
    """A rounded hardware reading."""
    return lambda d: round_num(hardware(d).get(key), nd)


def last_value(key: str, scale: float = 1, nd: int | None = None) -> Callable[[Data], Any]:
    """A numeric field of the last request, optionally scaled and rounded."""
    def fn(d: Data) -> Any:
        last = last_request(d)
        v = last.get(key) if last else None
        if not isinstance(v, (int, float)):
            return None
        v = v * scale
        return round(v, nd) if nd is not None else v
    return fn
