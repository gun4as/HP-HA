"""What differs between vendors, expressed as data.

Nine devices were probed to build this, and the differences turned out not to be
a matter of swapping OIDs. The *shape* differs too: a serial number is a chosen
row of a table on one vendor and a scalar on another, CPU is one value here and
four there, PoE is indexed by port number on one and by ifIndex on the other.
So a profile describes shapes, not just addresses.

No Home Assistant import, on purpose - snmp.py has to stay runnable and testable
on its own, and this is part of the same layer.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# --- IF-MIB ifType, the vendor-neutral way to find real ports and radios ------
IF_TYPE_ETHERNET = 6
IF_TYPE_WIFI = 71

# --- ENTITY-MIB ---------------------------------------------------------------
OID_ENT_CLASS = "1.3.6.1.2.1.47.1.1.1.1.5"
OID_ENT_SERIAL = "1.3.6.1.2.1.47.1.1.1.1.11"
ENT_CLASS_CHASSIS = 3

# --- HOST-RESOURCES-MIB -------------------------------------------------------
OID_HR_CPU = "1.3.6.1.2.1.25.3.3.1.2"
OID_HR_STORAGE_DESCR = "1.3.6.1.2.1.25.2.3.1.3"
OID_HR_STORAGE_UNITS = "1.3.6.1.2.1.25.2.3.1.4"
OID_HR_STORAGE_SIZE = "1.3.6.1.2.1.25.2.3.1.5"
OID_HR_STORAGE_USED = "1.3.6.1.2.1.25.2.3.1.6"

# --- POWER-ETHERNET-MIB, RFC 3621 ---------------------------------------------
PETH_DETECT_STATUS = {
    1: "disabled",
    2: "searching",
    3: "delivering",
    4: "fault",
    5: "test",
    6: "other_fault",
}
# MIKROTIK-MIB mtxrPOEStatus. Deliberately mapped onto the same vocabulary as
# RFC 3621, so a PoE status sensor means one thing regardless of vendor.
MTXR_POE_STATUS = {
    1: "disabled",
    2: "searching",
    3: "delivering",
    4: "fault",
    5: "fault",
    6: "fault",
}


@dataclass(frozen=True, slots=True)
class SerialSource:
    """Where a stable per-device identifier comes from.

    `entity_chassis` walks ENTITY-MIB and takes the row the device itself calls
    a chassis. Picking the lowest index instead looks right until a RouterBOARD
    answers `rb400_usb` or `xhci-hcd.1.auto` from an unrelated row - strings
    identical on every unit of that model, which would collide two devices onto
    one unique_id.
    """

    entity_chassis: bool = False
    scalar_oid: str | None = None
    # Values that are technically non-empty but are not serial numbers
    placeholders: frozenset[str] = frozenset(
        {"not avail", "not available", "none", "n/a", "unknown", "0"}
    )


@dataclass(frozen=True, slots=True)
class MetricSource:
    """A number that is either one scalar, or a column to be averaged."""

    oid: str
    table: bool = False


@dataclass(frozen=True, slots=True)
class MemorySource:
    """Two scalars, or one hrStorage row matched by description."""

    free_oid: str | None = None
    used_oid: str | None = None
    storage_match: str | None = None


@dataclass(frozen=True, slots=True)
class PoeSource:
    """Per-port PoE, and how its table is addressed.

    `index` is the difference that bites: AOS-S addresses the PoE tables by
    `<group>.<port>`, which the model file carries as `poe_index`, while
    RouterOS addresses them by ifIndex.
    """

    power_oid: str
    power_divisor: int
    index: str  # "poe_index" | "ifindex"
    status_oid: str | None = None
    status_map: dict[int, str] = field(default_factory=lambda: dict(PETH_DETECT_STATUS))
    main_power_oid: str | None = None
    main_consumption_oid: str | None = None


@dataclass(frozen=True, slots=True)
class WirelessSource:
    """CAPsMAN registrations, read from the controller.

    A managed access point answers almost nothing about its own radios - the
    controller holds the lot. Polling the controller therefore covers every AP
    in the estate, including the ones that are silent when asked directly.
    """

    registration_ssid_oid: str
    registration_signal_oid: str
    ap_ssid_oid: str | None = None
    ap_clients_oid: str | None = None
    ap_noise_oid: str | None = None
    ap_ccq_oid: str | None = None


@dataclass(frozen=True, slots=True)
class Profile:
    key: str
    name: str
    # sysObjectID starts with 1.3.6.1.4.1.<enterprise>
    enterprise: int
    serial: SerialSource
    cpu: MetricSource | None = None
    memory: MemorySource | None = None
    poe: PoeSource | None = None
    wireless: WirelessSource | None = None
    # Whether dot1qVlanStaticEgressPorts is populated. RouterOS fills dot1qPvid
    # and leaves the egress table empty - confirmed across eight devices on
    # 7.20 to 7.22, including two CRS switches, so this is the vendor rather
    # than a class of device. Without membership data there is no evidence for
    # access versus trunk.
    vlan_egress: bool = True
    # Whether ports can be discovered from ifType instead of a model file.
    discover_ports: bool = True


AOS_S = Profile(
    key="aos_s",
    name="ArubaOS-Switch",
    enterprise=11,
    serial=SerialSource(entity_chassis=True),
    cpu=MetricSource(oid="1.3.6.1.4.1.11.2.14.11.5.1.9.6.1.0"),
    memory=MemorySource(
        free_oid="1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.6.1",
        used_oid="1.3.6.1.4.1.11.2.14.11.5.1.1.2.1.1.1.7.1",
    ),
    poe=PoeSource(
        # HP-ICF-POE-MIB reports milliwatts. Confirmed against the switch's own
        # web UI, port for port, on six live loads.
        power_oid="1.3.6.1.4.1.11.2.14.11.1.9.1.1.1.8",
        power_divisor=1000,
        index="poe_index",
        status_oid="1.3.6.1.2.1.105.1.1.1.6",
        main_power_oid="1.3.6.1.2.1.105.1.3.1.1.2",
        main_consumption_oid="1.3.6.1.2.1.105.1.3.1.1.4",
    ),
    vlan_egress=True,
)

ROUTEROS = Profile(
    key="routeros",
    name="MikroTik RouterOS",
    enterprise=14988,
    # ENTITY-MIB on RouterOS puts USB controller names in the serial column and
    # leaves the chassis row empty, so the vendor scalar is the only usable one.
    serial=SerialSource(scalar_oid="1.3.6.1.4.1.14988.1.1.7.3.0"),
    cpu=MetricSource(oid=OID_HR_CPU, table=True),
    memory=MemorySource(storage_match="main memory"),
    poe=PoeSource(
        power_oid="1.3.6.1.4.1.14988.1.1.15.1.1.6",
        # Still unverified, and now known to be mostly moot. Across eight
        # RouterOS devices the only PoE-out port found under load - an RB2011
        # with `status=delivering` - reported voltage, current and power all
        # zero, because passive PoE-out has no measurement hardware. poll()
        # therefore reports unknown rather than 0 W, and this divisor only
        # matters on hardware that does measure, such as a CRS328-24P.
        power_divisor=1,
        index="ifindex",
        status_oid="1.3.6.1.4.1.14988.1.1.15.1.1.3",
        status_map=dict(MTXR_POE_STATUS),
    ),
    wireless=WirelessSource(
        registration_ssid_oid="1.3.6.1.4.1.14988.1.1.1.5.1.12",
        registration_signal_oid="1.3.6.1.4.1.14988.1.1.1.5.1.11",
        ap_ssid_oid="1.3.6.1.4.1.14988.1.1.1.3.1.4",
        ap_clients_oid="1.3.6.1.4.1.14988.1.1.1.3.1.6",
        ap_noise_oid="1.3.6.1.4.1.14988.1.1.1.3.1.9",
        ap_ccq_oid="1.3.6.1.4.1.14988.1.1.1.3.1.10",
    ),
    vlan_egress=False,
)

PROFILES: tuple[Profile, ...] = (AOS_S, ROUTEROS)

# Used when sysObjectID names an enterprise nobody has written a profile for.
# Standard MIBs only: link, speed, counters, descriptions, PVID. No PoE, no CPU,
# no serial - and saying so is better than reading the wrong OID and reporting a
# confident zero.
GENERIC = Profile(
    key="generic",
    name="Generic SNMP",
    enterprise=0,
    serial=SerialSource(entity_chassis=True),
    vlan_egress=True,
)


# pysnmp renders an OID through the MIBs it has loaded, so sysObjectID arrives as
# "SNMPv2-SMI::enterprises.11.2.3.7.11.182.21" rather than the dotted form. Both
# spellings mean the same thing and both have to be understood.
_RE_ENTERPRISE = re.compile(
    r"(?:^|::)(?:iso\.)?(?:1\.3\.6\.1\.4\.1|enterprises)\.(\d+)"
)


def enterprise_of(sys_object_id: str | None) -> int | None:
    """The enterprise number out of a sysObjectID, or None."""
    if not sys_object_id:
        return None
    match = _RE_ENTERPRISE.search(str(sys_object_id).strip())
    return int(match.group(1)) if match else None


def detect(sys_object_id: str | None) -> Profile:
    """Pick a profile from sysObjectID, falling back to standard MIBs only."""
    enterprise = enterprise_of(sys_object_id)
    for profile in PROFILES:
        if profile.enterprise == enterprise:
            return profile
    return GENERIC


def by_key(key: str | None) -> Profile:
    for profile in (*PROFILES, GENERIC):
        if profile.key == key:
            return profile
    return GENERIC
