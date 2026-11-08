"""End-to-end: config flow -> setup -> sensor states, against recorded /metrics payloads."""

import json
from pathlib import Path

from homeassistant import config_entries
from homeassistant.const import CONF_API_KEY, CONF_HOST, CONF_PORT, CONF_SSL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er

from custom_components.strata.const import DOMAIN

FIX = Path(__file__).parent / "fixtures"
URL = "http://192.168.50.70:8080"
HEALTH = {"status": "ok", "max_context": 262144, "model": "qwen3.8-flash-next", "service": "strata", "loaded": True}


def _metrics(name="metrics"):
    return json.loads((FIX / f"{name}.json").read_text())


async def _setup(hass, aioclient_mock, name="metrics", key="secret"):
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    aioclient_mock.get(f"{URL}/metrics", json=_metrics(name))
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.50.70", CONF_PORT: 8080, CONF_API_KEY: key})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    await hass.async_block_till_done()
    return result["result"]


def _id(hass, key):
    reg = er.async_get(hass)
    for e in reg.entities.values():
        if e.platform == DOMAIN and e.unique_id.endswith(f"_{key}"):
            return e.entity_id
    raise AssertionError(key)


async def test_idle(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock)
    assert entry.data[CONF_HOST] == "192.168.50.70" and entry.data[CONF_PORT] == 8080
    assert entry.unique_id == "192.168.50.70:8080"
    # the key is sent as a bearer token
    sent = [c for c in aioclient_mock.mock_calls if str(c[1]).endswith("/metrics")]
    assert sent and sent[-1][3]["Authorization"] == "Bearer secret"

    s = lambda k: hass.states.get(_id(hass, k))
    assert s("state").state == "idle"
    assert s("decode_speed").state == "43.5"
    assert float(s("prefill_speed").state) == 60
    assert float(s("gpu_temperature").state) == 72
    assert float(s("gpu_power").state) == 50.2
    assert s("gpu_load").state == "unknown"            # Intel xe: no util reading
    assert s("pcie_link").state == "Gen4 x16"
    assert float(s("disk_read").state) == 576.0
    assert s("experts_cached").state == "12490"
    assert float(s("context_fill").state) == 32.6     # (85170+245)/262144
    assert s("requests_total").state == "2704"
    assert s("prompt_tokens_read").state == "30643568"
    assert round(float(s("ram_used").state), 1) == 29.6         # bytes -> GiB via suggested unit
    assert float(s("decode_speed_avg").state) == 43.7
    assert float(s("prefill_speed_avg").state) == 734
    assert s("last_duration").state == "6.4"
    assert hass.states.get(_id(hass, "model_loaded")).state == "on"
    assert hass.states.get(_id(hass, "busy")).state == "off"
    mon = s("monitor")
    assert mon.attributes["requests_kept"] == 500
    assert len(mon.attributes["requests"]) == 12
    assert set(mon.attributes["requests"][0]) >= {"time", "prompt_tokens", "reused", "decode_tok_s"}
    assert "tok_s" in mon.attributes["history"]


async def test_generating(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup(hass, aioclient_mock, "metrics_generating")
    s = lambda k: hass.states.get(_id(hass, k))
    assert s("state").state == "generating"
    assert s("decode_speed").state == "46.2"
    assert float(s("prefill_speed").state) == 512
    assert float(s("gpu_load").state) == 97
    assert round(float(s("vram_used").state), 1) == 30.1
    assert hass.states.get(_id(hass, "busy")).state == "on"
    assert s("queued").state == "1"


async def test_bad_key(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{URL}/health", json=HEALTH)
    aioclient_mock.get(f"{URL}/metrics", status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.50.70:8080", CONF_API_KEY: "nope"})
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}


async def test_not_strata(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{URL}/health", json={"status": "ok"})
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "http://192.168.50.70:8080/"})
    assert result["errors"] == {"base": "cannot_connect"}


async def test_card_served(hass: HomeAssistant, aioclient_mock, hass_client) -> None:
    await _setup(hass, aioclient_mock)
    client = await hass_client()
    resp = await client.get("/strata_static/strata-card.js")
    assert resp.status == 200
    assert "customElements" in await resp.text()


async def test_domain_only_https(hass: HomeAssistant, aioclient_mock) -> None:
    """A domain alone with HTTPS: the request goes to https://domain (port 443), no port in the URL."""
    base = "https://strata.example.net"
    aioclient_mock.get(f"{base}/health", json=HEALTH)
    aioclient_mock.get(f"{base}/metrics", json=_metrics())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "strata.example.net", CONF_SSL: True})
    assert result["type"] is FlowResultType.CREATE_ENTRY, result
    assert result["data"][CONF_PORT] is None
    assert result["result"].unique_id == "strata.example.net:443"


def test_parse_input() -> None:
    from custom_components.strata.config_flow import InvalidHost, parse_input
    from custom_components.strata.coordinator import build_url
    import pytest
    cases = {
        ("192.168.50.70", 8080, False): "http://192.168.50.70:8080",
        ("192.168.50.70:8080", None, False): "http://192.168.50.70:8080",
        ("http://192.168.50.70:8080/", None, False): "http://192.168.50.70:8080",
        ("strata.example.net", None, False): "http://strata.example.net",
        ("strata.example.net", None, True): "https://strata.example.net",
        ("https://strata.example.net/", None, False): "https://strata.example.net",
        ("strata.example.net:9000", 8095, False): "http://strata.example.net:8095",   # the port field wins
        ("[fd00::70]:8095", None, False): "http://[fd00::70]:8095",
    }
    for (host, port, ssl), url in cases.items():
        assert build_url(parse_input({CONF_HOST: host, CONF_PORT: port, CONF_SSL: ssl})) == url, host
    for bad in ("", "   ", "http://", "a b"):
        with pytest.raises(InvalidHost):
            parse_input({CONF_HOST: bad})


async def test_reconfigure(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup(hass, aioclient_mock)
    new = "http://192.168.50.71:8095"
    aioclient_mock.get(f"{new}/health", json=HEALTH)
    aioclient_mock.get(f"{new}/metrics", json=_metrics())
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: "192.168.50.71", CONF_PORT: 8095})
    assert result["type"] is FlowResultType.ABORT and result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.50.71" and entry.data[CONF_PORT] == 8095
    assert entry.data[CONF_API_KEY] == "secret"   # kept when left empty
