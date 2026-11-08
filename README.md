# Strata LLM for Home Assistant

Fully AI generated with Opus 5.5

Custom integration for a [Strata](https://github.com/Niko1221/Strata) inference server. It polls the server's
`GET /metrics` (the JSON feed behind Strata's own Monitor tab), exposes the KPIs as sensors, and ships a Lovelace
card, `custom:strata-card`, laid out like the Monitor tab.

## Server side

Strata listens on `127.0.0.1:8095` by default (`--port` changes the port). For Home Assistant to reach it, start it with `--host 0.0.0.0`
(or `"host"` in its run config). Strata's own docs say not to do that without an API key: set `--api-key` /
`STRATA_API_KEY`. `/metrics` requires that key; `/health` does not.

Check from the Home Assistant host before adding the integration:

```sh
curl -s -H "Authorization: Bearer $KEY" http://<strata-host>:<port>/metrics | head -c 300
```

If HA and Strata are on different VLANs, the firewall must allow HA → Strata on that port.

## Install

**HACS:** add this repository as a custom repository (type *Integration*), install *Strata LLM*, restart HA.

**Manual:** copy `custom_components/strata` to `/config/custom_components/strata`, restart HA.

Then *Settings → Devices & services → Add integration → Strata LLM*:

| Field | Examples |
|---|---|
| Host | `192.168.50.70`, `192.168.50.70:8080`, `strata.example.net`, or a pasted URL like `http://192.168.50.70:8080/` |
| Port | optional: Strata's port (8095 unless `--port` changes it). Leave empty for a reverse proxy on 80 / 443 |
| Use HTTPS | on for an HTTPS reverse proxy (a pasted `https://` URL sets it) |
| Verify SSL certificate | off only for a self-signed certificate |
| API key | the server's `--api-key`; empty if none is set |

A port in the Port field overrides one written in the Host field. Host, port and HTTPS can be changed later with
*Reconfigure* on the integration's entry, without removing it.

Options: polling interval, 2–300 s (default 5 s; the server samples hardware once a second and keeps 60 s of history).
A wrong or changed key triggers HA's re-authentication prompt.

## Entities

| Entity | Source in `/metrics` |
|---|---|
| Model state (`idle` / `reading` / `generating` / `queued` / `unloaded`) | `live.state`, `live.queued` |
| Queued requests | `live.queued` |
| Decode speed · Prefill speed | live while running, else last request (as the Monitor shows) |
| Decode / Prefill speed (run average) | `totals` (token-weighted, since server start) |
| GPU load · VRAM used · GPU temperature · GPU power (attr: limit) | `hardware.gpu_*` |
| PCIe link (`Gen4 x16`) · PCIe to GPU (disabled by default) | `hardware.gpu_pcie_*` |
| CPU load · System RAM used · Disk read · Disk write | `hardware.*` |
| Context used · Context fill · Max context | running request, else last; `engine.max_context` |
| Experts in VRAM · Expert cache size | `engine.expert_slots`, `engine.expert_cache_mib` |
| Model | `engine.model` |
| Last request: prompt tokens (attr: reused), output tokens (attr: finish), duration, VRAM hit rate | `requests[0]` |
| Requests · Prompt tokens read · Prompt tokens reused · Output tokens | `totals` (`total_increasing`; a server restart resets them, which HA handles) |
| Monitor (diagnostic) | snapshot for the card |
| Model loaded · Busy (binary) | `live.state` |

On Intel Arc with the `xe` driver Strata reports no GPU utilisation or VRAM usage, so *GPU load* and *VRAM used*
stay `unknown` — the same "–" the Monitor tab shows. Temperature and power are reported.

Disk and PCIe rates are MiB/s (Strata divides by 2²⁰); the card labels them MB/s like the Monitor tab does.

## The card

The integration serves and loads the card itself; no resource needs adding. Add it from the card picker
(*Strata Monitor*) or in YAML:

```yaml
type: custom:strata-card
# entity: sensor.strata_monitor        # optional; found automatically with one Strata server
# title: Strata                        # optional, replaces "Model state"
# sections: [state, metrics, context, requests]   # optional, default all, in this order
# max_requests: 12                     # optional, the server sends the last 12
```

Use a *Panel* view or full width in a *Sections* view. Tiles open the matching sensor's history on click.
Colours follow the HA theme; Strata's green / blue / amber accents are fixed. Override the tile background or border
with the theme variables `strata-tile-background` and `strata-border-color`.

## Recorder

The *Monitor* sensor carries the snapshot (history, last requests) as attributes that are excluded from the recorder,
but it still updates every poll. To keep it out of the database entirely:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.strata_monitor*
```

## Tests

```sh
pip install pytest-homeassistant-custom-component
pytest tests
```

The fixtures in `tests/fixtures/` follow the payload shape of `Service.metrics()` in Strata's `serve/server.py`.
