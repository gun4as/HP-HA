# netviz

Managed network switch visualisation for Home Assistant. The SNMP polling happens
inside HA itself — no MQTT, no separate container, no add-on.

First model: **Aruba 2540-48G-PoE+-4SFP+ (JL357A)**, ArubaOS-Switch 16.x.

Read-only. No SNMP SET anywhere — a read-only community or v3 user is enough.

*Latviski: [README.lv.md](README.lv.md)*

## What is in it

- Config flow with SNMPv2c and v3 (SHA/MD5 + AES/AES192/AES256/DES)
- One device per switch, entities per port: link, speed, RX/TX, PoE power,
  PoE status, PVID, description
- System sensors: CPU, uptime, PoE consumption and budget, ports up
- A faceplate Lovelace card that the integration registers by itself
- The model definition lives in a JSON file — a new switch model is not a code
  change

## Installing through HACS

1. HACS → three dots → **Custom repositories**
2. URL: `https://github.com/gun4as/HP-HA`, category **Integration**
3. Install **netviz**, restart Home Assistant
4. **Settings → Devices & services → Add integration → netviz**

You do **not** need to add the card to the Lovelace resources by hand — the
integration registers it through `add_extra_js_url`. If after a restart the card
still reports `Custom element doesn't exist: netviz-faceplate-card`, check in
this order:

1. Is the file reachable: `http://<your-ha>:8123/netviz/netviz-faceplate-card.js`.
   A 404 means HACS did not download the `www/` directory — redownload the
   integration.
2. `Ctrl+Shift+R` in the browser. The resource list is cached, and a new script
   only shows up after a full reload.
3. If the file opens but the card is still missing, add the resource by hand:
   **Settings → Dashboards → three dots → Resources → Add**, URL
   `/netviz/netviz-faceplate-card.js`, type **JavaScript Module**.

### Icon

The integration carries its own brand images in
`custom_components/netviz/brand/`, which Home Assistant 2026.3 and later serve
from `/api/brands/integration/netviz/icon.png`, ahead of the CDN. No pull request
against [home-assistant/brands](https://github.com/home-assistant/brands) is
involved — its `custom_integrations` folder is marked legacy now. On older HA the
directory is ignored and HACS shows its generated placeholder.

The artwork is generated, not hand-drawn, so it can be adjusted and re-rendered:

```bash
pip install Pillow
python tools/gen_brand.py
```

It reuses the card's colour language — green 1G, blue 10G, amber 10/100M, grey
down, orange PoE — so the icon, the faceplate and the docs all say the same thing.

### Dependencies

`manifest.json` pins `pysnmp==7.1.27` — exactly the version HA Core already ships
for its built-in `snmp` and `brother` integrations. Installing therefore downloads
nothing extra and cannot create a version conflict.

## Configuration

Read-only access is enough on the switch side. AOS-S:

```
snmp-server community "netviz" operator restricted
```

SNMPv3 (recommended):

```
snmpv3 enable
snmpv3 user netviz auth sha <authpass> priv aes <privpass>
snmpv3 group managerpriv user netviz sec-model ver3
```

The options (integration card → **Configure**) let you change the poll interval,
turn individual metrics on and off, read or skip VLAN information, and pick
whether the device page links to the switch over http or https.

## Entity count — read this before enabling everything

On a JL357A:

| Enabled | Entities |
|---|---|
| Default (link, speed, RX, TX, PoE power, PoE status) | **310** |
| Everything (`ALL_METRICS`) | **518** |

Every metric multiplies by 52 ports. If the recorder starts to struggle, drop
`rx_rate` and `tx_rate` from the options and keep them only where the history is
genuinely useful, or exclude the port sensors in the recorder config:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_rx_total
      - sensor.*_tx_total
```

## Faceplate card

```yaml
type: custom:netviz-faceplate-card
device: <device_id>
title: SW-2540
```

or without a device_id:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
```

A faceplate is long and low — on a JL357A the aspect ratio is close to 9:1. The
card needs width, otherwise the ports end up tiny. In a sections dashboard, give
it a full row:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
grid_options:
  columns: full
```

The card scales to its container and has no scrollbar. Port numbers are hidden
when they would render below about 5.5px — under roughly 615px of card width on a
52 port chassis. The colours and the tooltip stay. If you would rather have full
size with horizontal scrolling, set `min_width`:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
min_width: 820
```

The card takes its geometry from the `faceplate` entity attributes and the live
state from the other entities of the same device. It collects ports by their
`port` and `metric` attributes, **not** by entity_id — renaming breaks nothing.

Colours: green 1G, blue 10G, amber 10/100M, grey down. An orange dot means the
port is delivering PoE; it sits in the corner at normal size and moves to the
middle of the port once the numbers are hidden. Clicking a port opens its
more-info dialog.

## A new switch model

```bash
python3 tools/gen_model.py --rj45 48 --sfp 4 --numbering column --sfp-side left \
  -o custom_components/netviz/models/myswitch.json
```

The generated model assumes the port `ifName` is its number and that the PoE
index is `1.<port>`. Verify against the hardware:

```bash
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.31.1.1.1.1
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.105.1.1.1.6
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8
```

If they do not line up, fix `ifname` or add an explicit `ifindex` to each port.
Two more assumptions are purely visual: the numbering across the faceplate (odd
on top, even below — `--numbering row` if your chassis differs) and which side
the SFP+ cage sits on (`--sfp-side right`). Both are worth checking against a
photo of the actual front panel.

The SNMP layer runs on its own, without HA. Run the file directly rather than
with `-m`: `-m` would import the parent package, hence `__init__.py`, hence all
of Home Assistant.

```bash
python3 custom_components/netviz/snmp.py 192.0.2.10 public
```

## Testing

```bash
pip install -r requirements_test.txt
pytest
```

Nothing else is needed — no Home Assistant install, no network. `snmp.py` and
`model.py` import no HA, and the tests load them straight from their files, so a
real `SnmpClient` runs with only `walk()` and `get_many()` fed from a recorded
snapshot. Everything above those two methods is the production code path.

The snapshots come from a JL357A and a MikroTik RB2011, and the two devices
disagree in useful ways: the RB2011 leaves the Q-BRIDGE egress table empty while
filling `dot1qPvid`, and answers `entPhysicalSerialNum` with `rb400_usb` from a
row whose `entPhysicalClass` is `unknown`. Both cases are pinned by tests,
because both produced a wrong answer that looked like a right one.

The tests never touch hardware — they run against a snapshot taken from a real
switch and then scrubbed. Two steps, and the second one is mandatory:

```bash
python3 tools/capture_fixture.py 192.0.2.10 public tests/fixtures/mine-live.json
python3 tools/sanitize_fixture.py tests/fixtures/mine-live.json tests/fixtures/mine.json
```

A raw snapshot contains the hostname, the chassis and SFP module serial numbers,
port descriptions naming actual devices, and VLAN names. `sanitize_fixture.py`
replaces all of it, leaves every numeric value untouched, and finishes with an
audit that fails if a private IP or MAC address survived. `*-live.json` is in
`.gitignore`, so the raw version cannot be committed by accident.

The bundled `tests/fixtures/jl357a.json` is exactly such a scrubbed snapshot from
a JL357A with 52 ports, 22 links up, six PoE consumers and eight VLANs.

## OIDs used

| What | OID | MIB |
|---|---|---|
| ifName / ifAlias | `1.3.6.1.2.1.31.1.1.1.1` / `.18` | IF-MIB |
| ifOperStatus / ifAdminStatus | `1.3.6.1.2.1.2.2.1.8` / `.7` | IF-MIB |
| ifHighSpeed | `1.3.6.1.2.1.31.1.1.1.15` | IF-MIB |
| ifHCInOctets / ifHCOutOctets | `1.3.6.1.2.1.31.1.1.1.6` / `.10` | IF-MIB |
| pethPsePortDetectionStatus | `1.3.6.1.2.1.105.1.1.1.6` | POWER-ETHERNET-MIB |
| pethMainPsePower / Consumption | `1.3.6.1.2.1.105.1.3.1.1.2` / `.4` | POWER-ETHERNET-MIB |
| hpicfPoePethPsePortActualPower | `1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8` | HP-ICF-POE-MIB (**mW**) |
| hpSwitchCpuStat | `1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0` | STATISTICS-MIB |
| entPhysicalSerialNum | `1.3.6.1.2.1.47.1.1.1.1.11` | ENTITY-MIB |
| dot1dBasePortIfIndex | `1.3.6.1.2.1.17.1.4.1.2` | BRIDGE-MIB |
| dot1qPvid | `1.3.6.1.2.1.17.7.1.4.5.1.1` | Q-BRIDGE-MIB |
| dot1qVlanStaticEgress / Untagged | `1.3.6.1.2.1.17.7.1.4.3.1.2` / `.4` | Q-BRIDGE-MIB |

HP-ICF-POE-MIB: <https://mibs.observium.org/mib/HP-ICF-POE-MIB/>
AOS-S 16.11: <https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/YAYB/content/common%20files/vie-poe-sta-spe-por.htm>

## Not there yet

- LLDP neighbours (LLDP-MIB `1.0.8802.1.1.2.1.4.1.1`)
- MAC table per port (`dot1dTpFdbPort`)
- A visual editor for the card (YAML only for now)
- Memory sensors, although `hpLocalMemFreeBytes` and `hpLocalMemAllocBytes` are
  already polled
- An overall timeout around one poll cycle

## Licence

[MIT](LICENSE).

An independent implementation. Not derived from Switch Vision — that has no
open-source licence, so neither code nor artwork was taken from it.
