/*
 * strata-card - a Home Assistant card that mirrors Strata's Monitor tab.
 * Data: the "Monitor" sensor of the Strata integration (its attributes are the server's /metrics snapshot).
 *
 *   type: custom:strata-card
 *   entity: sensor.strata_monitor   # optional, found automatically when there is one Strata server
 *   title: Strata                   # optional
 *   sections: [state, metrics, context, requests]   # optional, default all, in this order
 *   metrics: [speed, gpu_load, vram, gpu_temp, power, pcie, cpu, disk]   # optional: which tiles, in this order
 *   columns: 4                      # optional: tiles per row (default: up to 4)
 *   max_requests: 12                # optional
 * A card with only the metrics section draws its tiles without the surrounding card, so a single tile
 * (metrics: [power]) sits on the dashboard like any other card.
 */
const CARD_VERSION = "0.2.1";

const SECTIONS = ["state", "metrics", "context", "requests"];
const METRICS = ["speed", "gpu_load", "vram", "gpu_temp", "power", "pcie", "cpu", "disk"];
const SECTION_LABELS = {state: "Model state", metrics: "Metric tiles", context: "Context fill", requests: "Recent requests"};
const METRIC_LABELS = {speed: "Speed (decode / prefill)", gpu_load: "GPU load", vram: "VRAM", gpu_temp: "GPU temperature",
  power: "Power", pcie: "PCIe", cpu: "CPU", disk: "Disk read"};
const C = {green: "#34d399", blue: "#3aa9ff", amber: "#f5b53d", red: "#ff5a6e"};

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));

class StrataCard extends HTMLElement {
  static getStubConfig(hass) {
    const id = StrataCard.findMonitor(hass);
    return id ? {entity: id} : {};
  }

  static findMonitor(hass) {
    if (!hass) return null;
    const ents = hass.entities || {};
    for (const [id, e] of Object.entries(ents)) {
      if (e.platform === "strata" && e.translation_key === "monitor") return id;
    }
    return Object.keys(hass.states).find((id) => id.startsWith("sensor.") && hass.states[id].attributes.history &&
      hass.states[id].attributes.hardware_static && hass.states[id].attributes.engine) || null;
  }

  static getConfigElement() { return document.createElement("strata-card-editor"); }

  setConfig(config) {
    for (const [key, allowed] of [["sections", SECTIONS], ["metrics", METRICS]]) {
      const v = config[key];
      if (v == null) continue;
      if (!Array.isArray(v)) throw new Error(`${key} must be a list`);
      const bad = v.filter((x) => !allowed.includes(x));
      if (bad.length) throw new Error(`unknown ${key}: ${bad.join(", ")} (allowed: ${allowed.join(", ")})`);
    }
    if (config.columns != null && !(Number(config.columns) >= 1 && Number(config.columns) <= 8)) throw new Error("columns must be 1-8");
    this._config = {max_requests: 12, sections: SECTIONS, metrics: METRICS, ...config};
    this._lastState = null;
    if (!this.shadowRoot) this.attachShadow({mode: "open"});
    if (this._hass) this._render(true);
  }

  set hass(hass) {
    this._hass = hass;
    this._render(false);
  }

  getCardSize() { return this._onlyMetrics() ? 3 : 14; }

  _onlyMetrics() {
    const s = (this._config && this._config.sections) || SECTIONS;
    return s.length === 1 && s[0] === "metrics";
  }

  getGridOptions() {
    if (this._onlyMetrics()) {                    // tiles alone: as wide as they need in a Sections view
      const n = Math.max(1, (this._config.metrics || METRICS).length);
      const cols = Math.min(n, Number(this._config.columns) || 4);
      return {columns: cols >= 4 ? "full" : cols * 3, min_columns: 3, rows: "auto"};
    }
    return {columns: "full", min_columns: 6};
  }

  _entityId() {
    return this._config.entity || StrataCard.findMonitor(this._hass);
  }

  // sibling sensors of the same device, by translation key - for the more-info dialogs
  _sibling(key) {
    const h = this._hass, mon = this._entityId();
    const dev = h.entities && h.entities[mon] ? h.entities[mon].device_id : null;
    if (!dev) return null;
    for (const [id, e] of Object.entries(h.entities)) if (e.device_id === dev && e.translation_key === key) return id;
    return null;
  }

  _moreInfo(entityId) {
    if (!entityId) return;
    const ev = new Event("hass-more-info", {bubbles: true, composed: true});
    ev.detail = {entityId};
    this.dispatchEvent(ev);
  }

  // number formatting in the user's HA locale
  _fmt(n, d = 0) {
    if (n == null || Number.isNaN(Number(n))) return "\u2013";
    const lang = (this._hass && this._hass.locale && this._hass.locale.language) || undefined;
    return Number(n).toLocaleString(lang, {maximumFractionDigits: d, minimumFractionDigits: d});
  }
  _kfmt(n) { return n == null ? "\u2013" : n >= 1000 ? `${this._fmt(n / 1000, n >= 10000 ? 0 : 1)}k` : this._fmt(n); }
  _ctxfmt(n) { return n && n % 1024 === 0 ? `${this._fmt(n / 1024)}K` : this._kfmt(n); }
  _gb(b, d = 1) { return b == null ? "\u2013" : this._fmt(b / 1073741824, d); }
  _time(t, opts) {
    const loc = (this._hass && this._hass.locale) || {};
    const o = {...opts};
    if (loc.time_format === "12") o.hour12 = true;
    else if (loc.time_format === "24") o.hour12 = false;
    return new Date(t * 1000).toLocaleTimeString(loc.language || undefined, o);
  }

  _spark(values, color, max, opts = {}) {
    const v = (values || []).map((x) => (x == null ? 0 : x));
    if (v.length < 2) {     // no readings (e.g. GPU load / VRAM on Intel xe): a flat baseline, as Strata draws it
      return opts.overlay ? "" : `<svg class="spark" viewBox="0 0 100 32" preserveAspectRatio="none"><path d="M0,30L100,30" ` +
        `stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke" fill="none"/></svg>`;
    }
    const top = Math.max(max || 0, ...v, 1);
    const pts = v.map((x, i) => [(i / (v.length - 1)) * 100, 30 - (x / top) * 26]);
    const line = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(2)},${p[1].toFixed(2)}`).join("");
    const area = opts.noArea ? "" : `<path d="${line}L100,32L0,32Z" fill="${color}" fill-opacity=".16"/>`;
    return `<svg class="spark${opts.overlay ? " overlay" : ""}" viewBox="0 0 100 32" preserveAspectRatio="none">${area}` +
      `<path d="${line}" fill="none" stroke="${color}" stroke-width="1.6" vector-effect="non-scaling-stroke"` +
      `${opts.opacity ? ` stroke-opacity="${opts.opacity}"` : ""} stroke-linejoin="round"/></svg>`;
  }

  _tile(key, icon, title, valueHtml, sub, spark) {
    return `<div class="tile" data-key="${key}"><div class="tile-head"><ha-icon icon="${icon}"></ha-icon><span>${esc(title)}</span></div>` +
      `<div class="tile-val">${valueHtml}</div><div class="tile-sub">${esc(sub || "")}</div><div class="tile-spark">${spark}</div></div>`;
  }

  _val(v, unit) { return v == null ? "\u2013" : `${esc(v)}${unit ? `<small>${esc(unit)}</small>` : ""}`; }

  _render(force) {
    if (!this._config || !this._hass || !this.shadowRoot) return;
    const id = this._entityId();
    const st = id ? this._hass.states[id] : null;
    if (!force && st === this._lastState) return;    // HA replaces the state object on every change
    this._lastState = st;
    const title = this._config.title;

    if (!st || st.state === "unavailable" || !st.attributes.engine) {
      this.shadowRoot.innerHTML = `${STYLE}<ha-card>${title ? `<div class="title">${esc(title)}</div>` : ""}` +
        `<div class="empty">${!id ? "No Strata monitor sensor found. Set <code>entity:</code>." :
          !st ? `Entity ${esc(id)} not found.` : "Strata server unreachable."}</div></ha-card>`;
      return;
    }

    const a = st.attributes;
    const live = a.live || {}, hw = a.hardware || {}, sx = a.hardware_static || {}, eng = a.engine || {};
    const h = a.history || {}, reqs = a.requests || [], totals = a.totals || {};
    const last = reqs[0];
    const show = new Set(this._config.sections);
    const parts = [];
    const fmt = this._fmt.bind(this);

    // ---------- model state ----------
    if (show.has("state")) {
      const on = live.queued > 0 && live.state === "idle" ? "queued" : live.state;
      const badges = [["idle", "Idle"], ["unloaded", "Unloaded"], ["reading", "Reading"], ["generating", "Generating"],
        ["queued", "Queued"], ["error", "Error"]]
        .filter(([s]) => s !== "unloaded" || live.state === "unloaded")
        .map(([s, t]) => `<span class="badge b-${s}${s === on || s === live.state ? " on" : ""}">${t}</span>`).join("");
      let label = "Waiting for a request", detail = "", pct = 0, tone = "accent";
      if (live.state === "reading") {
        label = "Reading prompt"; tone = "info";
        if (live.prompt_total) {
          pct = (100 * live.prompt_read) / live.prompt_total;
          detail = `${fmt(live.prompt_read)} / ${fmt(live.prompt_total)} tokens \u00b7 ${fmt(pct)}%`;
        } else detail = `${fmt(live.prompt_tokens)} tokens`;
      } else if (live.state === "generating") {
        label = live.phase ? live.phase[0].toUpperCase() + live.phase.slice(1) : "Generating";
        pct = live.max_tokens ? Math.min(100, (100 * live.generated) / live.max_tokens) : 0;
        detail = `${fmt(live.generated)} tokens \u00b7 ${fmt(live.tok_s, 1)} tok/s`;
      } else if (live.state === "unloaded") {
        label = "Unloaded"; detail = "Loads on the next request.";
      } else if (last) {
        detail = `last: ${fmt(last.output_tokens)} tokens${last.decode_tok_s ? ` at ${fmt(last.decode_tok_s, 1)} tok/s` : ""}`;
      }
      if (live.queued > 0) detail += `${detail ? " \u00b7 " : ""}${fmt(live.queued)} queued`;
      parts.push(`<div class="panel state" data-key="state"><div class="state-head"><span class="ptitle">${esc(title || "Model state")}</span>` +
        `<span class="badges">${badges}</span></div><div class="state-row"><span>${esc(label)}</span><span class="muted">${esc(detail)}</span></div>` +
        `<div class="bar t-${tone}"><div style="width:${pct.toFixed(1)}%"></div></div></div>`);
    }

    // ---------- the eight metric tiles ----------
    if (show.has("metrics")) {
      const gen = live.state === "generating";
      const decode = gen ? live.tok_s : last ? last.decode_tok_s : null;
      const fresh = last && last.prompt_tokens != null ? Math.max(0, last.prompt_tokens - (last.reused || 0)) : 0;
      const prefill = (live.state === "reading" || gen) ? live.prefill_tok_s_mean
        : last && last.prompt_ms > 0 && fresh ? fresh / (last.prompt_ms / 1000) : null;
      const speed = `<div class="dual"><div><div class="tile-val">${this._val(decode == null ? null : fmt(decode, 1), "t/s")}</div>` +
        `<div class="tile-sub">${gen ? "Decode now" : "Decode last request"}</div></div>` +
        `<div class="right"><div class="tile-val">${this._val(prefill == null ? null : fmt(prefill), "t/s")}</div>` +
        `<div class="tile-sub">${live.state === "reading" ? "Prefill now" : gen ? "Prefill this request" : "Prefill last request"}</div></div></div>`;
      const tiles = {};
      tiles.speed = (`<div class="tile" data-key="decode_speed"><div class="tile-head"><ha-icon icon="mdi:speedometer"></ha-icon><span>Speed</span></div>${speed}` +
        `<div class="tile-spark">${this._spark(h.tok_s, C.green)}${this._spark(h.prefill_tok_s_mean, C.green, 0, {overlay: true, noArea: true, opacity: 0.45})}</div></div>`);
      const multi = (hw.gpus || []).length > 1;
      const per = (f) => (hw.gpus || []).map((g) => `GPU ${g.index} ${f(g)}`).join(" \u00b7 ");
      tiles.gpu_load = (this._tile("gpu_load", "mdi:expansion-card", "GPU load", this._val(hw.gpu_util == null ? null : fmt(hw.gpu_util), "%"),
        multi ? per((g) => (g.util == null ? "\u2013" : `${fmt(g.util)}%`)) : sx.gpu_name || "", this._spark(h.gpu_util, C.green, 100)));
      tiles.vram = (this._tile("vram_used", "mdi:layers-outline", "VRAM",
        this._val(hw.gpu_mem_used == null ? null : this._gb(hw.gpu_mem_used), hw.gpu_mem_total ? `/ ${this._gb(hw.gpu_mem_total, 0)} GB` : "GB"),
        eng.expert_slots ? `${fmt(eng.expert_slots)} experts cached` : "", this._spark(h.gpu_mem_used, C.green, hw.gpu_mem_total)));
      tiles.gpu_temp = (this._tile("gpu_temperature", "mdi:thermometer", "GPU temp", this._val(hw.gpu_temp == null ? null : fmt(hw.gpu_temp), "\u00b0C"),
        multi ? per((g) => (g.temp == null ? "\u2013" : `${fmt(g.temp)}\u00b0`)) : "", this._spark(h.gpu_temp, C.amber, 90)));
      tiles.power = (this._tile("gpu_power", "mdi:lightning-bolt-outline", "Power", this._val(hw.gpu_power == null ? null : fmt(hw.gpu_power), "W"),
        hw.gpu_power_limit ? `of ${fmt(hw.gpu_power_limit)} W limit` : "", this._spark(h.gpu_power, C.green, hw.gpu_power_limit)));
      const pg = hw.gpu_pcie_gen_max || hw.gpu_pcie_gen;
      tiles.pcie = (this._tile("pcie_link", "mdi:link-variant", "PCIe", this._val(pg ? `Gen${pg}` : null, hw.gpu_pcie_width ? `x${hw.gpu_pcie_width}` : ""),
        (hw.gpu_pcie_rx_mb == null ? "" : `to GPU ${fmt(hw.gpu_pcie_rx_mb, hw.gpu_pcie_rx_mb < 10 ? 1 : 0)} MB/s`) +
        (hw.gpu_pcie_gen && pg && hw.gpu_pcie_gen < pg ? ` \u00b7 idle Gen${hw.gpu_pcie_gen}` : ""), this._spark(h.gpu_pcie_rx_mb, C.blue)));
      tiles.cpu = (this._tile("cpu", "mdi:cpu-64-bit", "CPU", this._val(hw.cpu == null ? null : fmt(hw.cpu), "%"),
        sx.threads ? `${sx.cores ? `${sx.cores} cores \u00b7 ` : ""}${sx.threads} threads` : "", this._spark(h.cpu, C.green, 100)));
      let disk = null, dunit = "";
      if (hw.disk_read_mb != null) {
        const big = hw.disk_read_mb >= 1000;
        disk = big ? fmt(hw.disk_read_mb / 1024, 2) : fmt(hw.disk_read_mb, hw.disk_read_mb < 10 ? 1 : 0);
        dunit = big ? "GB/s" : "MB/s";
      }
      tiles.disk = (this._tile("disk_read", "mdi:harddisk", "Disk read", this._val(disk, dunit),
        hw.disk_write_mb == null ? "" : `write ${fmt(hw.disk_write_mb, 1)} MB/s`, this._spark(h.disk_read_mb, C.blue)));
      const order = this._config.metrics || METRICS;
      const cols = Number(this._config.columns) || Math.min(4, Math.max(1, order.length));
      parts.push(`<div class="metrics c${Math.min(cols, 4)}" style="--cols:${cols}">${order.map((k) => tiles[k] || "").join("")}</div>`);
    }

    // ---------- context fill + recent requests ----------
    const row = [];
    if (show.has("context")) {
      const ctx = eng.max_context || 0;
      let used = 0;
      if (live.state === "reading" || live.state === "generating") used = (live.prompt_tokens || 0) + (live.generated || 0);
      else if (last) used = (last.prompt_tokens || 0) + (last.output_tokens || 0);
      const frac = ctx ? Math.min(1, used / ctx) : 0;
      const dash = 235.6 * frac;
      const cache = (eng.expert_cache_mib || 0) * 1048576;
      const slotsPct = hw.gpu_mem_total ? Math.min(100, (100 * cache) / hw.gpu_mem_total) : 0;
      const ramPct = hw.ram_total ? (100 * hw.ram_used) / hw.ram_total : 0;
      const tempPct = hw.gpu_temp == null ? 0 : Math.min(100, hw.gpu_temp);
      row.push(`<div class="panel ctx" data-key="context_fill"><span class="ptitle">Context fill</span>
        <div class="gauge"><svg viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="50" fill="none" stroke="var(--track)" stroke-width="10" stroke-linecap="round" stroke-dasharray="235.6 314.2" transform="rotate(135 60 60)"/>
          <circle cx="60" cy="60" r="50" fill="none" stroke="${C.green}" stroke-width="10" stroke-linecap="round" stroke-dasharray="${dash.toFixed(1)} 314.2" transform="rotate(135 60 60)" style="opacity:${dash >= 3 ? 1 : 0}"/>
        </svg><div class="glabel"><span class="gpct">${Math.round(frac * 100)}%</span><span class="muted">${ctx ? `${this._kfmt(used)} / ${this._ctxfmt(ctx)}` : "\u2013"}</span></div></div>
        <div class="brow" data-key="experts_cached"><span>Experts in VRAM</span><span class="muted">${eng.expert_slots ? `${fmt(eng.expert_slots)} \u00b7 ${this._gb(cache)} GB` : "\u2013"}</span></div>
        <div class="bar t-accent"><div style="width:${slotsPct}%"></div></div>
        <div class="brow" data-key="ram_used"><span>System RAM</span><span class="muted">${hw.ram_total ? `${this._gb(hw.ram_used)} / ${this._gb(hw.ram_total, 0)} GB` : "\u2013"}</span></div>
        <div class="bar ${ramPct > 92 ? "t-danger" : "t-accent"}"><div style="width:${ramPct}%"></div></div>
        <div class="brow" data-key="gpu_temperature"><span>GPU temperature</span><span class="muted">${hw.gpu_temp == null ? "\u2013" : `${fmt(hw.gpu_temp)} \u00b0C`}</span></div>
        <div class="bar t-warn"><div style="width:${tempPct}%"></div></div></div>`);
    }
    if (show.has("requests")) {
      const badge = {stop: ["", "Done"], length: ["", "Max tokens"], cancel: ["b-queued on", "Stopped"],
        disconnect: ["b-queued on", "Closed"], error: ["b-error on", "Error"], timeout: ["b-queued on", "Timeout"]};
      const n = Math.max(1, Number(this._config.max_requests) || 12);
      const rows = reqs.slice(0, n).map((r) => {
        const [cls, text] = badge[r.finish] || ["", r.finish || "\u2013"];
        const hit = r.hit_rate == null ? "\u2013" : `${(r.hit_rate * 100).toFixed(1)}%` +
          (r.pcie_share ? ` <span class="muted">+${(r.pcie_share * 100).toFixed(1)}% PCIe</span>` : "");
        const fr = r.prompt_tokens == null ? null : Math.max(0, r.prompt_tokens - (r.reused || 0));
        const pr = fr > 0 && r.prompt_ms > 0 ? fr / (r.prompt_ms / 1000) : null;
        return `<tr><td>${esc(this._time(r.time, {hour: "2-digit", minute: "2-digit", second: "2-digit"}))}</td>` +
          `<td><span class="badge done ${cls}">${esc(text)}</span></td><td class="num">${fmt(r.prompt_tokens)}</td>` +
          `<td class="num">${fmt(r.reused)}</td><td class="num">${fmt(r.output_tokens)}</td><td class="num">${fmt(pr)}</td>` +
          `<td class="num">${fmt(r.decode_tok_s, 1)}</td><td class="num">${hit}</td><td class="num">${fmt(r.duration_s, 1)} s</td></tr>`;
      }).join("") || `<tr><td colspan="9" class="muted">No requests yet</td></tr>`;
      let foot = "";
      if (totals.requests) {
        const since = new Date(totals.since * 1000).toLocaleString((this._hass.locale || {}).language || undefined,
          {weekday: "short", hour: "2-digit", minute: "2-digit", hour12: (this._hass.locale || {}).time_format === "12" ? true : (this._hass.locale || {}).time_format === "24" ? false : undefined});
        const read = totals.prompt_tokens - (totals.reused || 0);
        const ps = totals.prompt_ms > 0 && read > 0 ? ` at ${fmt(read / (totals.prompt_ms / 1000))} tok/s` : "";
        const os = totals.decode_ms > 0 && totals.output_tokens > 0 ? ` at ${fmt(totals.output_tokens / (totals.decode_ms / 1000), 1)} tok/s` : "";
        foot = `Since ${since}: ${fmt(totals.requests)} requests \u00b7 ${fmt(read)} prompt tokens read${ps} (${fmt(totals.reused)} reused) \u00b7 ${fmt(totals.output_tokens)} written${os}`;
      }
      const kept = a.requests_kept;
      row.push(`<div class="panel req"><div class="req-head"><span class="ptitle">Recent requests</span>` +
        `${kept > n ? `<span class="pill">${fmt(kept)} kept</span>` : ""}</div>` +
        `<div class="twrap"><table><thead><tr><th>Time</th><th>Status</th><th class="num">Prompt</th><th class="num">Reused</th>` +
        `<th class="num">Output</th><th class="num">Prefill t/s</th><th class="num">Decode t/s</th><th class="num">VRAM hit rate</th>` +
        `<th class="num">Duration</th></tr></thead><tbody>${rows}</tbody></table></div>` +
        `${foot ? `<p class="muted foot">${esc(foot)}</p>` : ""}</div>`);
    }
    if (row.length) parts.push(`<div class="row${row.length === 1 ? " single" : ""}">${row.join("")}</div>`);

    this.shadowRoot.innerHTML = `${STYLE}<ha-card class="${this._onlyMetrics() ? "bare" : ""}"><div class="wrap">${parts.join("")}</div></ha-card>`;
    this.shadowRoot.querySelectorAll("[data-key]").forEach((el) => {
      el.addEventListener("click", (e) => {
        e.stopPropagation();
        const key = el.dataset.key;
        this._moreInfo(key === "state" ? this._sibling("state") || id : this._sibling(key));
      });
    });
  }
}

const STYLE = `<style>
  :host { --st-green:${C.green}; --st-blue:${C.blue}; --st-amber:${C.amber}; --st-red:${C.red};
    --tile-bg: var(--strata-tile-background, color-mix(in srgb, var(--primary-text-color) 3.5%, var(--card-background-color, var(--ha-card-background))));
    --line: var(--strata-border-color, color-mix(in srgb, var(--primary-text-color) 10%, transparent));
    --track: color-mix(in srgb, var(--primary-text-color) 9%, transparent);
    --muted: var(--secondary-text-color); display:block; container-type:inline-size; }
  ha-card { padding: 16px; overflow: hidden; color: var(--primary-text-color); }
  .wrap { color: var(--primary-text-color); display:flex; flex-direction:column; gap:14px; }
  .title { font-size: 1.1em; font-weight:600; padding-bottom: 8px; }
  .empty { color: var(--muted); padding: 8px 0; }
  .muted { color: var(--muted); }
  .panel, .tile { background: var(--tile-bg); border: 1px solid var(--line); border-radius: 16px; min-width:0; box-sizing:border-box; }
  [data-key] { cursor: pointer; }
  .panel { padding: 16px 18px; }
  .ptitle { font-weight: 700; font-size: 1.05em; }
  .state-head { display:flex; align-items:center; gap:12px; flex-wrap:wrap; }
  .badges { display:flex; gap:8px; flex-wrap:wrap; }
  .badge { display:inline-flex; align-items:center; gap:6px; height:24px; padding:0 10px; border-radius:999px; font-size:.78em; font-weight:700;
    border:1px solid var(--line); color: var(--muted); background: color-mix(in srgb, var(--primary-text-color) 5%, transparent); opacity:.38; white-space:nowrap; }
  .badge::before { content:""; width:6px; height:6px; border-radius:50%; background: currentColor; }
  .badge.on { opacity:1; }
  .badge.b-idle.on { color: var(--primary-text-color); }
  .badge.b-reading { color: var(--st-blue); background: color-mix(in srgb, var(--st-blue) 12%, transparent); border-color: transparent; }
  .badge.b-generating { color: var(--st-green); background: color-mix(in srgb, var(--st-green) 12%, transparent); border-color: transparent; }
  .badge.b-queued { color: var(--st-amber); background: color-mix(in srgb, var(--st-amber) 12%, transparent); border-color: transparent; }
  .badge.b-error { color: var(--st-red); background: color-mix(in srgb, var(--st-red) 12%, transparent); border-color: transparent; }
  .badge.done { opacity:1; }
  .state-row { display:flex; justify-content:space-between; gap:12px; margin: 14px 0 12px; flex-wrap:wrap; }
  .bar { height:8px; border-radius:999px; background: var(--track); overflow:hidden; margin: 6px 0 12px; }
  .bar > div { height:100%; border-radius:999px; transition: width .4s ease; }
  .bar.t-accent > div { background: var(--st-green); }
  .bar.t-info > div { background: var(--st-blue); }
  .bar.t-warn > div { background: var(--st-amber); }
  .bar.t-danger > div { background: var(--st-red); }
  .metrics { display:grid; grid-template-columns: repeat(var(--cols, 4), minmax(0,1fr)); gap:14px; }
  ha-card.bare { background: none; border: none; box-shadow: none; padding: 0; overflow: visible; }
  ha-card.bare .tile { background: var(--ha-card-background, var(--card-background-color)); border-radius: var(--ha-card-border-radius, 16px);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--line)); box-shadow: var(--ha-card-box-shadow, none); }
  .tile { padding: 14px 16px 10px; display:flex; flex-direction:column; }
  .tile-head { display:flex; align-items:center; gap:8px; color: var(--primary-text-color); font-size:.95em; }
  .tile-head ha-icon { --mdc-icon-size: 18px; color: var(--muted); }
  .tile-val { font-size: 2.2em; font-weight: 800; letter-spacing:-.02em; line-height:1.1; margin-top: 10px; font-variant-numeric: tabular-nums; }
  .tile-val small { font-size: .42em; font-weight: 500; color: var(--muted); margin-left: 4px; letter-spacing:0; }
  .tile-sub { color: var(--muted); font-size: .85em; margin-top: 6px; min-height: 1.2em; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .dual { display:flex; justify-content:space-between; gap:10px; }
  .dual .right { text-align:right; }
  .tile-spark { position:relative; height: 40px; margin-top: 10px; }
  .spark { position:absolute; inset:0; width:100%; height:100%; overflow:visible; }
  .row { display:grid; grid-template-columns: minmax(240px, 1fr) minmax(0, 2.4fr); gap:14px; }
  .row.single { grid-template-columns: 1fr; }
  .gauge { position:relative; width: 190px; max-width:100%; margin: 12px auto 20px; }
  .gauge svg { width:100%; display:block; }
  .glabel { position:absolute; inset:0; display:flex; flex-direction:column; align-items:center; justify-content:center; gap:2px; }
  .gpct { font-size: 1.9em; font-weight: 800; }
  .brow { display:flex; justify-content:space-between; gap:8px; margin-top: 8px; }
  .req-head { display:flex; align-items:center; justify-content:space-between; gap:8px; margin-bottom: 8px; }
  .pill { border:1px solid var(--line); border-radius:999px; padding: 4px 12px; font-size:.85em; font-weight:600; }
  .twrap { overflow-x:auto; }
  table { width:100%; border-collapse:collapse; font-variant-numeric: tabular-nums; font-size:.92em; }
  th { text-align:left; font-weight:600; font-size:.78em; letter-spacing:.06em; text-transform:uppercase; color: var(--muted); padding: 10px 8px; white-space:nowrap; }
  td { padding: 10px 8px; border-top: 1px solid var(--line); white-space:nowrap; }
  tbody tr:first-child td { background: color-mix(in srgb, var(--primary-text-color) 3%, transparent); }
  .num { text-align:right; }
  .foot { font-size:.85em; margin: 12px 0 0; }
  @container (max-width: 900px) {
    .metrics.c3, .metrics.c4 { grid-template-columns: repeat(2, minmax(0,1fr)); }
    .row { grid-template-columns: 1fr; }
  }
  @container (max-width: 420px) {
    ha-card { padding: 10px; }
    .metrics { grid-template-columns: 1fr; }
    .tile-val { font-size: 1.8em; }
  }
</style>`;

// visual editor: Home Assistant's own ha-form, so it looks like every other card editor
const EDITOR_SCHEMA = [
  {name: "entity", selector: {entity: {filter: {integration: "strata", domain: "sensor"}}}},
  {name: "title", selector: {text: {}}},
  {name: "sections", selector: {select: {multiple: true, mode: "list",
    options: SECTIONS.map((v) => ({value: v, label: SECTION_LABELS[v]}))}}},
  {name: "metrics", selector: {select: {multiple: true, mode: "list",
    options: METRICS.map((v) => ({value: v, label: METRIC_LABELS[v]}))}}},
  {name: "", type: "grid", schema: [
    {name: "columns", selector: {number: {min: 1, max: 8, mode: "box"}}},
    {name: "max_requests", selector: {number: {min: 1, max: 12, mode: "box"}}},
  ]},
];
const EDITOR_LABELS = {entity: "Monitor sensor (Strata \u2026 Monitor)", title: "Title", sections: "Sections",
  metrics: "Metric tiles", columns: "Tiles per row", max_requests: "Requests shown"};

class StrataCardEditor extends HTMLElement {
  setConfig(config) { this._config = config; this._render(); }
  set hass(hass) { this._hass = hass; this._render(); }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.computeLabel = (s) => EDITOR_LABELS[s.name] || s.name;
      this._form.computeHelper = (s) => s.name === "metrics" ? "Shown in the order you tick them. Untick everything but one for a single-stat card (with only the Metric tiles section)." : undefined;
      this._form.addEventListener("value-changed", (ev) => {
        const cfg = {...ev.detail.value};
        // keep orders stable: sections follow the card's layout; metrics keep the order they were ticked in
        if (Array.isArray(cfg.sections)) cfg.sections = SECTIONS.filter((x) => cfg.sections.includes(x));
        for (const k of ["title", "columns"]) if (cfg[k] === "" || cfg[k] == null) delete cfg[k];
        if (cfg.max_requests === 12) delete cfg.max_requests;
        this._config = cfg;
        this.dispatchEvent(new CustomEvent("config-changed", {detail: {config: cfg}, bubbles: true, composed: true}));
      });
      this.appendChild(this._form);
    }
    this._form.hass = this._hass;
    this._form.schema = EDITOR_SCHEMA;
    this._form.data = {sections: SECTIONS, metrics: METRICS, max_requests: 12, ...this._config};
  }
}

if (!customElements.get("strata-card")) customElements.define("strata-card", StrataCard);
if (!customElements.get("strata-card-editor")) customElements.define("strata-card-editor", StrataCardEditor);
window.customCards = window.customCards || [];
window.customCards.push({
  type: "strata-card",
  name: "Strata Monitor",
  description: "Strata server: model state, speed, GPU, context fill and recent requests.",
  preview: true,
  documentationURL: "https://github.com/steffenschlueter/strata-homeassitant-integration",
});
console.info(`%c STRATA-CARD %c ${CARD_VERSION} `, "background:#34d399;color:#052e20;font-weight:700", "background:#161a1d;color:#fff");
