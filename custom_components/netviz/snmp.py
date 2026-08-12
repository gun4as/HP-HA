"""
Async SNMP client. Deliberately free of any Home Assistant import so the module
can be run and tested on its own. Run the file directly - with `-m` Python would
import the parent package, and with it the whole of Home Assistant:

    python3 custom_components/netviz/snmp.py 192.0.2.10 public

Uses the pysnmp 7.x asyncio API, pinned to the same version HA Core already
ships for its `snmp` and `brother` integrations, so HACS installs nothing extra.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

from pysnmp.hlapi.v3arch.asyncio import (
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_walk_cmd,
    get_cmd,
    usmAesCfb128Protocol,
    usmAesCfb192Protocol,
    usmAesCfb256Protocol,
    usmDESPrivProtocol,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
)

try:  # inside Home Assistant this is a package
    from . import profiles
except ImportError:  # ...and standalone it is a plain directory on sys.path
    import profiles

_LOGGER = logging.getLogger(__name__)

AUTH_PROTOCOLS = {
    "sha": usmHMACSHAAuthProtocol,
    "md5": usmHMACMD5AuthProtocol,
}
PRIV_PROTOCOLS = {
    "aes": usmAesCfb128Protocol,
    "aes192": usmAesCfb192Protocol,
    "aes256": usmAesCfb256Protocol,
    "des": usmDESPrivProtocol,
}

# --- IF-MIB ---
OID_IF_DESCR = "1.3.6.1.2.1.2.2.1.2"
OID_IF_ADMIN = "1.3.6.1.2.1.2.2.1.7"
OID_IF_OPER = "1.3.6.1.2.1.2.2.1.8"
OID_IF_NAME = "1.3.6.1.2.1.31.1.1.1.1"
OID_IF_HISPEED = "1.3.6.1.2.1.31.1.1.1.15"
OID_IF_ALIAS = "1.3.6.1.2.1.31.1.1.1.18"
OID_IF_HCIN = "1.3.6.1.2.1.31.1.1.1.6"
OID_IF_HCOUT = "1.3.6.1.2.1.31.1.1.1.10"

# --- POWER-ETHERNET-MIB (RFC 3621) ---
OID_PETH_DETECT = "1.3.6.1.2.1.105.1.1.1.6"
OID_PETH_MAIN_POWER = "1.3.6.1.2.1.105.1.3.1.1.2"
OID_PETH_MAIN_CONS = "1.3.6.1.2.1.105.1.3.1.1.4"

# --- HP-ICF-POE-MIB (ActualPower is in MILLIWATTS) ---
OID_HP_POE_MW = "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8"
# 1.3.6.1.4.1.11.2.14.11.1.9.1.6.1.4 is deliberately not read: against a JL357A
# it returns 370, i.e. the maximum rather than the remaining power (the web UI
# showed 346 W remaining at the same moment). Remaining is poe_budget - poe_used.

# --- BRIDGE / Q-BRIDGE ---
OID_BASEPORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
OID_DOT1Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
OID_VLAN_EGRESS = "1.3.6.1.2.1.17.7.1.4.3.1.2"
OID_VLAN_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.3.1.4"

OID_IF_TYPE = "1.3.6.1.2.1.2.2.1.3"

# --- system ---
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_OBJECT_ID = "1.3.6.1.2.1.1.2.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
# ENTITY-MIB entPhysicalSerialNum. The table, not `.1`: on AOS-S the chassis is
# index 1001, and the table also holds module and power supply rows, some of
# which are empty or contain a vendor placeholder.
OID_ENT_SERIAL_TABLE = "1.3.6.1.2.1.47.1.1.1.1.11"
# ...and the class column, which is what makes the serial trustworthy. Picking
# the lowest index instead works on AOS-S and fails on RouterOS, where an
# unknown-class row answers "rb400_usb" - a component name that is identical on
# every unit of that model, so two devices would collide on one unique_id.
OID_ENT_CLASS = "1.3.6.1.2.1.47.1.1.1.1.5"
ENT_CLASS_CHASSIS = 3
# Values that are technically non-empty but are not a serial number
SERIAL_PLACEHOLDERS = {"not avail", "not available", "none", "n/a", "unknown", "0"}
OID_CPU = "1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"
OID_MEM_FREE = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1"
OID_MEM_USED = "1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.7.1"

DETECT_STATUS = {
    1: "disabled",
    2: "searching",
    3: "delivering",
    4: "fault",
    5: "test",
    6: "other_fault",
}


class SnmpConnectionError(Exception):
    """The agent does not answer, or authentication failed."""


@dataclass(slots=True)
class SnmpCredentials:
    host: str
    port: int = 161
    version: str = "2c"
    community: str = "public"
    username: str | None = None
    auth_protocol: str = "sha"
    auth_key: str | None = None
    priv_protocol: str = "aes"
    priv_key: str | None = None
    timeout: int = 4
    retries: int = 2


@dataclass(slots=True)
class _Snapshot:
    ts: float
    counters: dict[int, tuple[int, int]] = field(default_factory=dict)


def _auth_data(creds: SnmpCredentials):
    if str(creds.version) == "3":
        if not creds.username:
            raise SnmpConnectionError("SNMPv3 requires a username")
        return UsmUserData(
            creds.username,
            authKey=creds.auth_key or None,
            privKey=creds.priv_key or None,
            authProtocol=AUTH_PROTOCOLS.get(creds.auth_protocol, usmHMACSHAAuthProtocol),
            privProtocol=PRIV_PROTOCOLS.get(creds.priv_protocol, usmAesCfb128Protocol),
        )
    # mpModel 1 = SNMPv2c. SNMPv1 (mpModel 0) is not supported: walk() uses
    # GETBULK, which is v2c and later only, and a v1 GET containing one
    # non-existent OID returns noSuchName for the whole request, not per varbind.
    return CommunityData(creds.community, mpModel=1)


# AOS-S sysDescr:
#   Aruba JL357A 2540-48G-PoE+-4SFP+ Switch, revision YC.16.11.0029, ROM ... (...)
# The `revision` field is the one we want. `split(",")[-1]` would pick up the ROM
# version together with the build path, truncated mid-word. This lives here
# rather than next to the entity because it is a pure sysDescr parser, and this
# module is the one that can be imported and tested without Home Assistant.
_RE_REVISION = re.compile(r"revision\s+([A-Za-z0-9._-]+)", re.IGNORECASE)
_RE_VERSIONISH = re.compile(r"\b([A-Za-z]{0,3}\.?\d+\.\d+[.\d]*)\b")


def sw_version_from_descr(descr: str | None) -> str | None:
    """Firmware version from sysDescr, or None if the format is unrecognised."""
    if not descr:
        return None
    if match := _RE_REVISION.search(descr):
        return match.group(1).rstrip(".,")
    # Different vendor or different format: take the first thing that looks like
    # a version. None beats putting a model name or a file path on the device page.
    if match := _RE_VERSIONISH.search(descr):
        return match.group(1)
    return None


def _numeric(oid) -> str:
    return ".".join(str(part) for part in oid.get_oid())


def _as_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _portlist(raw: bytes) -> set[int]:
    """Q-BRIDGE PortList bitmap -> set of dot1dBasePort numbers."""
    ports: set[int] = set()
    for byte_index, byte in enumerate(raw):
        for bit in range(8):
            if byte & (0x80 >> bit):
                ports.add(byte_index * 8 + bit + 1)
    return ports


class SnmpClient:
    """One agent. Lives as long as the config entry."""

    def __init__(
        self, creds: SnmpCredentials, profile: profiles.Profile | None = None
    ) -> None:
        self._creds = creds
        self._engine = SnmpEngine()
        self._auth = _auth_data(creds)
        self._transport: UdpTransportTarget | None = None
        self._lock = asyncio.Lock()
        self._prev: _Snapshot | None = None
        self._vlan_cache: tuple[float, dict[int, dict]] | None = None
        self._unmatched: frozenset[str] | None = None
        # Until sysObjectID has been read, assume nothing beyond standard MIBs.
        self.profile = profile or profiles.GENERIC
        self._detected = profile is not None

    async def _target(self) -> UdpTransportTarget:
        if self._transport is None:
            self._transport = await UdpTransportTarget.create(
                (self._creds.host, self._creds.port),
                timeout=self._creds.timeout,
                retries=self._creds.retries,
            )
        return self._transport

    def close(self) -> None:
        try:
            self._engine.close_dispatcher()
        except Exception:  # noqa: BLE001 - closing must never raise
            _LOGGER.debug("closing the dispatcher failed", exc_info=True)

    # ------------------------------------------------------------- primitives

    async def walk(self, base: str, raw_bytes: bool = False) -> dict[str, object]:
        """Return {index_suffix: value}. An empty subtree gives an empty dict."""
        target = await self._target()
        out: dict[str, object] = {}
        prefix = base + "."
        async for err_ind, err_stat, _idx, binds in bulk_walk_cmd(
            self._engine,
            self._auth,
            target,
            ContextData(),
            0,
            25,
            ObjectType(ObjectIdentity(base)),
            lexicographicMode=False,
        ):
            if err_ind:
                raise SnmpConnectionError(str(err_ind))
            if err_stat:
                _LOGGER.debug("%s: %s", base, err_stat.prettyPrint())
                break
            for oid, value in binds:
                numeric = _numeric(oid)
                if not numeric.startswith(prefix):
                    return out
                suffix = numeric[len(prefix):]
                if raw_bytes:
                    out[suffix] = bytes(value)
                else:
                    out[suffix] = value
        return out

    async def get_many(self, oids: list[str]) -> dict[str, object]:
        target = await self._target()
        err_ind, err_stat, _idx, binds = await get_cmd(
            self._engine,
            self._auth,
            target,
            ContextData(),
            *[ObjectType(ObjectIdentity(o)) for o in oids],
        )
        if err_ind:
            raise SnmpConnectionError(str(err_ind))
        if err_stat:
            # The request failed as a whole (tooBig, genErr, ...). The varbind
            # values are unusable in that case, and returning them silently
            # would show None for every system sensor with nothing in the log.
            raise SnmpConnectionError(
                f"GET failed: {err_stat.prettyPrint()} "
                f"(varbind {int(_idx) if _idx else '?'})"
            )
        out: dict[str, object] = {}
        for oid, value in binds:
            name = value.__class__.__name__
            if name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                continue
            out[_numeric(oid)] = value
        return out

    # ------------------------------------------------------------ higher level

    def _adopt(self, sys_object_id: object) -> None:
        self.profile = profiles.detect(sys_object_id)
        self._detected = True
        _LOGGER.debug(
            "%s: sysObjectID %s -> profile %s",
            self._creds.host,
            sys_object_id,
            self.profile.key,
        )

    async def _ensure_profile(self) -> None:
        """Detect on first use.

        The coordinator calls poll() straight after a restart without any probe,
        so waiting for probe() would leave every device on the generic profile -
        no PoE, no CPU - until something happened to call it.
        """
        if self._detected:
            return
        try:
            data = await self.get_many([OID_SYS_OBJECT_ID])
        except SnmpConnectionError:
            return
        self._adopt(data.get(OID_SYS_OBJECT_ID))

    def _usable_serial(self, value: object) -> str | None:
        text = str(value or "").strip()
        if not text or text.lower() in self.profile.serial.placeholders:
            return None
        return text

    async def _serial(self) -> str | None:
        """A stable per-device identifier, from wherever the profile says.

        Either the ENTITY-MIB row the device itself calls a chassis, or a vendor
        scalar. If nothing usable comes back the answer is None, which is honest
        - better than a string like `rb400_usb` that is identical on every unit
        of a model and would collide two devices onto one unique_id.
        """
        source = self.profile.serial
        if source.scalar_oid:
            try:
                data = await self.get_many([source.scalar_oid])
            except SnmpConnectionError:
                _LOGGER.debug("%s is not available", source.scalar_oid, exc_info=True)
                return None
            return self._usable_serial(data.get(source.scalar_oid))

        if not source.entity_chassis:
            return None
        try:
            serials = await self.walk(OID_ENT_SERIAL_TABLE)
        except SnmpConnectionError:
            _LOGGER.debug("entPhysicalSerialNum is not available", exc_info=True)
            return None
        if not serials:
            return None
        try:
            classes = await self.walk(OID_ENT_CLASS)
        except SnmpConnectionError:
            classes = {}

        if classes:
            candidates = [
                index for index, value in classes.items()
                if _as_int(value) == ENT_CLASS_CHASSIS
            ]
        else:
            # No class column at all: fall back to index order, where the
            # chassis precedes the modules plugged into it.
            candidates = list(serials)

        for index in sorted(candidates, key=lambda k: [int(p) for p in k.split(".")]):
            if usable := self._usable_serial(serials.get(index)):
                return usable
        return None

    async def probe(self) -> dict[str, str | None]:
        """For config flow validation. Raises SnmpConnectionError on silence.

        Also settles which profile applies, so everything after this point knows
        which private MIBs the device actually speaks.
        """
        async with self._lock:
            data = await self.get_many(
                [OID_SYS_NAME, OID_SYS_DESCR, OID_SYS_OBJECT_ID]
            )
            if not data:
                raise SnmpConnectionError("the agent did not respond")
            self._adopt(data.get(OID_SYS_OBJECT_ID))
            serial = await self._serial()
        return {
            "name": str(data.get(OID_SYS_NAME, "")).strip() or None,
            "descr": str(data.get(OID_SYS_DESCR, "")).strip() or None,
            "serial": serial,
            "profile": self.profile.key,
            "profile_name": self.profile.name,
        }

    async def discover_ports(self) -> list[dict]:
        """Physical ports straight off the device, when no model file applies.

        ifType 6 is ethernetCsmacd on every vendor, which is the only reliable
        way to tell a port from a VLAN interface, a bridge or a radio. ifName is
        not: on RouterOS it is whatever the administrator typed, so it serves as
        the label and as the key, and renaming an interface does create new
        entities - the same trade-off the model files already make.
        """
        types = await self.walk(OID_IF_TYPE)
        names = await self.walk(OID_IF_NAME)
        poe_ports: set[str] = set()
        if (poe := self.profile.poe) and poe.index == "ifindex":
            poe_ports = {k.split(".")[0] for k in await self.walk(poe.power_oid)}

        ports: list[dict] = []
        for index in sorted(
            (i for i, t in types.items() if _as_int(t) == profiles.IF_TYPE_ETHERNET),
            key=lambda k: int(k),
        ):
            name = str(names.get(index, "")).strip() or f"if{index}"
            ports.append({
                "id": name,
                "label": name,
                "kind": "rj45",
                "ifname": name,
                "ifindex": int(index),
                "poe": index in poe_ports,
                "poe_index": index,
            })
        _LOGGER.debug(
            "%s: discovered %d physical ports, %d with PoE",
            self._creds.host,
            len(ports),
            sum(1 for p in ports if p["poe"]),
        )
        return ports

    async def _vlans(self, ttl: float = 300.0) -> dict[int, dict]:
        loop = asyncio.get_running_loop()
        now = loop.time()
        if self._vlan_cache and now - self._vlan_cache[0] < ttl:
            return self._vlan_cache[1]

        base_map_raw = await self.walk(OID_BASEPORT_IFINDEX)
        bp_to_if = {
            _as_int(bp): _as_int(v)
            for bp, v in base_map_raw.items()
            if _as_int(bp) is not None and _as_int(v) is not None
        }
        # RouterOS leaves the static VLAN tables empty while filling dot1qPvid,
        # so on such a profile there is no point asking for them at all.
        if self.profile.vlan_egress:
            egress = await self.walk(OID_VLAN_EGRESS, raw_bytes=True)
            untagged = await self.walk(OID_VLAN_UNTAGGED, raw_bytes=True)
        else:
            egress, untagged = {}, {}
        pvid = await self.walk(OID_DOT1Q_PVID)

        result: dict[int, dict] = {}
        for key, raw in egress.items():
            vlan = _as_int(key.split(".")[-1])
            if vlan is None:
                continue
            untag = _portlist(untagged.get(key, b""))  # type: ignore[arg-type]
            for bp in _portlist(raw):  # type: ignore[arg-type]
                ifindex = bp_to_if.get(bp)
                if ifindex is None:
                    continue
                rec = result.setdefault(ifindex, {"vlans": [], "untagged": []})
                rec["vlans"].append(vlan)
                if bp in untag:
                    rec["untagged"].append(vlan)

        for bp, value in pvid.items():
            ifindex = bp_to_if.get(_as_int(bp) or -1)
            vv = _as_int(value)
            if ifindex is not None and vv is not None:
                result.setdefault(ifindex, {"vlans": [], "untagged": []})["pvid"] = vv

        for rec in result.values():
            rec["vlans"] = sorted(rec["vlans"])
            rec["untagged"] = sorted(rec["untagged"])

        self._vlan_cache = (now, result)
        return result

    async def _wireless(self, names: dict) -> dict:
        """Wireless clients, aggregated.

        Read from a CAPsMAN controller, this covers every access point it
        manages - a managed AP answers almost nothing about its own radios, so
        asking the controller is both the only way and the cheaper one.

        Aggregates only. The registration table is keyed by client MAC address,
        and turning those into entities would be device tracking of everyone in
        the building; Home Assistant has an integration for that already, and
        this is not it.
        """
        source = self.profile.wireless
        if source is None:
            return {}
        registrations = await self.walk(source.registration_ssid_oid)
        if not registrations:
            return {}
        signals = await self.walk(source.registration_signal_oid)

        by_ssid: dict[str, dict] = {}
        by_radio: dict[str, dict] = {}
        for index, raw_ssid in registrations.items():
            ssid = str(raw_ssid).strip() or "(hidden)"
            # index is the client MAC followed by the interface it is on
            ifindex = index.split(".")[-1]
            signal = _as_int(signals.get(index))
            for bucket in (
                by_ssid.setdefault(ssid, {"clients": 0, "_signals": []}),
                by_radio.setdefault(
                    ifindex,
                    {
                        "name": str(names.get(ifindex, "")).strip() or f"if{ifindex}",
                        "clients": 0,
                        "_signals": [],
                    },
                ),
            ):
                bucket["clients"] += 1
                if signal is not None:
                    bucket["_signals"].append(signal)

        for bucket in (*by_ssid.values(), *by_radio.values()):
            found = bucket.pop("_signals")
            bucket["signal_avg"] = round(sum(found) / len(found)) if found else None
            bucket["signal_min"] = min(found) if found else None
            bucket["signal_max"] = max(found) if found else None

        return {
            "clients": len(registrations),
            "ssids": dict(sorted(by_ssid.items())),
            "radios": dict(
                sorted(by_radio.items(), key=lambda kv: kv[1]["name"])
            ),
        }

    async def _storage(self, match: str) -> tuple[int | None, int | None]:
        """Free and used bytes from an hrStorage row, matched by description.

        Sizes are in allocation units, not bytes, and the unit is per row.
        """
        descrs = await self.walk(profiles.OID_HR_STORAGE_DESCR)
        index = next(
            (i for i, v in descrs.items() if str(v).strip().lower() == match), None
        )
        if index is None:
            return None, None
        sizes = await self.walk(profiles.OID_HR_STORAGE_SIZE)
        used = await self.walk(profiles.OID_HR_STORAGE_USED)
        units = await self.walk(profiles.OID_HR_STORAGE_UNITS)
        unit = _as_int(units.get(index), 1) or 1
        total = _as_int(sizes.get(index))
        taken = _as_int(used.get(index))
        if total is None or taken is None:
            return None, None
        return (total - taken) * unit, taken * unit

    async def poll(self, ports: list[dict], with_vlans: bool = True) -> dict:
        """One full cycle. `ports` comes from the model JSON, or from discovery."""
        async with self._lock:
            await self._ensure_profile()
            loop = asyncio.get_running_loop()
            names = await self.walk(OID_IF_NAME)
            if not any(str(v) for v in names.values()):
                names = await self.walk(OID_IF_DESCR)
            by_name = {
                str(v).strip(): _as_int(k)
                for k, v in names.items()
                if str(v).strip() and _as_int(k) is not None
            }

            oper = await self.walk(OID_IF_OPER)
            admin = await self.walk(OID_IF_ADMIN)
            speed = await self.walk(OID_IF_HISPEED)
            alias = await self.walk(OID_IF_ALIAS)
            hcin = await self.walk(OID_IF_HCIN)
            hcout = await self.walk(OID_IF_HCOUT)
            poe = self.profile.poe
            poe_power = await self.walk(poe.power_oid) if poe else {}
            poe_status = (
                await self.walk(poe.status_oid) if poe and poe.status_oid else {}
            )
            vlan_map = await self._vlans() if with_vlans else {}

            scalars = [OID_SYS_NAME, OID_SYS_DESCR, OID_SYS_UPTIME]
            cpu_source = self.profile.cpu
            if cpu_source and not cpu_source.table:
                scalars.append(cpu_source.oid)
            memory = self.profile.memory
            if memory and memory.free_oid:
                scalars += [memory.free_oid, memory.used_oid]
            system_raw = await self.get_many(scalars)

            cpu = _as_int(system_raw.get(cpu_source.oid)) if (
                cpu_source and not cpu_source.table
            ) else None
            if cpu_source and cpu_source.table:
                # RouterOS reports one row per core; a single number is what a
                # sensor can show, so average them.
                loads = [
                    v for v in (_as_int(x) for x in (await self.walk(cpu_source.oid)).values())
                    if v is not None
                ]
                cpu = round(sum(loads) / len(loads)) if loads else None

            mem_free = mem_used = None
            if memory and memory.free_oid:
                mem_free = _as_int(system_raw.get(memory.free_oid))
                mem_used = _as_int(system_raw.get(memory.used_oid))
            elif memory and memory.storage_match:
                mem_free, mem_used = await self._storage(memory.storage_match)

            wireless = await self._wireless(names) if self.profile.wireless else {}

            main_power = await self.walk(poe.main_power_oid) if (
                poe and poe.main_power_oid
            ) else {}
            main_cons = await self.walk(poe.main_consumption_oid) if (
                poe and poe.main_consumption_oid
            ) else {}

            now = loop.time()
            snap = _Snapshot(ts=now)
            out_ports: dict[str, dict] = {}

            for pdef in ports:
                pid = str(pdef["id"])
                ifindex = by_name.get(str(pdef.get("ifname", pid)))
                if ifindex is None:
                    ifindex = _as_int(pdef.get("ifindex"))
                if ifindex is None:
                    continue
                key = str(ifindex)

                rx = _as_int(hcin.get(key))
                tx = _as_int(hcout.get(key))
                if rx is not None and tx is not None:
                    snap.counters[ifindex] = (rx, tx)

                rx_bps = tx_bps = None
                prev = self._prev
                if prev and ifindex in prev.counters and rx is not None and tx is not None:
                    prx, ptx = prev.counters[ifindex]
                    dt = now - prev.ts
                    if dt > 0:
                        if rx >= prx:
                            rx_bps = round((rx - prx) * 8 / dt)
                        if tx >= ptx:
                            tx_bps = round((tx - ptx) * 8 / dt)

                port = {
                    "id": pid,
                    "ifindex": ifindex,
                    "kind": pdef.get("kind", "rj45"),
                    "link": _as_int(oper.get(key)) == 1,
                    "admin_up": _as_int(admin.get(key)) == 1,
                    "speed": _as_int(speed.get(key)),
                    # AOS-S returns ifAlias exactly as configured, and there is
                    # often a leading space in there
                    "alias": str(alias.get(key, "") or "").strip(),
                    "rx_bytes": rx,
                    "tx_bytes": tx,
                    "rx_bps": rx_bps,
                    "tx_bps": tx_bps,
                }

                if poe and pdef.get("poe"):
                    # AOS-S addresses the PoE tables by <group>.<port>, which the
                    # model file carries; RouterOS addresses them by ifIndex.
                    pidx = (
                        str(ifindex) if poe.index == "ifindex"
                        else str(pdef.get("poe_index", f"1.{pid}"))
                    )
                    raw_power = _as_int(poe_power.get(pidx))
                    status = poe.status_map.get(
                        _as_int(poe_status.get(pidx)), "unknown"
                    )
                    port["poe_status"] = status
                    # Passive PoE-out has no measurement hardware. An RB2011
                    # reports `delivering` with voltage, current and power all
                    # reading zero, and 0 W on a port that is powering something
                    # is a false measurement dressed as a real one. Unknown is
                    # the true answer.
                    if raw_power is None or (raw_power == 0 and status == "delivering"):
                        port["poe_power"] = None
                    else:
                        port["poe_power"] = round(raw_power / poe.power_divisor, 1)

                vinfo = vlan_map.get(ifindex)
                if vinfo:
                    if vinfo.get("pvid") is not None:
                        port["pvid"] = vinfo["pvid"]
                    # RouterOS fills dot1qPvid but leaves the static egress table
                    # empty. With no membership data there is no evidence for
                    # access versus trunk, and defaulting to `access` would label
                    # a trunk carrying every VLAN as an access port - a wrong
                    # answer that looks like a real one. Say nothing instead.
                    if vlans := vinfo.get("vlans"):
                        port["vlans"] = vlans
                        tagged = [v for v in vlans if v not in vinfo.get("untagged", [])]
                        port["mode"] = "trunk" if tagged else "access"

                out_ports[pid] = port

            self._prev = snap

            # If the model's `ifname` does not match what the switch returns,
            # ports would silently vanish and every entity would go unavailable
            # with no explanation. Warn, but only when the set changes -
            # otherwise this spams the log every 30 seconds.
            unmatched = frozenset(
                str(p["id"]) for p in ports if str(p["id"]) not in out_ports
            )
            if unmatched != self._unmatched:
                if unmatched:
                    _LOGGER.warning(
                        "%s: %d of %d model ports did not match the switch ifName; "
                        "unmatched: %s; switch returned: %s",
                        self._creds.host,
                        len(unmatched),
                        len(ports),
                        sorted(unmatched)[:10],
                        sorted(by_name)[:10],
                    )
                elif self._unmatched:
                    _LOGGER.info("%s: all model ports match again", self._creds.host)
                self._unmatched = unmatched

            uptime = _as_int(system_raw.get(OID_SYS_UPTIME))
            system = {
                "name": str(system_raw.get(OID_SYS_NAME, "")) or None,
                "descr": str(system_raw.get(OID_SYS_DESCR, "")) or None,
                "uptime": uptime // 100 if uptime is not None else None,
                "profile": self.profile.key,
                "cpu": cpu,
                "mem_free": mem_free,
                "mem_used": mem_used,
                "poe_budget": _as_int(next(iter(main_power.values()), None)),
                "poe_used": _as_int(next(iter(main_cons.values()), None)),
                "ports_up": sum(1 for p in out_ports.values() if p["link"]),
                "ports_total": len(out_ports),
                "wireless_clients": wireless.get("clients"),
            }

        return {"system": system, "ports": out_ports, "wireless": wireless}


async def _selftest(host: str, community: str, port: int = 161) -> None:
    import json

    client = SnmpClient(SnmpCredentials(host=host, port=port, community=community))
    print(json.dumps(await client.probe(), indent=2, ensure_ascii=False))
    ports = [{"id": "1", "ifname": "1", "poe": True, "poe_index": "1.1"}]
    print(json.dumps(await client.poll(ports), indent=2, ensure_ascii=False, default=str))
    client.close()


if __name__ == "__main__":
    import sys

    asyncio.run(
        _selftest(
            sys.argv[1],
            sys.argv[2] if len(sys.argv) > 2 else "public",
            int(sys.argv[3]) if len(sys.argv) > 3 else 161,
        )
    )
