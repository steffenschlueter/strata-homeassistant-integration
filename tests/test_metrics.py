"""Unit tests for the /metrics readers."""

from custom_components.strata import metrics as m


def test_state_queued_only_when_idle() -> None:
    assert m.state({"live": {"state": "idle", "queued": 2}}) == "queued"
    assert m.state({"live": {"state": "generating", "queued": 2}}) == "generating"
    assert m.state({"live": {"state": "idle", "queued": 0}}) == "idle"
    assert m.state({}) is None


def test_binary_readers() -> None:
    assert m.model_loaded({"live": {"state": "unloaded"}}) is False
    assert m.model_loaded({}) is None
    assert m.busy({"live": {"state": "reading"}}) is True
    assert m.busy({"live": {"state": "idle", "queued": 1}}) is True
    assert m.busy({"live": {"state": "idle"}}) is False
    assert m.busy({}) is None


def test_prefill_excludes_reused_tokens() -> None:
    last = {"prompt_tokens": 3000, "reused": 1000, "prompt_ms": 2000}
    assert m.prefill_speed({"requests": [last]}) == 1000
    # all reused: no prefill speed
    assert m.prefill_speed({"requests": [{**last, "reused": 3000}]}) is None


def test_empty_payload() -> None:
    for fn in (m.decode_speed, m.prefill_speed, m.decode_speed_avg, m.prefill_speed_avg, m.context_used,
               m.context_fill, m.pcie_link, m.expert_cache_bytes, m.prompt_tokens_read):
        assert fn({}) is None, fn.__name__


def test_expert_cache_from_vram_block() -> None:
    assert m.expert_cache_bytes({"engine": {"vram": {"expert_cache_mib": 2}}}) == 2 * 2**20
