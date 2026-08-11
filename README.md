# netviz

Managed network device visualisation for Home Assistant. The SNMP polling happens
inside HA itself — no MQTT, no separate container, no add-on.

Read-only. No SNMP SET anywhere — a read-only community or an SNMPv3 user is
enough.

*Latviski: [README.lv.md](README.lv.md)*

## What is in it

- Config flow with SNMPv2c and v3 (SHA/MD5 + AES/AES192/AES256/DES)
- One device per switch, entities per port: link, speed, RX/TX, PoE power,
  PoE status, PVID, description
- System sensors: CPU, uptime, PoE consumption and budget, ports up
- A faceplate Lovelace card that the integration registers by itself
- Ports are discovered from the device, so nothing has to be described in
  advance; a model file is optional and adds faceplate geometry

## Which devices

Ports, link state, speed, throughput and descriptions come from standard MIBs and
work on anything that answers SNMP. Everything beyond that is vendor-specific, so
netviz picks a **profile** from `sysObjectID` and only reads what that vendor
actually implements.

| | ArubaOS-Switch | MikroTik RouterOS | anything else |
|---|---|---|---|
| Ports, link, speed, RX/TX | yes | yes | yes |
| Port descriptions | `ifAlias` | `ifName` | both |
| PVID per port | yes | yes | yes |
| VLAN membership, access vs trunk | yes | no | if Q-BRIDGE is filled |
| PoE per port | yes, milliwatts | yes, units unverified | no |
| PoE budget and consumption | yes | no | no |
| CPU | yes | yes, averaged over cores | no |
| Serial number as unique_id | ENTITY-MIB chassis row | `mtxrSerialNumber` | ENTITY-MIB if present |

An unrecognised vendor gets the last column and no guesses. Reading a private OID
that belongs to somebody else and reporting the resulting zero as a measurement is
worse than reporting nothing.

Tested against an Aruba 2540-48G-PoE+-4SFP+ (JL357A) on ArubaOS-Switch 16.11, and
against RouterOS 7.20–7.21 on a hAP ac³, two cAP ac and an RB2011UiAS.

### Known gaps on RouterOS

- **PoE power units are unverified.** Every MikroTik available for testing had one
  PoE-out port with nothing plugged into it, so voltage, current and power all
  read zero and the divisor could not be confirmed. It is marked as an assumption
  in `profiles.py`. If your reading looks wrong by a factor of ten, that is why.
- **VLAN membership is unavailable.** RouterOS fills `dot1qPvid` but leaves
  `dot1qVlanStaticEgressPorts` empty, so netviz reports the PVID and says nothing
  about access versus trunk rather than guessing. This was confirmed on a router
  and three access points; a CRS switch with bridge VLAN filtering may well
  populate the table, and the profile would then be wrong to assume otherwise.
- **Wireless needs the controller.** A managed access point answers almost
  nothing about its own radios, so pointing netviz at one gives ports and no
  wireless. Point it at the CAPsMAN controller instead and it covers every AP.

## Installing through HACS

1. HACS → three dots → **Custom repositories**
2. URL: `https://github.com/gun4as/HP-HA`, category **Integration**
3. Install **netviz**, restart Home Assistant
4. **Settings → Devices & services → Add integration → netviz**

Leave the model on **Detect ports automatically** unless a model file exists for
your exact hardware.

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
   `/netviz/netviz-faceplate-card.js`, type **JavaScript Module**. Note that a
   manual resource has no cache-busting query string, so it will keep serving the
   old file after an update — remove it once the automatic registration works.

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

Read-only access is enough. ArubaOS-Switch:

```
snmp-server community "netviz" operator restricted
```

SNMPv3 on AOS-S (recommended):

```
snmpv3 enable
snmpv3 user netviz auth sha <authpass> priv aes <privpass>
snmpv3 group managerpriv user netviz sec-model ver3
```

RouterOS ships with SNMP disabled. A community restricted to the Home Assistant
host:

```
/snmp community add name=netviz addresses=<ha-ip>/32 read-access=yes write-access=no
/snmp set enabled=yes
```

If it still does not answer, check the input chain — a default firewall will drop
UDP 161 before it reaches the service:

```
/ip firewall filter print where chain=input
```

The options (integration card → **Configure**) let you change the poll interval,
turn individual metrics on and off, read or skip VLAN information, and pick
whether the device page links to the device over http or https.

## Entity count — read this before enabling everything

On a JL357A:

| Enabled | Entities |
|---|---|
| Default (link, speed, RX, TX, PoE power, PoE status) | **310** |
| Everything (`ALL_METRICS`) | **518** |

Every metric multiplies by the port count, so a five-port router is nothing to
worry about and a 48-port switch is. If the recorder starts to struggle, drop
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

A switch faceplate is long and low — on a JL357A the aspect ratio is close to 9:1.
The card needs width, otherwise the ports end up tiny. In a sections dashboard,
give it a full row:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
grid_options:
  columns: full
```

The card scales to its container and has no scrollbar. It will not magnify a
small faceplate past 1.4× its natural size, so a five-port router does not fill a
dashboard. Port labels are hidden when they would render below about 5.5px — under
roughly 615px of card width on a 52 port chassis — and the colours and the tooltip
stay. If you would rather have full size with horizontal scrolling, set
`min_width`:

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
middle of the port once the labels are hidden. Clicking a port opens its
more-info dialog.

### Without a model file

Discovered ports are laid out automatically: left to right in the order the
device reported them, wrapping to a second row past six, each port sized to fit
its label. Interface names are shortened to their port token, because on RouterOS
a name like `ether1uplink dsl` is three times the width of the port it labels and
adjacent labels overlap into nonsense; the full name stays in the tooltip.

That drawing is a **port list, not a chassis**. It cannot know where an SFP cage
physically sits or how a front panel is numbered, and it marks itself `generated`
in the geometry. A model file is what turns it into a picture of real hardware.

## Model files

A model file is optional. It contributes faceplate geometry and nothing else —
the ports themselves always come from the device.

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

Nothing else is needed — no Home Assistant install, no network. `snmp.py`,
`model.py` and `profiles.py` import no HA, and the tests load them straight from
their files, so a real `SnmpClient` runs with only `walk()` and `get_many()` fed
from a recorded snapshot. Everything above those two methods is the production
code path.

Three snapshots, from a JL357A, a MikroTik RB2011 and a CAPsMAN controller. They
disagree in useful ways, and every disagreement below produced a wrong answer
that looked like a right one until a test pinned it:

- the RB2011 leaves the Q-BRIDGE egress table empty while filling `dot1qPvid`,
  which made every port come out as `access`, trunks included
- it answers `entPhysicalSerialNum` with `rb400_usb` from a row whose
  `entPhysicalClass` is `unknown` — a string identical on every RB2011, which
  would have collided two devices onto one unique_id
- `hrProcessorLoad` returns one value on one device and four on another, on the
  same firmware version
- `sysObjectID` arrives as `SNMPv2-SMI::enterprises.11...` rather than the dotted
  form, because pysnmp renders OIDs through its MIBs

The tests never touch hardware — they run against snapshots taken from real
devices and then scrubbed. Two steps, and the second one is mandatory:

```bash
python3 tools/capture_fixture.py 192.0.2.10 public tests/fixtures/mine-live.json
python3 tools/sanitize_fixture.py tests/fixtures/mine-live.json tests/fixtures/mine.json
```

A raw snapshot contains the hostname, chassis and module serial numbers, port
descriptions naming actual devices, VLAN names, SSIDs and the MAC address of
every wireless client. `sanitize_fixture.py` replaces all of it, leaves every
numeric value untouched, and finishes with an audit that fails if a private IP or
MAC address survived. `*-live.json` is in `.gitignore`, so the raw version cannot
be committed by accident.

## OIDs used

Standard MIBs, read on every device:

| What | OID | MIB |
|---|---|---|
| ifName / ifAlias | `1.3.6.1.2.1.31.1.1.1.1` / `.18` | IF-MIB |
| ifType — how physical ports are found | `1.3.6.1.2.1.2.2.1.3` | IF-MIB |
| ifOperStatus / ifAdminStatus | `1.3.6.1.2.1.2.2.1.8` / `.7` | IF-MIB |
| ifHighSpeed | `1.3.6.1.2.1.31.1.1.1.15` | IF-MIB |
| ifHCInOctets / ifHCOutOctets | `1.3.6.1.2.1.31.1.1.1.6` / `.10` | IF-MIB |
| sysObjectID — how the profile is chosen | `1.3.6.1.2.1.1.2.0` | SNMPv2-MIB |
| entPhysicalClass / SerialNum | `1.3.6.1.2.1.47.1.1.1.1.5` / `.11` | ENTITY-MIB |
| dot1dBasePortIfIndex | `1.3.6.1.2.1.17.1.4.1.2` | BRIDGE-MIB |
| dot1qPvid | `1.3.6.1.2.1.17.7.1.4.5.1.1` | Q-BRIDGE-MIB |
| dot1qVlanStaticEgress / Untagged | `1.3.6.1.2.1.17.7.1.4.3.1.2` / `.4` | Q-BRIDGE-MIB |

ArubaOS-Switch:

| What | OID | MIB |
|---|---|---|
| pethPsePortDetectionStatus | `1.3.6.1.2.1.105.1.1.1.6` | POWER-ETHERNET-MIB |
| pethMainPsePower / Consumption | `1.3.6.1.2.1.105.1.3.1.1.2` / `.4` | POWER-ETHERNET-MIB |
| hpicfPoePethPsePortActualPower | `1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8` | HP-ICF-POE-MIB (**mW**) |
| hpSwitchCpuStat | `1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0` | STATISTICS-MIB |
| hpLocalMemFree / AllocBytes | `...5.1.1.2.1.1.1.6.1` / `.7.1` | NETSWITCH-MIB |

MikroTik RouterOS:

| What | OID | MIB |
|---|---|---|
| mtxrSerialNumber | `1.3.6.1.4.1.14988.1.1.7.3.0` | MIKROTIK-MIB |
| mtxrPOEStatus / Power | `1.3.6.1.4.1.14988.1.1.15.1.1.3` / `.6` | MIKROTIK-MIB |
| hrProcessorLoad | `1.3.6.1.2.1.25.3.3.1.2` | HOST-RESOURCES-MIB |
| hrStorage — memory | `1.3.6.1.2.1.25.2.3.1.3` … `.6` | HOST-RESOURCES-MIB |
| CAPsMAN registrations | `1.3.6.1.4.1.14988.1.1.1.5` | MIKROTIK-MIB |

HP-ICF-POE-MIB: <https://mibs.observium.org/mib/HP-ICF-POE-MIB/>
AOS-S 16.11: <https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/YAYB/content/common%20files/vie-poe-sta-spe-por.htm>

## Wireless, on a CAPsMAN controller

Point netviz at the controller rather than at the access points. A managed AP
answers almost nothing about its own radios — the controller holds the lot — so
one device covers the whole estate, including the APs that look broken when
asked directly.

You get a total client count, a sensor per SSID, and a sensor per radio of per
access point, each carrying average, minimum and maximum signal as attributes.
The per-radio sensors are disabled by default, because a controller with several
APs produces a lot of them.

**Aggregates only, deliberately.** The registration table is keyed by client MAC
address. Turning those into entities would be tracking everyone in the building,
Home Assistant already has a MikroTik integration that does device tracking, and
this is not it. A test asserts that no MAC address can reach an entity.

## Not there yet

- Memory sensors, although memory is already polled on both vendors
- LLDP neighbours (LLDP-MIB `1.0.8802.1.1.2.1.4.1.1`)
- MAC table per port (`dot1dTpFdbPort`)
- A visual editor for the card (YAML only for now)
- An overall timeout around one poll cycle

## Licence

[MIT](LICENSE).

An independent implementation. Not derived from Switch Vision — that has no
open-source licence, so neither code nor artwork was taken from it.
