#!/usr/bin/env python3
"""Notīra identificējošos datus no capture_fixture.py snapshot'a.

Neapstrādātais snapshot ir noderīgs, bet tajā ir tīkla iekšas: hostname,
seriālnumuri, portu apraksti ar iekārtu nosaukumiem, VLAN nosaukumi. Repozitorijā
iet tikai izvads no šī skripta; ievads paliek lokāli un ir .gitignore sarakstā.

    python tools/sanitize_fixture.py tests/fixtures/jl357a-live.json \
                                     tests/fixtures/jl357a.json

Ko saglabā apzināti:
  * visu skaitlisko - skaitītājus, PoE milivatus, ātrumus, statusus, bitmapes
  * `ifAlias` sākuma atstarpi, jo tā ir kļūda, ko tests pieķer
  * `Not Avail` kā entPhysicalSerialNum vērtību, jo to atlases loģikai jāizfiltrē
  * seriālnumuru ar beigu atstarpēm, jo arī tas jāapgriež
"""

import argparse
import json
import re
import sys

OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
OID_ENT_MODEL = "1.3.6.1.2.1.47.1.1.1.1.13"

FAKE_HOST = "192.0.2.10"          # RFC 5737 dokumentācijas diapazons
FAKE_SYSNAME = "switch-test"
FAKE_CHASSIS_SERIAL = "TESTSERIAL1"
FAKE_MODULE_SERIAL = "TESTMODULE01    "   # atstarpes beigās - apzināti
FAKE_MODULE_MODEL = "TESTXCVR"
KEEP_SERIALS = {"Not Avail"}      # ražotāja vietturis, nav identificējošs


def sanitize(snap: dict) -> tuple[dict, list[str]]:
    log = []
    out = json.loads(json.dumps(snap))  # dziļa kopija

    if out.get("host"):
        log.append(f"host: {out['host']!r} -> {FAKE_HOST!r}")
        out["host"] = FAKE_HOST

    # --- skalāri ---
    if OID_SYS_NAME in out.get("get", {}):
        old = out["get"][OID_SYS_NAME]["value"]
        out["get"][OID_SYS_NAME]["value"] = FAKE_SYSNAME
        log.append(f"sysName: {old!r} -> {FAKE_SYSNAME!r}")

    # sysDescr: modelis paliek, jo uz to balstās modeļa atpazīšana un
    # sw_version parsēšanas tests. Bet būvēšanas ceļš un precīzais firmware
    # līmenis ir konkrētās iekārtas pazīmes - formātu saglabājam, ciparus ne.
    descr = out.get("get", {}).get(OID_SYS_DESCR, {}).get("value")
    if descr:
        new = descr.split(" (")[0]
        new = re.sub(r"(revision\s+[A-Z]{2}\.\d+\.\d+\.)\d+", r"\g<1>0000", new)
        new = re.sub(r"(ROM\s+[A-Z]{2}\.\d+\.\d+\.)\d+", r"\g<1>0000", new)
        if new != descr:
            out["get"][OID_SYS_DESCR]["value"] = new
            log.append(f"sysDescr: {descr!r}\n            -> {new!r}")

    for oid, rec in out.get("get", {}).items():
        if oid.startswith(OID_ENT_SERIAL) and rec.get("value"):
            old = rec["value"]
            rec["value"] = FAKE_CHASSIS_SERIAL
            log.append(f"GET {oid}: {old!r} -> {FAKE_CHASSIS_SERIAL!r}")

    walks = out.get("walks", {})

    # --- seriālnumuru tabula ---
    serials = walks.get(OID_ENT_SERIAL, {})
    seen = 0
    for idx in sorted(serials, key=lambda k: int(k)):
        value = serials[idx]
        if not value.strip() or value.strip() in KEEP_SERIALS:
            continue
        seen += 1
        new = FAKE_CHASSIS_SERIAL if seen == 1 else FAKE_MODULE_SERIAL
        log.append(f"entPhysicalSerialNum[{idx}]: {value!r} -> {new!r}")
        serials[idx] = new

    # --- modeļu tabula: šasijas modelis paliek, moduļu modeļi ne ---
    # Šasijas modelis ir tas, ko integrācija atpazīst, un tas ir pats produkts,
    # ko atbalsta. Bet iespraustie SFP moduļi atklāj, kāds uplinks kur ir.
    models = walks.get(OID_ENT_MODEL, {})
    if models:
        chassis = next(
            (models[i] for i in sorted(models, key=lambda k: int(k)) if models[i].strip()),
            None,
        )
        for idx, value in models.items():
            if value.strip() and value != chassis:
                log.append(f"entPhysicalModelName[{idx}]: {value!r} -> {FAKE_MODULE_MODEL!r}")
                models[idx] = FAKE_MODULE_MODEL

    # --- ifAlias: fiziskie porti, VLAN interfeisi, pārējie ---
    names = walks.get(OID_IF_NAME, {})
    aliases = walks.get(OID_IF_ALIAS, {})
    scrubbed = 0
    for idx, value in list(aliases.items()):
        if not value.strip():
            continue
        name = names.get(idx, "")
        lead = " " if value.startswith(" ") else ""   # kļūdas saglabāšana
        if name.isdigit():
            new = f"{lead}device-{int(name):02d}"
        elif (m := re.fullmatch(r"VLAN(\d+)", name)):
            new = f"{lead}vlan-{m.group(1)}"
        elif name.startswith("lo"):
            continue                                   # lo0..lo7 ir vispārīgi
        else:
            new = f"{lead}iface-{idx}"
        aliases[idx] = new
        scrubbed += 1
    log.append(f"ifAlias: notīrītas {scrubbed} vērtības (sākuma atstarpe saglabāta)")

    # DEFAULT_VLAN ifName ir AOS-S noklusējums, pārējie VLANxx ir tikai numuri -
    # tie paliek. ifDescr fiziskajiem portiem ir cipars, arī paliek.
    odd = [
        f"{idx}={value!r}"
        for idx, value in walks.get(OID_IF_DESCR, {}).items()
        if not value.isdigit() and "loopback" not in value.lower()
        and not re.fullmatch(r"(DEFAULT_)?VLAN\d*", value)
    ]
    if odd:
        log.append(f"UZMANĪBU, ifDescr neatpazītas vērtības: {odd[:5]}")

    return out, log


def audit(snap: dict) -> list[str]:
    """Pēdējā pārbaude: vai palicis kas tāds, kas izskatās pēc privātas IP,
    MAC adreses vai teksta, kas nav vispārīgs."""
    blob = json.dumps(snap, ensure_ascii=False)
    problems = []
    for ip in set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", blob)):
        octets = [int(o) for o in ip.split(".")]
        if any(o > 255 for o in octets):
            continue
        if octets[0] == 10 or (octets[0] == 192 and octets[1] == 168) or (
            octets[0] == 172 and 16 <= octets[1] <= 31
        ):
            problems.append(f"privāta IP adrese: {ip}")
    for mac in set(re.findall(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", blob)):
        problems.append(f"MAC adrese: {mac}")
    return problems


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("dest")
    args = ap.parse_args()

    with open(args.source, encoding="utf-8") as fh:
        snap = json.load(fh)

    clean, log = sanitize(snap)
    for line in log:
        print(f"  {line}")

    problems = audit(clean)
    if problems:
        print("\nNEIZDEVĀS - palikuši identificējoši dati:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    with open(args.dest, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"\naudits tīrs -> {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
