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
# entPhysicalSerialNum values that are not serial numbers at all. They say
# nothing about a particular device - "rb400_usb" is identical on every RB2011 -
# and they must survive sanitising, because rejecting them is exactly what the
# serial selection logic has to get right. Scrubbing them would quietly delete
# the test case.
KEEP_SERIALS = {"not avail", "not available", "none", "n/a", "unknown", "rb400_usb"}

OID_MTXR_SERIAL = "1.3.6.1.4.1.14988.1.1.7.3.0"
OID_MTXR_POE_NAME = "1.3.6.1.4.1.14988.1.1.15.1.1.2"
OID_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
OID_WL_AP_SSID = "1.3.6.1.4.1.14988.1.1.1.3.1.4"
OID_WL_REG_SSID = "1.3.6.1.4.1.14988.1.1.1.5.1.12"
# Both registration tables are indexed by the client MAC, six decimal octets
# followed by the interface index. The values are harmless, the index is not.
# Table 2 is the local one on a standalone AP, table 5 the CAPsMAN one.
OID_WL_REG_PREFIXES = ("1.3.6.1.4.1.14988.1.1.1.2.1", "1.3.6.1.4.1.14988.1.1.1.5.1")

# Storage rows that name generic hardware. Anything else - a USB stick, say -
# tends to carry a model and a serial in its description.
KEEP_STORAGE = {"main memory", "system disk", "memory buffers", "cached memory"}

# An interface name that gives nothing away. On AOS-S ifName is just the port
# number; on RouterOS the defaults are etherN, wlanN, sfpN, bridge, vlanN.
RE_GENERIC_IFNAME = re.compile(
    r"\d+|lo\d*|bridge\d*|(?:DEFAULT_)?VLAN\d*|vlan\d+|ether\d+|wlan\d+|sfp[\w+-]*",
    re.IGNORECASE,
)
# ...and one that starts with such a token and then carries the admin's notes,
# like "ether2 printer" or "ether1wan backup" - note that the separator is not
# always a space, so the token match cannot rely on one.
RE_PORT_PREFIX = re.compile(r"(ether\d+|wlan\d+|vlan\d+|bridge\d*|sfp\d+)(\D.*)")


def scrub_ifname(value: str, index: str) -> str | None:
    """Replacement for an interface name, or None if it is already generic.

    Keeps the shape on purpose: a name with a space in it is exactly the case
    that breaks matching ports by name, so the fixture has to keep one.
    """
    v = value.strip()
    if not v or RE_GENERIC_IFNAME.fullmatch(v):
        return None
    if match := RE_PORT_PREFIX.fullmatch(v):
        return f"{match.group(1)} desc-{index}"
    return f"iface-{index}"


def is_clean_ifname(value: str, index: str) -> bool:
    """True if the name is generic already, or is something scrub_ifname made."""
    v = value.strip()
    return (
        not v
        or bool(RE_GENERIC_IFNAME.fullmatch(v))
        or v == f"iface-{index}"
        or v.endswith(f" desc-{index}")
    )


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
        if (oid.startswith(OID_ENT_SERIAL) or oid == OID_MTXR_SERIAL) and rec.get("value"):
            old = rec["value"]
            rec["value"] = FAKE_CHASSIS_SERIAL
            log.append(f"GET {oid}: {old!r} -> {FAKE_CHASSIS_SERIAL!r}")

    walks = out.get("walks", {})

    # --- serial number table ---
    serials = walks.get(OID_ENT_SERIAL, {})
    seen = 0
    for idx in sorted(serials, key=lambda k: int(k)):
        value = serials[idx]
        if not value.strip() or value.strip().lower() in KEEP_SERIALS:
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

    # --- interface names -----------------------------------------------------
    # On AOS-S ifName is a port number and harmless. On RouterOS it is whatever
    # the admin typed - "ether2 printer", "wan", "ether3 trunk" - and that is a
    # map of the network. ifDescr carries the same value there, so both go.
    # mtxrPOEName is an interface name as well.
    for oid, label in (
        (OID_IF_NAME, "ifName"),
        (OID_IF_DESCR, "ifDescr"),
        (OID_MTXR_POE_NAME, "mtxrPOEName"),
    ):
        table = walks.get(oid, {})
        renamed = 0
        for idx, value in list(table.items()):
            if (new := scrub_ifname(value, idx.split(".")[0])) is not None:
                table[idx] = new
                renamed += 1
        if renamed:
            log.append(f"{label}: scrubbed {renamed} values (port token kept)")

    # --- wireless ------------------------------------------------------------
    # An SSID names a household as surely as a hostname does, and on a CAPsMAN
    # controller the interface names carry the identity of every access point:
    # "24Ghz-<ap name>-1-2". Both go. The band prefix goes with them, and that is
    # deliberate - it is a name the operator chose, not something the device
    # reports, so nothing may parse a band out of it.
    ssids: dict[str, str] = {}
    for oid in (OID_WL_AP_SSID, OID_WL_REG_SSID):
        table = walks.get(oid, {})
        for idx, value in list(table.items()):
            name = value.strip()
            if not name:
                continue
            ssids.setdefault(name, f"ssid-{len(ssids) + 1}")
            table[idx] = ssids[name]
    if ssids:
        log.append(f"SSID: {len(ssids)} unique replaced with ssid-N")

    # The registration table index embeds a client MAC. Re-key it so the rows
    # keep their shape - six octets plus an interface index - without the MACs.
    macs: dict[str, str] = {}
    for oid, table in list(walks.items()):
        if not oid.startswith(OID_WL_REG_PREFIXES):
            continue
        rekeyed = {}
        for idx, value in table.items():
            parts = idx.split(".")
            if len(parts) >= 7:
                mac, tail = ".".join(parts[:6]), ".".join(parts[6:])
                if mac not in macs:
                    n = len(macs) + 1
                    macs[mac] = f"2.0.0.0.{n // 256}.{n % 256}"
                idx = f"{macs[mac]}.{tail}"
            rekeyed[idx] = value
        walks[oid] = rekeyed
    if macs:
        log.append(f"CAPsMAN registrations: {len(macs)} client MACs re-keyed")

    # --- storage rows --------------------------------------------------------
    # A removable disk row reads like "disk: <brand> <model> [<serial>]" - a model
    # and a serial number wearing a trench coat.
    storage = walks.get(OID_HR_STORAGE_DESCR, {})
    for idx, value in list(storage.items()):
        if value.strip().lower() not in KEEP_STORAGE:
            log.append(f"hrStorageDescr[{idx}]: {value!r} -> 'storage-{idx}'")
            storage[idx] = f"storage-{idx}"

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

    # Belt and braces on the interface names: scrub_ifname returns None only for
    # names that are already generic, so after scrubbing nothing here should be
    # left. If something is, a table was missed rather than a value.
    walks = snap.get("walks", {})
    for oid, label in (
        (OID_IF_NAME, "ifName"),
        (OID_IF_DESCR, "ifDescr"),
        (OID_MTXR_POE_NAME, "mtxrPOEName"),
    ):
        for idx, value in walks.get(oid, {}).items():
            if not is_clean_ifname(value, idx.split(".")[0]):
                problems.append(f"{label}[{idx}] is not generic: {value!r}")

    for idx, value in walks.get(OID_HR_STORAGE_DESCR, {}).items():
        if value.strip().lower() not in KEEP_STORAGE and value != f"storage-{idx}":
            problems.append(f"hrStorageDescr[{idx}] is not generic: {value!r}")

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
