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
| PoE per port | yes, milliwatts | status only, see below | no |
| PoE budget and consumption | yes | no | no |
| CPU | yes | yes, averaged over cores | no |
| Serial number as unique_id | ENTITY-MIB chassis row | `mtxrSerialNumber` | ENTITY-MIB if present |

An unrecognised vendor gets the last column and no guesses. Reading a private OID
that belongs to somebody else and reporting the resulting zero as a measurement is
worse than reporting nothing.

Tested against an Aruba 2540-48G-PoE+-4SFP+ (JL357A) on ArubaOS-Switch 16.11, and
against RouterOS 7.20–7.22 on eight devices: a hAP ac³, two cAP ac, two RB2011UiAS,
an RB951G, a CRS309-1G-8S+ and a CRS112-8G-4S.

### Known gaps on RouterOS

- **PoE power is not measured on passive PoE-out.** An RB2011 with a powered
  device attached reports `delivering` while voltage, current and power all read
  zero, because that hardware has no measurement circuit. The status sensor is
  therefore useful and the power sensor reports unknown rather than a false 0 W.
  Hardware that does measure, such as a CRS328-24P, has not been tested, and the
  unit divisor for it remains an assumption.
- **VLAN membership is unavailable.** RouterOS fills `dot1qPvid` but leaves
  `dot1qVlanStaticEgressPorts` empty, so netviz reports the PVID and says nothing
  about access versus trunk rather than guessing. Confirmed across all eight
  devices, including two CRS switches with bridge VLAN filtering — so this is the
  vendor rather than a class of device.
- **Wireless needs the controller.** A managed access point cannot count clients
  on its own radios — it answers either nothing or its unused local configuration
  — so netviz shows the radios but reports the count as unknown. Point it at the
  CAPsMAN controller as well and every AP is covered.

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

A hollow block with a dashed outline means there is no entity behind it, which is
a different thing from a radio that is switched off. Radio sensors shipped
disabled by default in an early version, and Home Assistant applies that flag
only when an entity is created, so upgrading left them hidden; netviz now clears
that flag on load where it set it itself, and leaves alone any entity the user
disabled.

Radios appear on the faceplate too, as rounded blocks after the ports, labelled
by band — `2.4G`, `5G`. Green means clients are attached, dark green means up and
idle, blue means a controller manages the radio and this device cannot count its
clients, grey means not running. The tooltip carries the SSID, client count,
average signal, noise floor and transmit quality. Only radios the device serves
itself get a block: a CAPsMAN controller reports one per managed access point,
and those belong on the faceplate of the access point that has them.

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

## Faceplate templates

The model dropdown lists a template for every front panel that has been drawn
from a photograph, alongside **Detect ports automatically**:

| Template | Ports |
|---|---|
| Aruba 2540-48G-PoE+-4SFP+ | 52 |
| MikroTik CRS309-1G-8S+ | 9 |
| MikroTik CRS112-8G-4S | 12 |
| MikroTik RB2011UiAS | 11 |
| MikroTik RB951Ui-2HnD | 5 |
| MikroTik hAP ac³ | 5 |
| MikroTik cAP ac | 2 |

A template contributes **geometry and nothing else**. The ports themselves always
come from the device, and a slot in a template carries a shape, a position and
which discovered port belongs in it — never an interface name. That matters on
RouterOS, where an interface is called whatever the operator typed: a template
keyed on `ether1` would break the moment somebody renamed it, and a test pins
that renaming every port on a CRS309 changes nothing about the drawing.

Ports are paired with slots by position in the device's own ifIndex order. On
every MikroTik checked that order runs left to right across the front panel,
including a CRS309 where the RJ45 sits on the right and comes last in ifIndex.

Picking a template for the wrong hardware is safe: if the port count does not
match, netviz logs it and falls back to the automatic layout rather than drawing
a faceplate with holes in it.

One detail in the CRS112 template comes from convention rather than from the
photograph — which of each vertical pair is the lower-numbered port. Column-major
is what both MikroTik and HP use on two-row panels. If a port's state shows up in
the wrong place on the card, that is the line to change in
`tools/gen_templates.py`.

## Model files

A full model file is the older format: it carries the SNMP binding as well as the
geometry, and it is what the Aruba entry uses. Templates are preferable for new
hardware.

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

Seven snapshots: a JL357A, a MikroTik RB2011, a CRS309 switch, a standalone AP, a
CAPsMAN controller, and two APs that controller provisions — one that reports a
little about its radios and one that reports nothing. They disagree in useful
ways, and every disagreement below produced a wrong answer that looked like a
right one until a test pinned it:

- the RB2011 leaves the Q-BRIDGE egress table empty while filling `dot1qPvid`,
  which made every port come out as `access`, trunks included — and the CRS309 is
  in the set because a switch was the obvious objection to that conclusion
- it answers `entPhysicalSerialNum` with `rb400_usb` from a row whose
  `entPhysicalClass` is `unknown` — a string identical on every RB2011, which
  would have collided two devices onto one unique_id
- `hrProcessorLoad` returns one value on one device, two on another and four on a
  third, all on the same firmware family
- `sysObjectID` arrives as `SNMPv2-SMI::enterprises.11...` rather than the dotted
  form, because pysnmp renders OIDs through its MIBs
- a standalone access point keeps its clients in a different table from a CAPsMAN
  controller, and that table has no SSID column
- a provisioned access point reports six radios up but only two rows in
  `mtxrWlAp`, both with the factory SSID and no clients, which had netviz drawing
  two idle radios on a device serving eighteen clients
- the one next to it reports six radios up and no rows at all, so netviz drew no
  wireless on an access point whose wireless was on — only the locally-
  administered bit in each interface's MAC says which two are the hardware

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
| ifPhysAddress — a real radio against a controller's | `1.3.6.1.2.1.2.2.1.6` | IF-MIB |
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
| mtxrWlApSsid / Clients / Noise / CCQ | `1.3.6.1.4.1.14988.1.1.1.3.1.4` / `.6` / `.9` / `.10` | MIKROTIK-MIB |
| mtxrWlRtab — local clients | `1.3.6.1.4.1.14988.1.1.1.2.1.3` | MIKROTIK-MIB |
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

Radios a device serves itself — a standalone access point, or the controller's
own radios alongside the ones it manages — also appear, and carry their SSID,
noise floor and transmit quality. A standalone AP keeps its clients in a separate
table with no SSID column, so the SSID is attributed per interface; the resulting
per-SSID and per-radio numbers look the same either way.

`mtxrWlAp` is populated for a radio configured in AP mode, whether or not it is
currently up. A radio left in station mode has no row at all, which is worth
knowing if a device reports no wireless when you expected some.

### A managed access point does not know its own client count

Ask a CAPsMAN-provisioned AP directly and one of two things happens. Either it
answers nothing at all — no `mtxrWlAp` rows — or it answers with the *local*
configuration nobody is being served by: the factory SSID and zero clients, while
its real clients are on the controller. Both were observed on cAP ac units on the
same network.

That zero is not a measurement, so netviz does not report it. Such a radio comes
back as `unknown` rather than `0`, its faceplate block is blue rather than green,
and the tooltip says the clients are counted on the controller. A zero there
would paint an idle radio on an access point carrying eighteen clients.

Two identical access points can therefore end up labelled differently — one
`2.4G`/`5G` and the other `wlan1`/`wlan2` — and that is the devices disagreeing,
not the card. The band comes from the frequency in `mtxrWlAp`, an access point
whose local AP configuration was removed reports no such row, and naming the band
from the interface instead would be a guess. The tooltip says so on the block.

Not every column of that row is equally worthless, and netviz publishes them
accordingly:

| column | on a controller-driven radio | published |
|---|---|---|
| SSID | reads as the factory default while the AP serves other names | no |
| clients | clients on that unused SSID, so zero | no, `unknown` |
| noise floor, CCQ | physical measurements of the radio | yes |
| frequency | the radio's own, so the band follows | yes, and the tooltip says where it came from |

Nothing here proves the frequency tracks the channel the controller assigned, so
the band is presented as the radio's own report rather than as verified fact.

The radios still get drawn, though, because they are the access point's own
hardware and they are transmitting. Which of them are real comes from the MAC
address: bit 1 of the first octet is IEEE's locally-administered flag, clear on
an address burned into a NIC and set on one a driver invented. A provisioned cAP
ac reports six radio interfaces up; two read `0x48` and four read `0x4a`, so two
of them are the hardware and the rest were created by the controller. With no
`mtxrWlAp` row there is no frequency and therefore no band, so those blocks carry
the interface name — `wlan1`, `wlan2` — rather than claiming one.

Where a device does not report interface addresses at all, the fallback is
arithmetic: more radio interfaces up than rows in `mtxrWlAp` means a controller
created the extra ones. It cannot say *which* are real, so it only decides
whether to trust the client counts.

Where those clients actually are is the controller, under its own dynamic
interfaces — and CAPsMAN names them after the access point and the band, so
`24Ghz-<ap name>-1` on the controller is the radio you were asking the AP about.
netviz does not yet link the two: the only thing joining a controller radio to an
access point is that operator-chosen name, and matching on it would be a guess
dressed as a fact. Enable the controller's per-radio sensors and the numbers are
all there.

**Aggregates only, deliberately.** The registration table is keyed by client MAC
address. Turning those into entities would be tracking everyone in the building,
Home Assistant already has a MikroTik integration that does device tracking, and
this is not it. A test asserts that no MAC address can reach an entity.

## Not there yet

- A radio or a port that appears after the integration was set up gets no
  entity and no faceplate block until the config entry is reloaded: both are
  built once, when the entry loads.
- Memory sensors, although memory is already polled on both vendors
- LLDP neighbours (LLDP-MIB `1.0.8802.1.1.2.1.4.1.1`)
- MAC table per port (`dot1dTpFdbPort`)
- A visual editor for the card (YAML only for now)
- An overall timeout around one poll cycle

## Licence

[MIT](LICENSE).

An independent implementation. Not derived from Switch Vision — that has no
open-source licence, so neither code nor artwork was taken from it.
