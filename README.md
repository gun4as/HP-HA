# netviz

Pārvaldāmu tīkla switch'u vizualizācija Home Assistant. SNMP aptauja notiek
pašā HA — nav ne MQTT, ne atsevišķa konteinera, ne add-on'a.

Pirmais modelis: **Aruba 2540-48G-PoE+-4SFP+ (JL357A)**, ArubaOS-Switch 16.x.

Tikai lasīšana. Nekādu SNMP SET — read-only community vai v3 lietotājs pietiek.

## Kas ir iekšā

- Config flow ar SNMPv1/v2c/v3 (SHA/MD5 + AES/AES192/AES256/DES)
- Ierīce uz switch'u, entītijas uz portu: link, ātrums, RX/TX, PoE jauda,
  PoE statuss, PVID, apraksts
- Sistēmas sensori: CPU, uptime, PoE patēriņš un budžets, aktīvo portu skaits
- Faceplate Lovelace karte, ko integrācija reģistrē pati
- Modeļa definīcija JSON failā — jauns switch modelis nav koda izmaiņa

## Instalācija caur HACS

1. HACS → trīs punkti → **Custom repositories**
2. URL: `https://github.com/gun4as/HP-HA`, kategorija **Integration**
3. Instalē **netviz**, pārstartē Home Assistant
4. **Iestatījumi → Ierīces un pakalpojumi → Pievienot integrāciju → netviz**

Karti pievienot ar roku Lovelace resursos **nevajag** — integrācija to reģistrē
pati caur `add_extra_js_url`. Ja pēc pārstarta karte tomēr met `Custom element
doesn't exist: netviz-faceplate-card`, pārbaudi pēc kārtas:

1. Vai fails ir pieejams: `http://<tava-ha>:8123/netviz/netviz-faceplate-card.js`.
   Ja tas dod 404, HACS nav nolejupielādējis `www/` mapi — pārlādē integrāciju.
2. `Ctrl+Shift+R` pārlūkā. Resursu saraksts tiek kešots, un jauns skripts
   parādās tikai pēc pilnas pārlādes.
3. Ja fails atveras, bet karte joprojām nav, pievieno resursu ar roku:
   **Iestatījumi → Paneļi → trīs punkti → Resursi → Pievienot**, URL
   `/netviz/netviz-faceplate-card.js`, tips **JavaScript Module**.

### Atkarības

`manifest.json` prasa `pysnmp==7.1.27` — tieši to pašu versiju, ko HA Core jau
ved līdzi priekš iebūvētās `snmp` un `brother` integrācijām. Tāpēc instalācija
neko papildus nelejupielādē un nav versiju konflikta.

## Konfigurācija

Switch pusē pietiek ar read-only piekļuvi. AOS-S:

```
snmp-server community "netviz" operator restricted
```

SNMPv3 (ieteicams):

```
snmpv3 enable
snmpv3 user netviz auth sha <authpass> priv aes <privpass>
snmpv3 group managerpriv user netviz sec-model ver3
```

Opcijās (integrācijas kartītē → **Konfigurēt**) var mainīt aptaujas intervālu,
ieslēgt/izslēgt metrikas un VLAN lasīšanu.

## Entītiju skaits — izlasi pirms ieslēdz visu

Uz JL357A:

| Ieslēgts | Entītijas |
|---|---|
| Noklusējums (link, speed, RX, TX, PoE power, PoE status) | **310** |
| Viss (`ALL_METRICS`) | **518** |

Katra metrika reizinās ar 52 portiem. Ja recorder sāk smakt, izmet `rx_rate`
un `tx_rate` no opcijām un atstāj tos tikai tur, kur tiešām vajag vēsturi, vai
izslēdz portu sensorus recorder konfigurācijā:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.*_rx_total
      - sensor.*_tx_total
```

## Faceplate karte

```yaml
type: custom:netviz-faceplate-card
device: <device_id>
title: SW-2540
```

vai bez device_id:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
```

Priekšpanelis ir garš un zems — uz JL357A proporcija ir gandrīz 9:1. Kartei
vajag platumu, citādi porti kļūst niecīgi. Sadaļu panelī (`sections`) dod tam
pilnu rindu:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
grid_options:
  columns: full
```

Karte mērogojas pēc konteinera un ritjoslas nav. Portu numuri tiek paslēpti, ja
tie sanāktu mazāki par ~5,5px — zem ~615px platuma uz 52 portu korpusa. Krāsas
un tooltip paliek. Ja gribi pilnu izmēru ar horizontālo ritināšanu, uzstādi
`min_width`:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
min_width: 820
```

Karte ņem ģeometriju no `faceplate` entītijas atribūtiem un stāvokli no pārējām
tās pašas ierīces entītijām. Portus tā savāc pēc `port` un `metric` atribūtiem,
**nevis** pēc entity_id — pārsaukšana neko nesalauž.

Krāsas: zaļa 1G, zila 10G, dzeltena 10/100M, pelēka down. Oranžs punkts porta
stūrī = PoE padod jaudu. Klikšķis atver porta more-info.

## Jauns switch modelis

```bash
python3 tools/gen_model.py --rj45 48 --sfp 4 --numbering column \
  -o custom_components/netviz/models/manssvičs.json
```

Modeļa JSON pieņem, ka porta `ifName` ir tā numurs un PoE indekss ir
`1.<ports>`. Pārbaudi pret dzelzi:

```bash
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.31.1.1.1.1
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.105.1.1.1.6
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8
```

Ja nesakrīt, labo `ifname` vai pievieno `ifindex` katram portam. Trešais
pieņēmums ir vizuāls — portu numerācija priekšpanelī (nepāra augšā, pāra
apakšā). Ja korpusā ir citādi: `--numbering row`.

SNMP slāni var palaist atsevišķi, bez HA. Failu palaiž tieši, nevis ar `-m`:
`-m` importētu vecāku paketi, tātad `__init__.py`, tātad visu Home Assistant.

```bash
python3 custom_components/netviz/snmp.py 192.0.2.10 public
```

## Testēšana

Testi negriežas pie dzelžiem — tie strādā pret snapshot'u, kas noņemts no īsta
switch'a un pēc tam notīrīts. Divi soļi, un otrais ir obligāts:

```bash
python3 tools/capture_fixture.py 192.0.2.10 public tests/fixtures/mans-live.json
python3 tools/sanitize_fixture.py tests/fixtures/mans-live.json tests/fixtures/mans.json
```

Neapstrādātajā snapshot'ā ir hostname, šasijas un SFP moduļu seriālnumuri, portu
apraksti ar iekārtu nosaukumiem un VLAN nosaukumi. `sanitize_fixture.py` tos
aizstāj, saglabājot visu skaitlisko neskartu, un beigās noskrien auditu, kas met
kļūdu, ja palikusi privāta IP vai MAC adrese. `*-live.json` ir `.gitignore`
sarakstā, tāpēc neapstrādāto versiju nevar iekomitēt nejauši.

Repozitorijā iekļautais `tests/fixtures/jl357a.json` ir tāds pats sanitizēts
snapshot no JL357A ar 52 portiem, 22 aktīviem linkiem, sešiem PoE patērētājiem
un astoņiem VLAN.

## Izmantotie OID

| Ko | OID | MIB |
|---|---|---|
| ifName / ifAlias | `1.3.6.1.2.1.31.1.1.1.1` / `.18` | IF-MIB |
| ifOperStatus / ifAdminStatus | `1.3.6.1.2.1.2.2.1.8` / `.7` | IF-MIB |
| ifHighSpeed | `1.3.6.1.2.1.31.1.1.1.15` | IF-MIB |
| ifHCInOctets / ifHCOutOctets | `1.3.6.1.2.1.31.1.1.1.6` / `.10` | IF-MIB |
| pethPsePortDetectionStatus | `1.3.6.1.2.1.105.1.1.1.6` | POWER-ETHERNET-MIB |
| pethMainPsePower / Consumption | `1.3.6.1.2.1.105.1.3.1.1.2` / `.4` | POWER-ETHERNET-MIB |
| hpicfPoePethPsePortActualPower | `1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8` | HP-ICF-POE-MIB (**mW**) |
| hpSwitchCpuStat | `1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0` | STATISTICS-MIB |
| dot1dBasePortIfIndex | `1.3.6.1.2.1.17.1.4.1.2` | BRIDGE-MIB |
| dot1qPvid | `1.3.6.1.2.1.17.7.1.4.5.1.1` | Q-BRIDGE-MIB |
| dot1qVlanStaticEgress / Untagged | `1.3.6.1.2.1.17.7.1.4.3.1.2` / `.4` | Q-BRIDGE-MIB |

HP-ICF-POE-MIB: <https://mibs.observium.org/mib/HP-ICF-POE-MIB/>
AOS-S 16.11: <https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/YAYB/content/common%20files/vie-poe-sta-spe-por.htm>

## Vēl nav

- LLDP kaimiņi (LLDP-MIB `1.0.8802.1.1.2.1.4.1.1`)
- MAC tabula uz portu (`dot1dTpFdbPort`)
- Kartes vizuālais redaktors (pagaidām tikai YAML)

## Licence

Neatkarīga implementācija. Nav atvasināta no Switch Vision — tam nav
open-source licences, tāpēc no turienes nav ņemts ne kods, ne attēli.
