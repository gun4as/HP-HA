#!/usr/bin/env python3
"""Strips identifying data out of a capture_fixture.py snapshot.

A raw snapshot is useful, but it holds the innards of a network: hostname,
serial numbers, port descriptions naming real devices, VLAN names. Only the
output of this script goes into the repository; the input stays local and is
listed in .gitignore.

    python tools/sanitize_fixture.py tests/fixtures/jl357a-live.json \
                                     tests/fixtures/jl357a.json

Deliberately preserved:
  * everything numeric - counters, PoE milliwatts, speeds, statuses, bitmaps
  * the leading space in `ifAlias`, because that is the bug a test pins down
  * `Not Avail` as an entPhysicalSerialNum value, because the selection logic
    has to filter it out
  * a serial number with trailing spaces, because that has to be stripped too
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

FAKE_HOST = "192.0.2.10"          # RFC 5737 documentation range
FAKE_SYSNAME = "switch-test"
FAKE_CHASSIS_SERIAL = "TESTSERIAL1"
FAKE_MODULE_SERIAL = "TESTMODULE01    "   # trailing spaces on purpose
FAKE_MODULE_MODEL = "TESTXCVR"
KEEP_SERIALS = {"Not Avail"}      # vendor placeholder, not identifying


def sanitize(snap: dict) -> tuple[dict, list[str]]:
    log = []
    out = json.loads(json.dumps(snap))  # deep copy

    if out.get("host"):
        log.append(f"host: {out['host']!r} -> {FAKE_HOST!r}")
        out["host"] = FAKE_HOST

    # --- scalars ---
    if OID_SYS_NAME in out.get("get", {}):
        old = out["get"][OID_SYS_NAME]["value"]
        out["get"][OID_SYS_NAME]["value"] = FAKE_SYSNAME
        log.append(f"sysName: {old!r} -> {FAKE_SYSNAME!r}")

    # sysDescr: the model stays, because model detection and the sw_version
    # parsing test both rest on it. But the build path and the exact firmware
    # level identify one specific unit - keep the shape, drop the digits.
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

    # --- serial number table ---
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

    # --- model table: the chassis model stays, module models do not ---
    # The chassis model is what the integration recognises, and it is the very
    # product being supported. Plugged-in SFP modules, though, reveal which
    # uplink runs where.
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

    # --- ifAlias: physical ports, VLAN interfaces, the rest ---
    names = walks.get(OID_IF_NAME, {})
    aliases = walks.get(OID_IF_ALIAS, {})
    scrubbed = 0
    for idx, value in list(aliases.items()):
        if not value.strip():
            continue
        name = names.get(idx, "")
        lead = " " if value.startswith(" ") else ""   # preserve the bug
        if name.isdigit():
            new = f"{lead}device-{int(name):02d}"
        elif (m := re.fullmatch(r"VLAN(\d+)", name)):
            new = f"{lead}vlan-{m.group(1)}"
        elif name.startswith("lo"):
            continue                                   # lo0..lo7 are generic
        else:
            new = f"{lead}iface-{idx}"
        aliases[idx] = new
        scrubbed += 1
    log.append(f"ifAlias: scrubbed {scrubbed} values (leading space preserved)")

    # DEFAULT_VLAN as an ifName is the AOS-S default, and the other VLANxx are
    # just numbers - those stay. ifDescr on a physical port is a digit, stays too.
    odd = [
        f"{idx}={value!r}"
        for idx, value in walks.get(OID_IF_DESCR, {}).items()
        if not value.isdigit() and "loopback" not in value.lower()
        and not re.fullmatch(r"(DEFAULT_)?VLAN\d*", value)
    ]
    if odd:
        log.append(f"WARNING, unrecognised ifDescr values: {odd[:5]}")

    return out, log


def audit(snap: dict) -> list[str]:
    """Final check: is anything left that looks like a private IP, a MAC
    address, or text that is not generic."""
    blob = json.dumps(snap, ensure_ascii=False)
    problems = []
    for ip in set(re.findall(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", blob)):
        octets = [int(o) for o in ip.split(".")]
        if any(o > 255 for o in octets):
            continue
        if octets[0] == 10 or (octets[0] == 192 and octets[1] == 168) or (
            octets[0] == 172 and 16 <= octets[1] <= 31
        ):
            problems.append(f"private IP address: {ip}")
    for mac in set(re.findall(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", blob)):
        problems.append(f"MAC address: {mac}")
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
        print("\nFAILED - identifying data remains:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    with open(args.dest, "w", encoding="utf-8") as fh:
        json.dump(clean, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"\naudit clean -> {args.dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
