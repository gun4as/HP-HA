"""Takes a full SNMP snapshot off a real switch and saves it as a test fixture.

Read-only. Fetches exactly the OIDs that snmp.py:poll() and probe() use, plus two
counter samples with a pause between them, so the rx_bps/tx_bps maths is testable
as well.

The output does NOT belong in the repository - run it through
tools/sanitize_fixture.py first.

    python capture_fixture.py 192.0.2.10 public tests/fixtures/jl357a-live.json
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    bulk_walk_cmd,
    get_cmd,
)

# tables that poll() walks; raw=True for the ones whose value is a bitmap
WALK_OIDS = {
    "1.3.6.1.2.1.2.2.1.2": ("ifDescr", False),
    # ifType is how physical ports are found without trusting ifName: 6 is
    # ethernetCsmacd everywhere, while ifName is whatever the admin typed
    "1.3.6.1.2.1.2.2.1.3": ("ifType", False),
    "1.3.6.1.2.1.2.2.1.7": ("ifAdminStatus", False),
    "1.3.6.1.2.1.2.2.1.8": ("ifOperStatus", False),
    "1.3.6.1.2.1.31.1.1.1.1": ("ifName", False),
    "1.3.6.1.2.1.31.1.1.1.15": ("ifHighSpeed", False),
    "1.3.6.1.2.1.31.1.1.1.18": ("ifAlias", False),
    "1.3.6.1.2.1.31.1.1.1.6": ("ifHCInOctets", False),
    "1.3.6.1.2.1.31.1.1.1.10": ("ifHCOutOctets", False),
    "1.3.6.1.2.1.105.1.1.1.5": ("pethPsePortClass", False),
    "1.3.6.1.2.1.105.1.1.1.6": ("pethPsePortDetectionStatus", False),
    "1.3.6.1.2.1.105.1.3.1.1.2": ("pethMainPsePower", False),
    "1.3.6.1.2.1.105.1.3.1.1.4": ("pethMainPseConsumptionPower", False),
    "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8": ("hpicfPoePethPsePortActualPower", False),
    "1.3.6.1.4.1.11.2.14.11.1.9.1.6.1.4": ("hpicfPoePethPseAvail", False),
    "1.3.6.1.2.1.17.1.4.1.2": ("dot1dBasePortIfIndex", False),
    "1.3.6.1.2.1.17.7.1.4.5.1.1": ("dot1qPvid", False),
    "1.3.6.1.2.1.17.7.1.4.3.1.2": ("dot1qVlanStaticEgressPorts", True),
    "1.3.6.1.2.1.17.7.1.4.3.1.4": ("dot1qVlanStaticUntaggedPorts", True),
    # tables poll() does not use, but which the serial number fix needs
    # entPhysicalClass is what makes the serial trustworthy: the device says
    # which row is the chassis, instead of us guessing by index order
    "1.3.6.1.2.1.47.1.1.1.1.5": ("entPhysicalClass", False),
    "1.3.6.1.2.1.47.1.1.1.1.11": ("entPhysicalSerialNum", False),
    "1.3.6.1.2.1.47.1.1.1.1.13": ("entPhysicalModelName", False),
    # --- other vendors, for the profile work ---
    # These come back empty on AOS-S and populated on RouterOS, or the other way
    # round. Capturing both means one snapshot documents what a vendor does NOT
    # answer, which is exactly what the profile has to encode.
    "1.3.6.1.4.1.14988.1.1.15.1.1.2": ("mtxrPOEName", False),
    "1.3.6.1.4.1.14988.1.1.15.1.1.3": ("mtxrPOEStatus", False),
    "1.3.6.1.4.1.14988.1.1.15.1.1.4": ("mtxrPOEVoltage", False),
    "1.3.6.1.4.1.14988.1.1.15.1.1.5": ("mtxrPOECurrent", False),
    "1.3.6.1.4.1.14988.1.1.15.1.1.6": ("mtxrPOEPower", False),
    "1.3.6.1.2.1.25.3.3.1.2": ("hrProcessorLoad", False),
    "1.3.6.1.2.1.25.2.3.1.3": ("hrStorageDescr", False),
    "1.3.6.1.2.1.25.2.3.1.5": ("hrStorageSize", False),
    "1.3.6.1.2.1.25.2.3.1.6": ("hrStorageUsed", False),
    "1.3.6.1.2.1.25.2.3.1.4": ("hrStorageAllocationUnits", False),
}

GET_OIDS = {
    "1.3.6.1.2.1.1.1.0": "sysDescr",
    "1.3.6.1.2.1.1.2.0": "sysObjectID",
    "1.3.6.1.2.1.1.3.0": "sysUpTime",
    "1.3.6.1.2.1.1.5.0": "sysName",
    "1.3.6.1.4.1.14988.1.1.7.3.0": "mtxrSerialNumber",
    "1.3.6.1.4.1.14988.1.1.7.4.0": "mtxrFirmwareVersion",
    "1.3.6.1.2.1.47.1.1.1.1.11.1": "entPhysicalSerialNum.1",
    "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0": "hpSwitchCpuStat",
    "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1": "hpLocalMemFreeBytes",
    "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.7.1": "hpLocalMemAllocBytes",
}

COUNTERS = ("1.3.6.1.2.1.31.1.1.1.6", "1.3.6.1.2.1.31.1.1.1.10")


def numeric(oid):
    return ".".join(str(p) for p in oid.get_oid())


async def walk(engine, auth, target, base, raw):
    out, prefix = {}, base + "."
    async for ei, es, _i, vbs in bulk_walk_cmd(
        engine, auth, target, ContextData(), 0, 25,
        ObjectType(ObjectIdentity(base)), lexicographicMode=False,
    ):
        if ei:
            raise RuntimeError(f"{base}: {ei}")
        if es:
            break
        stop = False
        for oid, value in vbs:
            n = numeric(oid)
            if not n.startswith(prefix):
                stop = True
                break
            if raw:
                out[n[len(prefix):]] = base64.b64encode(bytes(value)).decode()
            else:
                out[n[len(prefix):]] = value.prettyPrint()
        if stop:
            break
    return out


async def main(host, community, out_path, gap=8.0):
    engine = SnmpEngine()
    auth = CommunityData(community, mpModel=1)
    target = await UdpTransportTarget.create((host, 161), timeout=4, retries=2)

    snap = {"host": host, "walks": {}, "walks_raw_b64": [], "get": {}, "counters_t1": {}}

    for base, (label, raw) in WALK_OIDS.items():
        snap["walks"][base] = await walk(engine, auth, target, base, raw)
        if raw:
            snap["walks_raw_b64"].append(base)
        print(f"  {label:32} {len(snap['walks'][base]):>3} rows")

    ei, es, _i, binds = await get_cmd(
        engine, auth, target, ContextData(),
        *[ObjectType(ObjectIdentity(o)) for o in GET_OIDS],
    )
    if ei:
        raise RuntimeError(str(ei))
    for oid, value in binds:
        cls = value.__class__.__name__
        snap["get"][numeric(oid)] = {
            "value": None if cls in ("NoSuchObject", "NoSuchInstance") else value.prettyPrint(),
            "type": cls,
        }
    print(f"  GET: {len(snap['get'])} OID, "
          f"{sum(1 for v in snap['get'].values() if v['value'] is None)} empty")

    print(f"\n  waiting {gap:.0f}s for the second counter sample...")
    await asyncio.sleep(gap)
    for base in COUNTERS:
        snap["counters_t1"][base] = await walk(engine, auth, target, base, False)
    snap["counter_gap_seconds"] = gap

    # how many ports actually moved -> whether the rate test has anything to chew on
    moved = 0
    for base in COUNTERS:
        t0, t1 = snap["walks"][base], snap["counters_t1"][base]
        moved += sum(1 for k in t0 if k in t1 and int(t1[k]) > int(t0[k]))
    print(f"  counters moved on {moved} interfaces")

    path = Path(out_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(f"\n-> {path} ({path.stat().st_size // 1024} KB)")
    engine.close_dispatcher()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1], sys.argv[2], sys.argv[3]))
