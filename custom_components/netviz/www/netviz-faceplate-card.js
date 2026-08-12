/**
 * netviz faceplate card
 *
 * Takes its geometry from the `sensor.<device>_faceplate` attributes and the
 * live state from the other entities of the same device. Ports are collected by
 * their `port` and `metric` attributes, NOT by entity_id, so renaming an entity
 * breaks nothing.
 *
 * Lovelace:
 *   type: custom:netviz-faceplate-card
 *   device: <device_id>          # or:
 *   faceplate: sensor.sw_2540_faceplate
 *   title: SW-2540
 */

// The PoE indicator must not rely on hue alone: the previous #ff9f1c on a
// 10/100M port (#f2b632) was all but invisible. A deeper orange plus a dark
// outline reads equally well on green, amber, blue and grey.
const POE_COLOR = "#ff6d00";
const POE_OUTLINE = "rgba(0,0,0,0.75)";
const POE_DOT_R = 2.6;      // in the corner, next to the number
const POE_DOT_R_BIG = 4.5;  // centred, once the numbers are hidden and it is free

const LABEL_FONT_SIZE = 8;
// Below this rendered size the port numbers are mush - hide them and keep the
// colours and the tooltip. The switch's own web UI does the same when small.
const LABEL_MIN_PX = 5.5;

// A radio is drawn like a socket but coloured by what it is doing: serving
// clients, up and idle, or not running at all.
const RADIO_BUSY = "#3ec46d";
const RADIO_IDLE = "#2e7d4f";
const RADIO_DOWN = "var(--disabled-color, #6f7378)";

const LINK_COLORS = {
  down: "var(--disabled-color, #6f7378)",
  10: "#f2b632",
  100: "#f2b632",
  1000: "#3ec46d",
  2500: "#2ea3f2",
  5000: "#2ea3f2",
  10000: "#2ea3f2",
};

class NetvizFaceplateCard extends HTMLElement {
  // Deliberately without getConfigElement/getStubConfig: this card has no
  // visual editor, and returning `hui-generic-entity-row` hands back a row
  // element rather than an editor - that broke the editor, and the stub config
  // with an empty `faceplate` failed setConfig validation immediately. Without
  // these methods HA falls back to the YAML editor, which is correct.

  setConfig(config) {
    if (!config.device && !config.faceplate) {
      throw new Error("Set either 'device' or a 'faceplate' entity");
    }
    this._config = config;
    this._built = false;
    this.innerHTML = "";
  }

  getCardSize() {
    return 4;
  }

  set hass(hass) {
    this._hass = hass;
    const faceplate = this._findFaceplate();
    if (!faceplate) {
      this._renderError("Faceplate entity not found");
      return;
    }
    const geometry = faceplate.attributes;
    if (!geometry.ports || !geometry.ports.length) {
      this._renderError("No ports in the faceplate attributes");
      return;
    }
    if (!this._built || this._geometryId !== faceplate.entity_id) {
      this._build(geometry, faceplate.entity_id);
    }
    this._update();
  }

  /** Finds the faceplate entity from the config, or by device_id. */
  _findFaceplate() {
    const hass = this._hass;
    if (this._config.faceplate) {
      return hass.states[this._config.faceplate];
    }
    const entities = Object.values(hass.entities || {}).filter(
      (e) => e.platform === "netviz" && e.device_id === this._config.device
    );
    for (const entry of entities) {
      const state = hass.states[entry.entity_id];
      if (state && state.attributes && state.attributes.ports) return state;
    }
    return undefined;
  }

  /**
   * {port_id: {metric: entity_id}}, cached.
   *
   * HA calls `set hass` on ANY state change in the house, so a full scan of
   * hass.entities every time is expensive - on a 48 port switch that is 300+ of
   * our own entities plus everything else. The registry changes rarely, the
   * states change constantly.
   */
  _entityMap() {
    const hass = this._hass;
    const expected =
      Object.keys(this._portNodes || {}).length +
      Object.keys(this._radioNodes || {}).length;
    if (
      this._map &&
      this._mapSource === hass.entities &&
      Object.keys(this._map).length >= expected
    ) {
      return this._map;
    }
    const deviceId =
      this._config.device ||
      (hass.entities[this._faceplateId] || {}).device_id;
    const map = {};
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.platform !== "netviz") continue;
      if (deviceId && entry.device_id !== deviceId) continue;
      const state = hass.states[entry.entity_id];
      const { port, metric } = (state && state.attributes) || {};
      if (!port || !metric) continue;
      if (!map[port]) map[port] = {};
      map[port][metric] = entry.entity_id;
    }
    // Never cache an empty or partial map: at startup some states may not have
    // arrived yet, and then their attributes cannot be read.
    if (Object.keys(map).length >= expected && expected > 0) {
      this._mapSource = hass.entities;
      this._map = map;
    }
    return map;
  }

  /** Every netviz entity of this device, grouped by port and metric. */
  _portStates() {
    const hass = this._hass;
    const grouped = {};
    for (const [port, metrics] of Object.entries(this._entityMap())) {
      for (const [metric, entityId] of Object.entries(metrics)) {
        const state = hass.states[entityId];
        if (!state) continue;
        if (!grouped[port]) grouped[port] = {};
        grouped[port][metric] = state;
      }
    }
    return grouped;
  }

  _build(geometry, faceplateId) {
    this._faceplateId = faceplateId;
    this._geometryId = faceplateId;
    this._map = null;        // different device or geometry - drop the cache
    this._mapSource = null;
    const width = geometry.width || 800;
    const height = geometry.height || 100;

    const card = document.createElement("ha-card");
    if (this._config.title || geometry.display) {
      card.header = this._config.title || geometry.display;
    }

    // By default the faceplate scales to its container and there is no
    // scrollbar. `min_width` is there for anyone who wants full size and scroll.
    const minWidth = Number(this._config.min_width) || 0;
    const wrap = document.createElement("div");
    wrap.style.cssText =
      "padding:12px 16px 16px" + (minWidth ? ";overflow-x:auto" : "");

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", geometry.viewbox || `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    // Scale down to fit, but never blow a small faceplate up to fill the card:
    // an 11 port device is a quarter the width of a 52 port one, and stretched
    // to the same width its ports come out four times life size.
    const maxWidth = Math.round(width * 1.4);
    svg.style.cssText =
      "width:100%;height:auto;display:block;margin:0 auto" +
      (minWidth ? `;min-width:${minWidth}px` : `;max-width:${maxWidth}px`);
    this._viewBoxWidth = width;
    this._labels = [];

    const chassis = document.createElementNS("http://www.w3.org/2000/svg", "rect");
    chassis.setAttribute("x", "4");
    chassis.setAttribute("y", "4");
    chassis.setAttribute("width", String(width - 8));
    chassis.setAttribute("height", String(height - 8));
    chassis.setAttribute("rx", "6");
    chassis.setAttribute("fill", "var(--card-background-color, #1c1c1c)");
    chassis.setAttribute("stroke", "var(--divider-color, #444)");
    chassis.setAttribute("stroke-width", "1.5");
    svg.appendChild(chassis);

    this._portNodes = {};

    for (const port of geometry.ports) {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.style.cursor = "pointer";

      const body = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      body.setAttribute("x", port.x);
      body.setAttribute("y", port.y);
      body.setAttribute("width", port.w);
      body.setAttribute("height", port.h);
      body.setAttribute("rx", port.kind === "sfp+" ? "2" : "3");
      body.setAttribute("stroke", "var(--divider-color, #555)");
      body.setAttribute("stroke-width", "1");
      group.appendChild(body);

      // PoE indicator. Position and size are set by _applyPoeDotLayout, since
      // both depend on whether the numbers are visible.
      let poeDot = null;
      if (port.poe) {
        poeDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        poeDot.setAttribute("fill", "transparent");
        poeDot.setAttribute("stroke", "transparent");
        poeDot.setAttribute("stroke-width", "0.8");
        poeDot.setAttribute("pointer-events", "none");
        group.appendChild(poeDot);
      }

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", Number(port.x) + Number(port.w) / 2);
      label.setAttribute("y", Number(port.y) + Number(port.h) / 2 + 3);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", String(LABEL_FONT_SIZE));
      label.setAttribute("fill", "var(--primary-text-color, #eee)");
      label.setAttribute("pointer-events", "none");
      label.textContent = port.label;
      group.appendChild(label);
      this._labels.push(label);

      const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      group.appendChild(tooltip);

      group.addEventListener("click", () => this._openPort(port.id));
      svg.appendChild(group);
      this._portNodes[port.id] = { body, poeDot, tooltip, def: port };
    }

    this._radioNodes = {};
    for (const radio of geometry.radios || []) {
      const group = document.createElementNS("http://www.w3.org/2000/svg", "g");
      group.style.cursor = "pointer";

      const body = document.createElementNS("http://www.w3.org/2000/svg", "rect");
      body.setAttribute("x", radio.x);
      body.setAttribute("y", radio.y);
      body.setAttribute("width", radio.w);
      body.setAttribute("height", radio.h);
      body.setAttribute("rx", "9");
      body.setAttribute("stroke", "var(--divider-color, #555)");
      body.setAttribute("stroke-width", "1");
      group.appendChild(body);

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", Number(radio.x) + Number(radio.w) / 2);
      label.setAttribute("y", Number(radio.y) + Number(radio.h) / 2 + 3);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", String(LABEL_FONT_SIZE));
      label.setAttribute("fill", "var(--primary-text-color, #eee)");
      label.setAttribute("pointer-events", "none");
      label.textContent = radio.label;
      group.appendChild(label);
      this._labels.push(label);

      const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      group.appendChild(tooltip);
      group.addEventListener("click", () => this._openPort(radio.id));
      svg.appendChild(group);
      this._radioNodes[radio.id] = { body, tooltip, def: radio };
    }

    wrap.appendChild(svg);

    const legend = document.createElement("div");
    legend.style.cssText =
      "display:flex;gap:14px;flex-wrap:wrap;padding-top:10px;" +
      "font-size:12px;color:var(--secondary-text-color)";
    legend.innerHTML = [
      ["#3ec46d", "1G"],
      ["#2ea3f2", "10G"],
      ["#f2b632", "10/100M"],
      ["var(--disabled-color,#6f7378)", "down"],
    ]
      .map(
        ([color, text]) =>
          `<span style="display:inline-flex;align-items:center;gap:5px">
             <span style="width:10px;height:10px;border-radius:2px;background:${color}"></span>${text}
           </span>`
      )
      .join("") +
      `<span style="display:inline-flex;align-items:center;gap:5px">
         <span style="width:9px;height:9px;border-radius:50%;background:${POE_COLOR};
                      box-shadow:0 0 0 1px ${POE_OUTLINE}"></span>PoE
       </span>` +
      ((geometry.radios || []).length
        ? `<span style="display:inline-flex;align-items:center;gap:5px">
             <span style="width:14px;height:9px;border-radius:5px;background:${RADIO_BUSY}"></span>radio
           </span>
           <span style="display:inline-flex;align-items:center;gap:5px">
             <span style="width:14px;height:9px;border-radius:5px;background:${RADIO_IDLE}"></span>idle
           </span>`
        : "");
    wrap.appendChild(legend);

    this._summary = document.createElement("div");
    this._summary.style.cssText =
      "padding-top:6px;font-size:12px;color:var(--secondary-text-color)";
    wrap.appendChild(this._summary);

    card.appendChild(wrap);
    this.innerHTML = "";
    this.appendChild(card);
    // Initial position, so the dots are never left without coordinates if
    // ResizeObserver has not fired yet or is missing from the browser
    this._applyPoeDotLayout(true);
    this._observeLabels(svg);
    this._built = true;
  }

  /**
   * The port numbers scale with the SVG, and in a narrow column they turn
   * illegible. Better to drop them - the colours and the tooltip remain.
   */
  _observeLabels(svg) {
    const apply = () => {
      const rendered = svg.clientWidth || svg.getBoundingClientRect().width;
      if (!rendered || !this._viewBoxWidth) return;
      const px = (LABEL_FONT_SIZE * rendered) / this._viewBoxWidth;
      const show = px >= LABEL_MIN_PX;
      if (show === this._labelsShown) return;
      this._labelsShown = show;
      for (const label of this._labels) {
        label.style.display = show ? "" : "none";
      }
      this._applyPoeDotLayout(show);
    };
    this._labelsShown = undefined;
    if (this._resizeObserver) this._resizeObserver.disconnect();
    if (typeof ResizeObserver === "function") {
      this._resizeObserver = new ResizeObserver(apply);
      this._resizeObserver.observe(svg);
    }
    apply();
  }

  /**
   * With the numbers hidden the middle of the port is free, so the PoE dot moves
   * to the centre and grows. At small sizes a 2.6 unit dot in the corner would
   * scale down to about a pixel and a half and vanish, exactly as it used to
   * vanish against amber.
   */
  _applyPoeDotLayout(labelsShown) {
    for (const node of Object.values(this._portNodes || {})) {
      if (!node.poeDot) continue;
      const p = node.def;
      const corner = labelsShown;
      node.poeDot.setAttribute(
        "cx",
        corner ? Number(p.x) + Number(p.w) - 4 : Number(p.x) + Number(p.w) / 2
      );
      node.poeDot.setAttribute(
        "cy",
        corner ? Number(p.y) + Number(p.h) - 4 : Number(p.y) + Number(p.h) / 2
      );
      node.poeDot.setAttribute("r", String(corner ? POE_DOT_R : POE_DOT_R_BIG));
    }
  }

  disconnectedCallback() {
    if (this._resizeObserver) {
      this._resizeObserver.disconnect();
      this._resizeObserver = null;
    }
  }

  _update() {
    const states = this._portStates();
    let up = 0;
    let poeTotal = 0;

    for (const [portId, node] of Object.entries(this._portNodes)) {
      const metrics = states[portId] || {};
      const link = metrics.link;
      const isUp = link && link.state === "on";
      if (isUp) up += 1;

      let color = LINK_COLORS.down;
      if (isUp) {
        const speed = metrics.speed ? Number(metrics.speed.state) : 0;
        color = LINK_COLORS[speed] || "#3ec46d";
      }
      node.body.setAttribute("fill", color);

      if (node.poeDot) {
        const poe = metrics.poe_power ? Number(metrics.poe_power.state) : 0;
        const delivering =
          metrics.poe_status && metrics.poe_status.state === "delivering";
        const on = delivering || poe > 0;
        node.poeDot.setAttribute("fill", on ? POE_COLOR : "transparent");
        node.poeDot.setAttribute("stroke", on ? POE_OUTLINE : "transparent");
        if (!Number.isNaN(poe)) poeTotal += poe;
      }

      // def.name is the full interface name when the label had to be shortened
      const lines = [`Port ${node.def.name || node.def.label}`];
      if (link && link.attributes.description) {
        lines.push(link.attributes.description);
      }
      lines.push(isUp ? "up" : "down");
      if (isUp && metrics.speed) lines.push(`${metrics.speed.state} Mbit/s`);
      if (metrics.rx_rate && metrics.tx_rate) {
        lines.push(`RX ${metrics.rx_rate.state} / TX ${metrics.tx_rate.state} Mbit/s`);
      }
      if (metrics.poe_power && Number(metrics.poe_power.state) > 0) {
        lines.push(`PoE ${metrics.poe_power.state} W`);
      }
      if (link && link.attributes.vlans) {
        lines.push(`VLAN ${link.attributes.vlans.join(", ")}`);
      }
      node.tooltip.textContent = lines.join(" · ");
    }

    let radioClients = 0;
    for (const [radioId, node] of Object.entries(this._radioNodes || {})) {
      const state = (states[radioId] || {}).radio;
      const attrs = (state && state.attributes) || {};
      const clients = state ? Number(state.state) : NaN;
      const up = attrs.up !== false;

      let colour = RADIO_DOWN;
      if (state && up) colour = clients > 0 ? RADIO_BUSY : RADIO_IDLE;
      node.body.setAttribute("fill", colour);
      if (Number.isFinite(clients)) radioClients += clients;

      const lines = [attrs.interface || node.def.label];
      if (attrs.ssid) lines.push(attrs.ssid);
      lines.push(up ? "up" : "down");
      if (Number.isFinite(clients)) {
        lines.push(`${clients} client${clients === 1 ? "" : "s"}`);
      }
      if (attrs.signal_avg != null) lines.push(`avg ${attrs.signal_avg} dBm`);
      if (attrs.noise_floor != null) lines.push(`noise ${attrs.noise_floor} dBm`);
      if (attrs.quality != null) lines.push(`CCQ ${attrs.quality}%`);
      node.tooltip.textContent = lines.join(" · ");
    }

    const total = Object.keys(this._portNodes).length;
    this._summary.textContent =
      `${up}/${total} up` +
      (poeTotal > 0 ? ` · PoE ${poeTotal.toFixed(1)} W` : "") +
      (Object.keys(this._radioNodes || {}).length
        ? ` · ${radioClients} wireless`
        : "");
  }

  /** Clicking a port opens the more-info dialog of its link entity. */
  _openPort(portId) {
    const states = this._portStates()[portId];
    if (states && states.radio) {
      const event = new Event("hass-more-info", { bubbles: true, composed: true });
      event.detail = { entityId: states.radio.entity_id };
      this.dispatchEvent(event);
      return;
    }
    if (!states) return;
    const target = states.link || Object.values(states)[0];
    if (!target) return;
    const event = new Event("hass-more-info", { bubbles: true, composed: true });
    event.detail = { entityId: target.entity_id };
    this.dispatchEvent(event);
  }

  _renderError(message) {
    if (this._errorShown === message) return;
    this._errorShown = message;
    this.innerHTML = `<ha-card><div style="padding:16px;color:var(--error-color)">${message}</div></ha-card>`;
    this._built = false;
  }
}

customElements.define("netviz-faceplate-card", NetvizFaceplateCard);

window.customCards = window.customCards || [];
window.customCards.push({
  type: "netviz-faceplate-card",
  name: "netviz Faceplate",
  description: "Switch faceplate with link, speed and PoE state",
  preview: false,
});

console.info("%c netviz-faceplate-card %c 0.4.1 ", "background:#2ea3f2;color:#fff", "");
