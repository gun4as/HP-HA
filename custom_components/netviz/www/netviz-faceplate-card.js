/**
 * netviz faceplate card
 *
 * Ģeometriju ņem no `sensor.<ierīce>_faceplate` atribūtiem, stāvokli - no pārējām
 * tās pašas ierīces entītijām. Portus savāc pēc `port` un `metric` atribūtiem,
 * NEVIS pēc entity_id nosaukuma, tāpēc pārsaukšana neko nesalauž.
 *
 * Lovelace:
 *   type: custom:netviz-faceplate-card
 *   device: <device_id>          # vai:
 *   faceplate: sensor.sw_2540_faceplate
 *   title: SW-2540
 */

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
  static getConfigElement() {
    return document.createElement("hui-generic-entity-row");
  }

  static getStubConfig() {
    return { faceplate: "" };
  }

  setConfig(config) {
    if (!config.device && !config.faceplate) {
      throw new Error("Norādi vai nu 'device', vai 'faceplate' entītiju");
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
      this._renderError("Faceplate entītija nav atrasta");
      return;
    }
    const geometry = faceplate.attributes;
    if (!geometry.ports || !geometry.ports.length) {
      this._renderError("Faceplate atribūtos nav portu");
      return;
    }
    if (!this._built || this._geometryId !== faceplate.entity_id) {
      this._build(geometry, faceplate.entity_id);
    }
    this._update();
  }

  /** Atrod faceplate entītiju pēc konfigurācijas vai pēc device_id. */
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

  /** Visas šīs ierīces netviz entītijas, sagrupētas pēc porta un metrikas. */
  _portStates() {
    const hass = this._hass;
    const deviceId =
      this._config.device ||
      (hass.entities[this._faceplateId] || {}).device_id;
    const grouped = {};
    for (const entry of Object.values(hass.entities || {})) {
      if (entry.platform !== "netviz") continue;
      if (deviceId && entry.device_id !== deviceId) continue;
      const state = hass.states[entry.entity_id];
      if (!state) continue;
      const { port, metric } = state.attributes || {};
      if (!port || !metric) continue;
      if (!grouped[port]) grouped[port] = {};
      grouped[port][metric] = state;
    }
    return grouped;
  }

  _build(geometry, faceplateId) {
    this._faceplateId = faceplateId;
    this._geometryId = faceplateId;
    const width = geometry.width || 800;
    const height = geometry.height || 100;

    const card = document.createElement("ha-card");
    if (this._config.title || geometry.display) {
      card.header = this._config.title || geometry.display;
    }

    const wrap = document.createElement("div");
    wrap.style.cssText = "padding:12px 16px 16px;overflow-x:auto";

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", geometry.viewbox || `0 0 ${width} ${height}`);
    svg.setAttribute("width", "100%");
    svg.style.cssText = `min-width:${Math.round(width * 0.75)}px;display:block`;

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

      // PoE indikators - mazs punkts porta apakšējā labajā stūrī
      let poeDot = null;
      if (port.poe) {
        poeDot = document.createElementNS("http://www.w3.org/2000/svg", "circle");
        poeDot.setAttribute("cx", Number(port.x) + Number(port.w) - 4);
        poeDot.setAttribute("cy", Number(port.y) + Number(port.h) - 4);
        poeDot.setAttribute("r", "2");
        poeDot.setAttribute("fill", "transparent");
        group.appendChild(poeDot);
      }

      const label = document.createElementNS("http://www.w3.org/2000/svg", "text");
      label.setAttribute("x", Number(port.x) + Number(port.w) / 2);
      label.setAttribute("y", Number(port.y) + Number(port.h) / 2 + 3);
      label.setAttribute("text-anchor", "middle");
      label.setAttribute("font-size", "8");
      label.setAttribute("fill", "var(--primary-text-color, #eee)");
      label.setAttribute("pointer-events", "none");
      label.textContent = port.label;
      group.appendChild(label);

      const tooltip = document.createElementNS("http://www.w3.org/2000/svg", "title");
      group.appendChild(tooltip);

      group.addEventListener("click", () => this._openPort(port.id));
      svg.appendChild(group);
      this._portNodes[port.id] = { body, poeDot, tooltip, def: port };
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
      .join("");
    wrap.appendChild(legend);

    this._summary = document.createElement("div");
    this._summary.style.cssText =
      "padding-top:6px;font-size:12px;color:var(--secondary-text-color)";
    wrap.appendChild(this._summary);

    card.appendChild(wrap);
    this.innerHTML = "";
    this.appendChild(card);
    this._built = true;
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
        node.poeDot.setAttribute(
          "fill",
          delivering || poe > 0 ? "#ff9f1c" : "transparent"
        );
        if (!Number.isNaN(poe)) poeTotal += poe;
      }

      const lines = [`Ports ${node.def.label}`];
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

    const total = Object.keys(this._portNodes).length;
    this._summary.textContent =
      `${up}/${total} aktīvi` +
      (poeTotal > 0 ? ` · PoE ${poeTotal.toFixed(1)} W` : "");
  }

  /** Klikšķis uz porta atver link entītijas more-info dialogu. */
  _openPort(portId) {
    const states = this._portStates()[portId];
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
  description: "Switch priekšpanelis ar link, ātruma un PoE stāvokli",
  preview: false,
});

console.info("%c netviz-faceplate-card %c 0.1.0 ", "background:#2ea3f2;color:#fff", "");
