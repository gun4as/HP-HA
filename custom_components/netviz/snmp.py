"""
Asinhronais SNMP klients. Apzināti bez neviena Home Assistant importa, lai
šo moduli var palaist un testēt atsevišķi. Failu palaiž tieši - ar `-m` tiktu
importēta vecāku pakete un līdz ar to viss Home Assistant:

    python3 custom_components/netviz/snmp.py 192.0.2.10 public

Lietojam pysnmp 7.x asyncio API, to pašu versiju, ko HA Core jau ved līdzi
priekš `snmp` un `brother` integrācijām -> HACS neko papildus neinstalēs.
"""

from __future__ import annotations

import asyncio
import logging
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

# --- HP-ICF-POE-MIB (ActualPower ir MILIVATOS) ---
OID_HP_POE_MW = "1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8"
# 1.3.6.1.4.1.11.2.14.11.1.9.1.6.1.4 apzināti netiek lasīts: pret JL357A tas
# atgriež 370, t.i. maksimālo, nevis atlikušo jaudu (UI tajā pašā mirklī rādīja
# 346 W atlikuma). Atlikums ir poe_budget - poe_used.

# --- BRIDGE / Q-BRIDGE ---
OID_BASEPORT_IFINDEX = "1.3.6.1.2.1.17.1.4.1.2"
OID_DOT1Q_PVID = "1.3.6.1.2.1.17.7.1.4.5.1.1"
OID_VLAN_EGRESS = "1.3.6.1.2.1.17.7.1.4.3.1.2"
OID_VLAN_UNTAGGED = "1.3.6.1.2.1.17.7.1.4.3.1.4"

# --- sistēma ---
OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"
OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
# ENTITY-MIB entPhysicalSerialNum. Tabula, nevis `.1`: uz AOS-S šasija ir
# indekss 1001, un tabulā ir arī moduļu un barošanas bloku ieraksti, no kuriem
# daļa ir tukši vai satur ražotāja vietturi.
OID_ENT_SERIAL_TABLE = "1.3.6.1.2.1.47.1.1.1.1.11"
# Vērtības, kas formāli nav tukšas, bet seriālnumurs nav
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
    """Agents neatbild vai autentifikācija neizdevās."""


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
            raise SnmpConnectionError("SNMPv3 bez lietotājvārda")
        return UsmUserData(
            creds.username,
            authKey=creds.auth_key or None,
            privKey=creds.priv_key or None,
            authProtocol=AUTH_PROTOCOLS.get(creds.auth_protocol, usmHMACSHAAuthProtocol),
            privProtocol=PRIV_PROTOCOLS.get(creds.priv_protocol, usmAesCfb128Protocol),
        )
    # mpModel 1 = SNMPv2c. SNMPv1 (mpModel 0) netiek atbalstīts: walk() lieto
    # GETBULK, kas ir tikai v2c+, un v1 GET ar vienu neeksistējošu OID atgriež
    # noSuchName visam pieprasījumam, nevis per-varbind.
    return CommunityData(creds.community, mpModel=1)


def _numeric(oid) -> str:
    return ".".join(str(part) for part in oid.get_oid())


def _as_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _portlist(raw: bytes) -> set[int]:
    """Q-BRIDGE PortList bitmaps -> dot1dBasePort numuru kopa."""
    ports: set[int] = set()
    for byte_index, byte in enumerate(raw):
        for bit in range(8):
            if byte & (0x80 >> bit):
                ports.add(byte_index * 8 + bit + 1)
    return ports


class SnmpClient:
    """Viens agents. Dzīvo tik ilgi, cik config entry."""

    def __init__(self, creds: SnmpCredentials) -> None:
        self._creds = creds
        self._engine = SnmpEngine()
        self._auth = _auth_data(creds)
        self._transport: UdpTransportTarget | None = None
        self._lock = asyncio.Lock()
        self._prev: _Snapshot | None = None
        self._vlan_cache: tuple[float, dict[int, dict]] | None = None
        self._unmatched: frozenset[str] | None = None

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
        except Exception:  # noqa: BLE001 - aizvēršana nedrīkst mest ārā
            _LOGGER.debug("dispatcher aizvēršana neizdevās", exc_info=True)

    # ---------------------------------------------------------------- primitīvi

    async def walk(self, base: str, raw_bytes: bool = False) -> dict[str, object]:
        """Atgriež {indeksa_sufikss: vērtība}. Tukšs koks -> tukšs dict."""
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
            # Pieprasījums kā vienība neizdevās (tooBig, genErr, ...). Varbind
            # vērtības tādā gadījumā nav lietojamas, un tās klusi atgriezt
            # nozīmētu rādīt None visiem sistēmas sensoriem bez pēdas logā.
            raise SnmpConnectionError(
                f"GET neizdevās: {err_stat.prettyPrint()} "
                f"(varbind {int(_idx) if _idx else '?'})"
            )
        out: dict[str, object] = {}
        for oid, value in binds:
            name = value.__class__.__name__
            if name in ("NoSuchObject", "NoSuchInstance", "EndOfMibView"):
                continue
            out[_numeric(oid)] = value
        return out

    # ------------------------------------------------------------------ augstāk

    async def _serial(self) -> str | None:
        """Šasijas seriālnumurs no entPhysicalSerialNum.

        Ņem pirmo lietojamo vērtību augošā indeksu secībā, jo šasija ENTITY-MIB
        tabulā vienmēr ir pirms tajā iespraustajiem moduļiem. Izmet tukšos, kā
        arī ražotāja vietturus un moduļu seriālnumurus ar liekām atstarpēm.
        """
        try:
            table = await self.walk(OID_ENT_SERIAL_TABLE)
        except SnmpConnectionError:
            _LOGGER.debug("entPhysicalSerialNum nav pieejams", exc_info=True)
            return None
        for index in sorted(table, key=lambda k: [int(p) for p in k.split(".")]):
            value = str(table[index]).strip()
            if value and value.lower() not in SERIAL_PLACEHOLDERS:
                return value
        return None

    async def probe(self) -> dict[str, str | None]:
        """Config flow validācijai. Met SnmpConnectionError, ja agents klusē."""
        async with self._lock:
            data = await self.get_many([OID_SYS_NAME, OID_SYS_DESCR])
            if not data:
                raise SnmpConnectionError("agents neatbildēja")
            serial = await self._serial()
        return {
            "name": str(data.get(OID_SYS_NAME, "")).strip() or None,
            "descr": str(data.get(OID_SYS_DESCR, "")).strip() or None,
            "serial": serial,
        }

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
        egress = await self.walk(OID_VLAN_EGRESS, raw_bytes=True)
        untagged = await self.walk(OID_VLAN_UNTAGGED, raw_bytes=True)
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

    async def poll(self, ports: list[dict], with_vlans: bool = True) -> dict:
        """Viens pilns cikls. `ports` nāk no modeļa JSON."""
        async with self._lock:
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
            detect = await self.walk(OID_PETH_DETECT)
            poe_mw = await self.walk(OID_HP_POE_MW)
            vlan_map = await self._vlans() if with_vlans else {}

            system_raw = await self.get_many(
                [
                    OID_SYS_NAME,
                    OID_SYS_DESCR,
                    OID_SYS_UPTIME,
                    OID_CPU,
                    OID_MEM_FREE,
                    OID_MEM_USED,
                ]
            )
            main_power = await self.walk(OID_PETH_MAIN_POWER)
            main_cons = await self.walk(OID_PETH_MAIN_CONS)

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
                    # AOS-S atdod ifAlias tā, kā tas ierakstīts konfigurācijā,
                    # un tur mēdz būt atstarpe priekšā
                    "alias": str(alias.get(key, "") or "").strip(),
                    "rx_bytes": rx,
                    "tx_bytes": tx,
                    "rx_bps": rx_bps,
                    "tx_bps": tx_bps,
                }

                if pdef.get("poe"):
                    pidx = str(pdef.get("poe_index", f"1.{pid}"))
                    status = _as_int(detect.get(pidx))
                    milliwatts = _as_int(poe_mw.get(pidx))
                    port["poe_status"] = DETECT_STATUS.get(status, "unknown")
                    port["poe_power"] = (
                        round(milliwatts / 1000, 1) if milliwatts is not None else None
                    )

                vinfo = vlan_map.get(ifindex)
                if vinfo:
                    port["pvid"] = vinfo.get("pvid")
                    port["vlans"] = vinfo.get("vlans", [])
                    tagged = [
                        v for v in vinfo.get("vlans", [])
                        if v not in vinfo.get("untagged", [])
                    ]
                    port["mode"] = "trunk" if tagged else "access"

                out_ports[pid] = port

            self._prev = snap

            # Ja modeļa `ifname` nesakrīt ar to, ko atdod switch, porti klusi
            # pazustu un visas entītijas kļūtu nepieejamas bez paskaidrojuma.
            # Brīdinām, bet tikai kad kopa mainās - citādi spams ik 30 sekundes.
            unmatched = frozenset(
                str(p["id"]) for p in ports if str(p["id"]) not in out_ports
            )
            if unmatched != self._unmatched:
                if unmatched:
                    _LOGGER.warning(
                        "%s: %d no %d modeļa portiem nesakrita ar switch'a ifName; "
                        "nesakritušie: %s; switch atdeva: %s",
                        self._creds.host,
                        len(unmatched),
                        len(ports),
                        sorted(unmatched)[:10],
                        sorted(by_name)[:10],
                    )
                elif self._unmatched:
                    _LOGGER.info("%s: visi modeļa porti atkal sakrīt", self._creds.host)
                self._unmatched = unmatched

            uptime = _as_int(system_raw.get(OID_SYS_UPTIME))
            system = {
                "name": str(system_raw.get(OID_SYS_NAME, "")) or None,
                "descr": str(system_raw.get(OID_SYS_DESCR, "")) or None,
                "uptime": uptime // 100 if uptime is not None else None,
                "cpu": _as_int(system_raw.get(OID_CPU)),
                "mem_free": _as_int(system_raw.get(OID_MEM_FREE)),
                "mem_used": _as_int(system_raw.get(OID_MEM_USED)),
                "poe_budget": _as_int(next(iter(main_power.values()), None)),
                "poe_used": _as_int(next(iter(main_cons.values()), None)),
                "ports_up": sum(1 for p in out_ports.values() if p["link"]),
                "ports_total": len(out_ports),
            }

        return {"system": system, "ports": out_ports}


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
