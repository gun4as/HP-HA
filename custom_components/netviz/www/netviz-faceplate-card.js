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

// PoE indikators nedrīkst balstīties tikai uz toni: iepriekšējais #ff9f1c uz
// 10/100M porta (#f2b632) bija praktiski neredzams. Dziļāks oranžs plus tumša
// kontūra nolasās uz zaļa, dzintara, zila un pelēka vienādi labi.
const POE_COLOR = "#ff6d00";
const POE_OUTLINE = "rgba(0,0,0,0.75)";
const POE_DOT_R = 2.6;      // stūrī, blakus numuram
const POE_DOT_R_BIG = 4.5;  // centrā, kad numuri ir paslēpti un vieta ir brīva

const LABEL_FONT_SIZE = 8;
// Zem šī izmēra pikseļos portu numuri ir tikai putra - tad tos slēpjam, un
// paliek krāsas un tooltip. Tāpat dara switch'a paša web saskarne mazā izmērā.
const LABEL_MIN_PX = 5.5;

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
  // Apzināti bez getConfigElement/getStubConfig: vizuālā redaktora šai kartei
  // nav, un `hui-generic-entity-row` atgriešana ir rindas elements, nevis
  // redaktors - tas salauza redaktoru, un stub konfigurācija ar tukšu
  // `faceplate` uzreiz krita setConfig validācijā. Bez šīm metodēm HA korekti
  // atkāpjas uz YAML redaktoru.

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

  /**
   * {porta_id: {metrika: entity_id}}, keširots.
   *
   * `set hass` HA izsauc pie JEBKURAS stāvokļa maiņas mājā, tāpēc pilns
   * hass.entities skenējums katrā reizē ir dārgs - uz 48 portu switch'a tur ir
   * 300+ mūsu entītiju plus viss pārējais. Reģistrs mainās reti, stāvokļi bieži.
   */
  _entityMap() {
    const hass = this._hass;
    const expected = Object.keys(this._portNodes || {}).length;
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
    // Tukšu vai nepilnu karti nekešojam: startējot daļa stāvokļu vēl var nebūt
    // ienākuši, un tad atribūtu pēc tiem nevar nolasīt.
    if (Object.keys(map).length >= expected && expected > 0) {
      this._mapSource = hass.entities;
      this._map = map;
    }
    return map;
  }

  /** Visas šīs ierīces netviz entītijas, sagrupētas pēc porta un metrikas. */
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
    this._map = null;        // cita ierīce vai cita ģeometrija - keša ārā
    this._mapSource = null;
    const width = geometry.width || 800;
    const height = geometry.height || 100;

    const card = document.createElement("ha-card");
    if (this._config.title || geometry.display) {
      card.header = this._config.title || geometry.display;
    }

    // Pēc noklusējuma faceplate mērogojas pēc konteinera un ritjoslas nav.
    // `min_width` ir izvēle tiem, kas grib pilnu izmēru un ritināšanu.
    const minWidth = Number(this._config.min_width) || 0;
    const wrap = document.createElement("div");
    wrap.style.cssText =
      "padding:12px 16px 16px" + (minWidth ? ";overflow-x:auto" : "");

    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("viewBox", geometry.viewbox || `0 0 ${width} ${height}`);
    svg.setAttribute("preserveAspectRatio", "xMidYMid meet");
    svg.style.cssText =
      "width:100%;height:auto;display:block" +
      (minWidth ? `;min-width:${minWidth}px` : "");
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

      // PoE indikators. Pozīciju un izmēru uzstāda _applyPoeDotLayout, jo tas
      // atkarīgs no tā, vai numuri ir redzami.
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
       </span>`;
    wrap.appendChild(legend);

    this._summary = document.createElement("div");
    this._summary.style.cssText =
      "padding-top:6px;font-size:12px;color:var(--secondary-text-color)";
    wrap.appendChild(this._summary);

    card.appendChild(wrap);
    this.innerHTML = "";
    this.appendChild(card);
    // Sākotnējā pozīcija, lai punkti nav bez koordinātām, ja ResizeObserver
    // vēl nav nostrādājis vai to pārlūkā nav
    this._applyPoeDotLayout(true);
    this._observeLabels(svg);
    this._built = true;
  }

  /**
   * Portu numuri mērogojas kopā ar SVG, un šaurā kolonnā tie kļūst
   * nesalasāmi. Tad tos labāk noņemt - krāsas un tooltip paliek.
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
   * Kad numuri ir paslēpti, porta vidus ir brīvs - tad PoE punkts iet uz centru
   * un kļūst lielāks. Mazā izmērā 2.6 vienību punkts stūrī izmērogotos uz
   * pusotra pikseļa un pazustu tāpat kā iepriekš pazuda uz dzintara.
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

console.info("%c netviz-faceplate-card %c 0.2.3 ", "background:#2ea3f2;color:#fff", "");
