# netviz

Pārvaldāmu tīkla iekārtu vizualizācija Home Assistant. SNMP aptauja notiek pašā
HA — nav ne MQTT, ne atsevišķa konteinera, ne add-on'a.

Tikai lasīšana. Nekādu SNMP SET — read-only community vai SNMPv3 lietotājs pietiek.

*In English: [README.md](README.md)*

## Kas ir iekšā

- Config flow ar SNMPv2c un v3 (SHA/MD5 + AES/AES192/AES256/DES)
- Ierīce uz switch'u, entītijas uz portu: link, ātrums, RX/TX, PoE jauda,
  PoE statuss, PVID, apraksts
- Sistēmas sensori: CPU, uptime, PoE patēriņš un budžets, aktīvo portu skaits
- Faceplate Lovelace karte, ko integrācija reģistrē pati
- Porti tiek atrasti uz pašas iekārtas, tāpēc neko nevajag aprakstīt iepriekš;
  modeļa fails ir neobligāts un pievieno tikai priekšpaneļa ģeometriju

## Kādas iekārtas

Porti, link, ātrums, caurlaidība un apraksti nāk no standarta MIB un strādā uz
visa, kas atbild SNMP. Viss pārējais ir ražotāja specifisks, tāpēc netviz izvēlas
**profilu** pēc `sysObjectID` un lasa tikai to, ko konkrētais ražotājs tiešām
atbalsta.

| | ArubaOS-Switch | MikroTik RouterOS | pārējie |
|---|---|---|---|
| Porti, link, ātrums, RX/TX | jā | jā | jā |
| Portu apraksti | `ifAlias` | `ifName` | abi |
| PVID uz portu | jā | jā | jā |
| VLAN dalība, access vai trunk | jā | nē | ja Q-BRIDGE ir aizpildīts |
| PoE uz portu | jā, milivatos | tikai statuss, skat. zemāk | nē |
| PoE budžets un patēriņš | jā | nē | nē |
| CPU | jā | jā, vidējots pa kodoliem | nē |
| Seriālnumurs kā unique_id | ENTITY-MIB šasijas rinda | `mtxrSerialNumber` | ENTITY-MIB, ja ir |

Neatpazīts ražotājs dabū pēdējo kolonnu un nekādu minēšanu. Nolasīt sveša
ražotāja privāto OID un tā iegūto nulli pasniegt kā mērījumu ir sliktāk nekā
nerādīt neko.

Pārbaudīts pret Aruba 2540-48G-PoE+-4SFP+ (JL357A) ar ArubaOS-Switch 16.11, un
pret RouterOS 7.20–7.22 uz astoņām iekārtām: hAP ac³, divām cAP ac, divām
RB2011UiAS, RB951G, CRS309-1G-8S+ un CRS112-8G-4S.

### Zināmi trūkumi uz RouterOS

- **Pasīvajam PoE-out jauda netiek mērīta.** RB2011 ar pieslēgtu patērētāju
  rāda `delivering`, bet spriegums, strāva un jauda visi ir nulle, jo tai dzelzij
  nav mērīšanas ķēdes. Tāpēc statusa sensors ir noderīgs, bet jaudas sensors rāda
  `unknown`, nevis nepatiesu 0 W. Dzelzs, kas jaudu mēra, piemēram CRS328-24P,
  nav pārbaudīta, un mērvienību dalītājs tai paliek pieņēmums.
- **VLAN dalība nav pieejama.** RouterOS aizpilda `dot1qPvid`, bet atstāj
  `dot1qVlanStaticEgressPorts` tukšu, tāpēc netviz rāda PVID un par access vai
  trunk klusē, nevis min. Apstiprināts uz visām astoņām iekārtām, ieskaitot divus
  CRS switch'us ar bridge VLAN filtering — tātad tā ir ražotāja, nevis konkrētas
  iekārtu klases īpašība.
- **Bezvadu daļai vajag kontrolieri.** Pārvaldīta AP nespēj saskaitīt klientus uz
  saviem radio — tā atbild vai nu neko, vai savu neizmantoto vietējo
  konfigurāciju — tāpēc netviz radio parāda, bet skaitu ziņo kā nezināmu. Norādi
  netviz arī uz CAPsMAN kontrolieri, un visas AP ir nosegtas.

## Instalācija caur HACS

1. HACS → trīs punkti → **Custom repositories**
2. URL: `https://github.com/gun4as/HP-HA`, kategorija **Integration**
3. Instalē **netviz**, pārstartē Home Assistant
4. **Iestatījumi → Ierīces un pakalpojumi → Pievienot integrāciju → netviz**

Modeli atstāj uz **Detect ports automatically**, ja vien tavai konkrētajai
dzelzij nav modeļa faila.

Karti pievienot ar roku Lovelace resursos **nevajag** — integrācija to reģistrē
pati caur `add_extra_js_url`. Ja pēc pārstarta karte tomēr met `Custom element
doesn't exist: netviz-faceplate-card`, pārbaudi pēc kārtas:

1. Vai fails ir pieejams: `http://<tava-ha>:8123/netviz/netviz-faceplate-card.js`.
   Ja tas dod 404, HACS nav nolejupielādējis `www/` mapi — pārlādē integrāciju.
2. `Ctrl+Shift+R` pārlūkā. Resursu saraksts tiek kešots, un jauns skripts
   parādās tikai pēc pilnas pārlādes.
3. Ja fails atveras, bet karte joprojām nav, pievieno resursu ar roku:
   **Iestatījumi → Paneļi → trīs punkti → Resursi → Pievienot**, URL
   `/netviz/netviz-faceplate-card.js`, tips **JavaScript Module**. Ņem vērā, ka
   manuālam resursam nav keša lauzēja parametra, tāpēc pēc atjauninājuma tas
   turpinās pasniegt veco failu — noņem to, kad automātiskā reģistrācija strādā.

### Ikona

Integrācija nes savus zīmola attēlus mapē `custom_components/netviz/brand/`, ko
Home Assistant 2026.3 un jaunāks pasniedz no
`/api/brands/integration/netviz/icon.png`, priekšroku dodot lokālajam, ne CDN.
Pull request uz [home-assistant/brands](https://github.com/home-assistant/brands)
nav vajadzīgs — tā `custom_integrations` mape tagad ir apzīmēta kā legacy. Uz
vecākas HA mape tiek ignorēta, un HACS rāda savu ģenerēto vietturi.

Attēli ir ģenerēti, ne zīmēti ar roku, tāpēc tos var pieregulēt un pārzīmēt:

```bash
pip install Pillow
python tools/gen_brand.py
```

## Konfigurācija

Pietiek ar read-only piekļuvi. ArubaOS-Switch:

```
snmp-server community "netviz" operator restricted
```

SNMPv3 uz AOS-S (ieteicams):

```
snmpv3 enable
snmpv3 user netviz auth sha <authpass> priv aes <privpass>
snmpv3 group managerpriv user netviz sec-model ver3
```

RouterOS SNMP pēc noklusējuma ir izslēgts. Community, ierobežots ar Home
Assistant resursdatoru:

```
/snmp community add name=netviz addresses=<ha-ip>/32 read-access=yes write-access=no
/snmp set enabled=yes
```

Ja joprojām neatbild, pārbaudi input ķēdi — noklusējuma ugunsmūris UDP 161 nomet,
pirms tas sasniedz servisu:

```
/ip firewall filter print where chain=input
```

Opcijās (integrācijas kartītē → **Konfigurēt**) var mainīt aptaujas intervālu,
ieslēgt un izslēgt metrikas, VLAN lasīšanu un to, vai saite uz iekārtas web
saskarni iet pa http vai https.

## Entītiju skaits — izlasi pirms ieslēdz visu

Uz JL357A:

| Ieslēgts | Entītijas |
|---|---|
| Noklusējums (link, speed, RX, TX, PoE power, PoE status) | **310** |
| Viss (`ALL_METRICS`) | **518** |

Katra metrika reizinās ar portu skaitu, tāpēc piecu portu maršrutētājs nav
problēma, bet 48 portu switch ir. Ja recorder sāk smakt, izmet `rx_rate` un
`tx_rate` no opcijām, vai izslēdz portu sensorus recorder konfigurācijā:

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

Switch priekšpanelis ir garš un zems — uz JL357A proporcija ir gandrīz 9:1.
Kartei vajag platumu. Sadaļu panelī dod tam pilnu rindu:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
grid_options:
  columns: full
```

Karte mērogojas pēc konteinera un ritjoslas nav. Mazu priekšpaneli tā
nepalielinās vairāk par 1,4× no dabiskā izmēra, tāpēc piecu portu maršrutētājs
neaizņem visu paneli. Portu etiķetes tiek paslēptas, ja tās sanāktu mazākas par
~5,5px — zem ~615px platuma uz 52 portu korpusa — un krāsas ar tooltip paliek. Ja
gribi pilnu izmēru ar horizontālo ritināšanu, uzstādi `min_width`:

```yaml
type: custom:netviz-faceplate-card
faceplate: sensor.sw_2540_faceplate
min_width: 820
```

Karte ņem ģeometriju no `faceplate` entītijas atribūtiem un stāvokli no pārējām
tās pašas ierīces entītijām. Portus tā savāc pēc `port` un `metric` atribūtiem,
**nevis** pēc entity_id — pārsaukšana neko nesalauž.

Tukšs bloks ar punktētu apmali nozīmē, ka tam nav entītijas — un tas nav tas pats,
kas izslēgts radio. Agrā versijā radio sensori tika veidoti izslēgti, un Home
Assistant to karodziņu piemēro tikai entītijas izveides brīdī, tāpēc pēc
atjaunināšanas tie palika paslēpti; netviz tagad ielādes laikā to karodziņu noņem
tur, kur pats to uzlika, un neaiztiek entītijas, ko izslēdzis lietotājs.

Priekšpanelī parādās arī radio — apaļoti bloki aiz portiem, ar joslas apzīmējumu
`2.4G`, `5G`. Zaļš nozīmē, ka klienti ir pieslēgti, tumši zaļš — ka radio ir `up`,
bet dīkstāvē, zils — ka radio pārvalda kontrolieris un šī iekārta savus klientus
saskaitīt nevar, pelēks — ka tas nestrādā; tooltip ir SSID, klientu skaits,
vidējais signāls, trokšņu grīda un pārraides kvalitāte. Bloku dabū tikai tie radio, ko
iekārta apkalpo pati: CAPsMAN kontrolieris ziņo vienu uz katru pārvaldīto AP, un
tie pieder tās AP priekšpanelim, kurai tie ir.

Krāsas: zaļa 1G, zila 10G, dzintars 10/100M, pelēka down. Oranžs punkts nozīmē,
ka ports padod PoE jaudu; normālā izmērā tas ir stūrī, bet, kad etiķetes ir
paslēptas, pārvietojas uz porta vidu. Klikšķis atver porta more-info.

### Bez modeļa faila

Atrastie porti tiek izkārtoti automātiski: no kreisās uz labo tādā secībā, kādā
iekārta tos pieteica, aiz sešiem pārceļoties uz otro rindu, katrs ports izmērots
pēc savas etiķetes. Interfeisu nosaukumi tiek saīsināti līdz porta tokenam, jo uz
RouterOS tāds nosaukums kā `ether1uplink dsl` ir trīsreiz platāks par portu un
blakus etiķetes pārklājas nesalasāmi; pilnais nosaukums paliek tooltip.

Tas zīmējums ir **portu saraksts, ne korpuss**. Tas nevar zināt, kurā pusē
fiziski ir SFP ligzda vai kā numurēts priekšpanelis, un ģeometrijā atzīmē sevi ar
`generated`. Modeļa fails ir tas, kas to pārvērš par īstas dzelzs attēlu.

## Priekšpaneļa veidnes

Modeļu izvēlnē ir veidne katram priekšpanelim, kas ir uzzīmēts no foto, blakus
**Detect ports automatically**:

| Veidne | Porti |
|---|---|
| Aruba 2540-48G-PoE+-4SFP+ | 52 |
| MikroTik CRS309-1G-8S+ | 9 |
| MikroTik CRS112-8G-4S | 12 |
| MikroTik RB2011UiAS | 11 |
| MikroTik RB951Ui-2HnD | 5 |
| MikroTik hAP ac³ | 5 |
| MikroTik cAP ac | 2 |

Veidne pievieno **tikai ģeometriju**. Porti vienmēr nāk no iekārtas, un slots
veidnē satur formu, pozīciju un to, kurš atrastais ports tajā ietilpst — nekad
interfeisa nosaukumu. Uz RouterOS tas ir būtiski, jo interfeiss saucas tā, kā
operators ierakstījis: veidne ar `ether1` salūztu tajā mirklī, kad to pārsauc, un
ir tests, kas pierāda, ka, pārsaucot visus CRS309 portus, zīmējums nemainās.

Porti tiek piekārtoti slotiem pēc secības iekārtas paša `ifIndex` sarakstā. Visām
pārbaudītajām MikroTik iekārtām tā secība iet no kreisās uz labo pa priekšpaneli,
arī CRS309, kur RJ45 ir pa labi un `ifIndex` ir pēdējais.

Izvēlēties veidni nepareizai dzelzij ir droši: ja portu skaits nesakrīt, netviz to
ieraksta logā un atkāpjas uz automātisko izkārtojumu, nevis zīmē priekšpaneli ar
caurumiem.

Viena detaļa CRS112 veidnē nāk no konvencijas, ne no foto — kurš no katra
vertikālā pāra ir mazākais numurs. Kolonnu secība ir tā, ko lieto gan MikroTik,
gan HP uz divu rindu paneļiem. Ja kartē kāda porta stāvoklis parādās nepareizā
vietā, tā ir tā rinda, ko mainīt `tools/gen_templates.py`.

## Modeļa faili

Pilns modeļa fails ir vecākais formāts: tas nes arī SNMP piesaisti, ne tikai
ģeometriju, un to lieto Aruba ieraksts. Jaunai dzelzij veidnes ir labākas.

```bash
python3 tools/gen_model.py --rj45 48 --sfp 4 --numbering column --sfp-side left \
  -o custom_components/netviz/models/manssvics.json
```

Ģenerētais modelis pieņem, ka porta `ifName` ir tā numurs un PoE indekss ir
`1.<ports>`. Pārbaudi pret dzelzi:

```bash
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.31.1.1.1.1
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.2.1.105.1.1.1.6
snmpbulkwalk -v2c -c public -Oqn 192.0.2.10 1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8
```

Ja nesakrīt, labo `ifname` vai pievieno `ifindex` katram portam. Vēl divi
pieņēmumi ir tikai vizuāli: portu numerācija priekšpanelī (`--numbering row`) un
tas, kurā pusē ir SFP+ bloks (`--sfp-side right`). Abus vērts pārbaudīt pret
īstas priekšas foto.

SNMP slāni var palaist atsevišķi, bez HA. Failu palaiž tieši, nevis ar `-m`:

```bash
python3 custom_components/netviz/snmp.py 192.0.2.10 public
```

## Testēšana

```bash
pip install -r requirements_test.txt
pytest
```

Vairāk nekā nevajag — ne HA instalācijas, ne tīkla. `snmp.py`, `model.py` un
`profiles.py` neimportē HA, un testi tos ielādē tieši no failiem, tāpēc īsts
`SnmpClient` strādā ar `walk()` un `get_many()`, kas baroti no ierakstīta
snapshot'a. Viss virs tiem ir ražošanas koda ceļš.

Septiņi snapshot'i: JL357A, MikroTik RB2011, CRS309 switch, atsevišķa AP, CAPsMAN
kontrolieris un divas AP, ko tas kontrolieris pārvalda — viena, kas par saviem
radio ziņo mazliet, un otra, kas neziņo neko. Tie atšķiras noderīgi, un katra no
zemāk minētajām atšķirībām deva nepareizu atbildi, kas izskatījās pareiza, līdz
tests to pieķēra:

- RB2011 atstāj Q-BRIDGE egress tabulu tukšu, aizpildot `dot1qPvid`, un tāpēc
  katrs ports iznāca kā `access`, ieskaitot trunkus — un CRS309 ir komplektā
  tāpēc, ka switch bija acīmredzamais iebildums pret to secinājumu
- tas atbild `entPhysicalSerialNum` ar `rb400_usb` no rindas, kuras
  `entPhysicalClass` ir `unknown` — virkne, kas ir vienāda katram RB2011, un kas
  būtu sadūrusi divas iekārtas uz viena unique_id
- `hrProcessorLoad` atdod vienu vērtību uz vienas iekārtas, divas uz citas un
  četras uz trešās, visas ar to pašu firmware saimi
- `sysObjectID` atnāk kā `SNMPv2-SMI::enterprises.11...`, ne punktotā formā, jo
  pysnmp OID izdrukā caur saviem MIB
- atsevišķa AP savus klientus glabā citā tabulā nekā CAPsMAN kontrolieris, un tai
  tabulai nav SSID kolonnas
- pārvaldīta AP ziņo sešus radio `up`, bet `mtxrWlAp` ir tikai divas rindas, abām
  rūpnīcas SSID un nulle klientu — un tāpēc netviz zīmēja divus dīkstāves radio uz
  iekārtas, kas apkalpo astoņpadsmit klientus
- tā blakus ziņo sešus radio `up` un nevienu rindu, tāpēc netviz nezīmēja nekādu
  bezvadu daļu uz AP, kurai WiFi bija ieslēgts — tikai *locally administered* bits
  katra interfeisa MAC adresē pasaka, kuri divi ir dzelzs

Testi nekad neaiztiek dzelzi. Snapshot ņem divos soļos, un otrais ir obligāts:

```bash
python3 tools/capture_fixture.py 192.0.2.10 public tests/fixtures/mans-live.json
python3 tools/sanitize_fixture.py tests/fixtures/mans-live.json tests/fixtures/mans.json
```

Neapstrādātajā snapshot'ā ir hostname, šasijas un moduļu seriālnumuri, portu
apraksti ar iekārtu nosaukumiem, VLAN nosaukumi, SSID un katra bezvadu klienta
MAC adrese. `sanitize_fixture.py` tos visus aizstāj, saglabājot visu skaitlisko
neskartu, un beigās noskrien auditu, kas met kļūdu, ja palikusi privāta IP vai
MAC adrese. `*-live.json` ir `.gitignore` sarakstā.

## Izmantotie OID

Standarta MIB, lasīti uz katras iekārtas:

| Ko | OID | MIB |
|---|---|---|
| ifName / ifAlias | `1.3.6.1.2.1.31.1.1.1.1` / `.18` | IF-MIB |
| ifType — kā atrod fiziskos portus | `1.3.6.1.2.1.2.2.1.3` | IF-MIB |
| ifPhysAddress — īsts radio pret kontroliera izveidotu | `1.3.6.1.2.1.2.2.1.6` | IF-MIB |
| ifOperStatus / ifAdminStatus | `1.3.6.1.2.1.2.2.1.8` / `.7` | IF-MIB |
| ifHighSpeed | `1.3.6.1.2.1.31.1.1.1.15` | IF-MIB |
| ifHCInOctets / ifHCOutOctets | `1.3.6.1.2.1.31.1.1.1.6` / `.10` | IF-MIB |
| sysObjectID — pēc kā izvēlas profilu | `1.3.6.1.2.1.1.2.0` | SNMPv2-MIB |
| entPhysicalClass / SerialNum | `1.3.6.1.2.1.47.1.1.1.1.5` / `.11` | ENTITY-MIB |
| dot1dBasePortIfIndex | `1.3.6.1.2.1.17.1.4.1.2` | BRIDGE-MIB |
| dot1qPvid | `1.3.6.1.2.1.17.7.1.4.5.1.1` | Q-BRIDGE-MIB |
| dot1qVlanStaticEgress / Untagged | `1.3.6.1.2.1.17.7.1.4.3.1.2` / `.4` | Q-BRIDGE-MIB |

ArubaOS-Switch:

| Ko | OID | MIB |
|---|---|---|
| pethPsePortDetectionStatus | `1.3.6.1.2.1.105.1.1.1.6` | POWER-ETHERNET-MIB |
| pethMainPsePower / Consumption | `1.3.6.1.2.1.105.1.3.1.1.2` / `.4` | POWER-ETHERNET-MIB |
| hpicfPoePethPsePortActualPower | `1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8` | HP-ICF-POE-MIB (**mW**) |
| hpSwitchCpuStat | `1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0` | STATISTICS-MIB |
| hpLocalMemFree / AllocBytes | `...5.1.1.2.1.1.1.6.1` / `.7.1` | NETSWITCH-MIB |

MikroTik RouterOS:

| Ko | OID | MIB |
|---|---|---|
| mtxrSerialNumber | `1.3.6.1.4.1.14988.1.1.7.3.0` | MIKROTIK-MIB |
| mtxrPOEStatus / Power | `1.3.6.1.4.1.14988.1.1.15.1.1.3` / `.6` | MIKROTIK-MIB |
| mtxrWlApSsid / Clients / Noise / CCQ | `1.3.6.1.4.1.14988.1.1.1.3.1.4` / `.6` / `.9` / `.10` | MIKROTIK-MIB |
| mtxrWlRtab — lokālie klienti | `1.3.6.1.4.1.14988.1.1.1.2.1.3` | MIKROTIK-MIB |
| hrProcessorLoad | `1.3.6.1.2.1.25.3.3.1.2` | HOST-RESOURCES-MIB |
| hrStorage — atmiņa | `1.3.6.1.2.1.25.2.3.1.3` … `.6` | HOST-RESOURCES-MIB |
| CAPsMAN reģistrācijas | `1.3.6.1.4.1.14988.1.1.1.5` | MIKROTIK-MIB |

HP-ICF-POE-MIB: <https://mibs.observium.org/mib/HP-ICF-POE-MIB/>
AOS-S 16.11: <https://arubanetworking.hpe.com/techdocs/AOS-S/16.11/MCG/YAYB/content/common%20files/vie-poe-sta-spe-por.htm>

## Bezvadu daļa uz CAPsMAN kontroliera

Norādi netviz uz kontrolieri, nevis uz AP. Pārvaldīta AP par saviem radio
neatbild gandrīz neko — viss ir uz kontroliera — tāpēc viena iekārta sedz visu
tīklu, ieskaitot tās AP, kas, tieši prasot, izskatās salauztas.

Iegūsti kopējo klientu skaitu, sensoru uz katru SSID un sensoru uz katru AP
radio, katram atribūtos vidējais, minimālais un maksimālais signāls. Radio
sensori pēc noklusējuma ir izslēgti, jo kontrolieris ar vairākām AP tādu uztaisa
daudz.

Parādās arī radio, ko iekārta apkalpo pati — atsevišķa AP, vai kontroliera paša
radio blakus tiem, ko tas pārvalda — un tiem ir SSID, trokšņu grīda un pārraides
kvalitāte. Atsevišķa AP savus klientus glabā citā tabulā, kurai nav SSID
kolonnas, tāpēc SSID tiek piešķirts pēc interfeisa; rezultāts pa SSID un pa radio
izskatās vienādi abos gadījumos.

`mtxrWlAp` ir aizpildīta radio, kas **konfigurēts** AP režīmā, neatkarīgi no tā,
vai tas šobrīd ir `up`. Radio, kas atstāts station režīmā, tur nav vispār — to
vērts zināt, ja iekārta neziņo bezvadu daļu, kur to gaidīji.

### Pārvaldīta AP nezina savu klientu skaitu

Ja prasa CAPsMAN pārvaldītai AP tieši, notiek viens no diviem. Vai nu tā neatbild
neko — `mtxrWlAp` nav nevienas rindas — vai atbild ar *vietējo* konfigurāciju, ko
neviens neizmanto: rūpnīcas SSID un nulle klientu, kaut patiesie klienti ir uz
kontroliera. Abi gadījumi novēroti uz cAP ac vienā tīklā.

Tā nulle nav mērījums, tāpēc netviz to neziņo. Tāds radio atgriežas kā `unknown`,
nevis `0`, tā bloks priekšpanelī ir zils, nevis zaļš, un tooltip pasaka, ka
klienti tiek skaitīti uz kontroliera. Nulle tur uzzīmētu dīkstāves radio uz AP,
kas nes astoņpadsmit klientus.

Tāpēc divas vienādas AP var iznākt ar atšķirīgiem apzīmējumiem — vienai `2.4G`/`5G`,
otrai `wlan1`/`wlan2` — un tā ir iekārtu, nevis kartes atšķirība. Josla nāk no
frekvences `mtxrWlAp` tabulā; AP, kurai vietējā AP konfigurācija ir noņemta, tādas
rindas nav, un nosaukt joslu pēc interfeisa būtu minējums. Tooltip to pasaka uz
paša bloka.

Ne visas tās rindas kolonnas ir vienlīdz nederīgas, un netviz tās publicē
attiecīgi:

| kolonna | uz kontroliera vadīta radio | publicē |
|---|---|---|
| SSID | rāda rūpnīcas noklusējumu, kamēr AP apkalpo citus vārdus | nē |
| klienti | tā neizmantotā SSID klienti, tātad nulle | nē, `unknown` |
| trokšņu grīda, CCQ | fiziski radio mērījumi | jā |
| frekvence | paša radio, tātad josla no tās | jā, un tooltip pasaka, no kurienes |

Nekas te nepierāda, ka frekvence seko kanālam, ko piešķīris kontrolieris, tāpēc
josla tiek pasniegta kā paša radio ziņojums, nevis kā pārbaudīts fakts.

Radio tomēr tiek uzzīmēti, jo tie ir tās AP paša dzelzs un tie raida. Kurš no
tiem ir īsts, pasaka MAC adrese: pirmā okteta 1. bits ir IEEE *locally
administered* karodziņš — nulle adresei, kas iededzināta NIC, un viens tādai, ko
izdomājis draiveris. Pārvaldīta cAP ac ziņo sešus radio interfeisus `up`; divi
sākas ar `0x48` un četri ar `0x4a`, tāpēc divi no tiem ir dzelzs, bet pārējos
izveidoja kontrolieris. Bez `mtxrWlAp` rindas nav frekvences un tātad nav joslas,
tāpēc tie bloki nes interfeisa nosaukumu — `wlan1`, `wlan2` — nevis izliekas
zināt.

Ja iekārta interfeisu adreses neziņo vispār, atkāpe ir aritmētiska: ja `up` radio
interfeisu ir vairāk nekā rindu `mtxrWlAp`, tad liekos ir izveidojis kontrolieris.
Tā nevar pateikt, *kuri* ir īsti, tāpēc izšķir tikai to, vai ticēt klientu
skaitiem.

Klienti patiesībā ir uz kontroliera, zem tā dinamiskajiem interfeisiem — un
CAPsMAN tos nosauc pēc AP un joslas, tāpēc `24Ghz-<ap nosaukums>-1` uz kontroliera
ir tas pats radio, par ko prasīji AP. netviz šos divus vēl nesasaista: vienīgais,
kas kontroliera radio saista ar AP, ir operatora izvēlēts nosaukums, un salikt tos
pēc tā būtu minējums, kas izliktos par faktu. Ieslēdz kontroliera radio sensorus,
un skaitļi visi ir tur.

**Apzināti tikai agregāti.** Reģistrācijas tabula ir indeksēta pēc klienta MAC
adreses. Taisīt no tām entītijas nozīmētu izsekot visus mājā, Home Assistant tam
jau ir sava MikroTik integrācija, un šī nav tā. Ir tests, kas apgalvo, ka neviena
MAC adrese nevar nonākt entītijā.

## Vēl nav

- Radio vai ports, kas parādās pēc integrācijas pievienošanas, nedabū ne
  entītiju, ne bloku priekšpanelī, kamēr ieraksts netiek pārlādēts: abi tiek
  uzbūvēti vienreiz, ierakstam ielādējoties.
- Atmiņas sensori, lai gan atmiņa jau tiek aptaujāta abiem ražotājiem
- LLDP kaimiņi (LLDP-MIB `1.0.8802.1.1.2.1.4.1.1`)
- MAC tabula uz portu (`dot1dTpFdbPort`)
- Kartes vizuālais redaktors (pagaidām tikai YAML)
- Kopējais taimauts vienam aptaujas ciklam

## Licence

[MIT](LICENSE).

Neatkarīga implementācija. Nav atvasināta no Switch Vision — tam nav
open-source licences, tāpēc no turienes nav ņemts ne kods, ne attēli.
