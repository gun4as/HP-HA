"""Vendor profiles, and the detection that picks one.

The point of a profile is that the differences between vendors are described in
one place instead of being spread through poll(). These tests check that the
description matches what the four probed devices actually answered.
"""

from __future__ import annotations

import pytest

from conftest import profiles


@pytest.mark.parametrize(
    ("sys_object_id", "expected"),
    [
        ("1.3.6.1.4.1.11.2.3.7.11.182.21", "aos_s"),          # the JL357A
        ("1.3.6.1.4.1.14988.1", "routeros"),                   # every MikroTik
        ("1.3.6.1.4.1.9.1.1745", "generic"),                   # Cisco, no profile
        # pysnmp renders OIDs through its MIBs, so this is the spelling that
        # actually arrives from a live device
        ("SNMPv2-SMI::enterprises.11.2.3.7.11.182.21", "aos_s"),
        ("SNMPv2-SMI::enterprises.14988.1", "routeros"),
        ("1.3.6.1.2.1.1", "generic"),                          # not an enterprise OID
        ("", "generic"),
        (None, "generic"),
    ],
)
def test_detection_from_sysobjectid(sys_object_id, expected):
    assert profiles.detect(sys_object_id).key == expected


def test_enterprise_parsing_ignores_rubbish():
    assert profiles.enterprise_of("1.3.6.1.4.1.14988.1.1.7") == 14988
    assert profiles.enterprise_of("1.3.6.1.4.1.x.1") is None
    assert profiles.enterprise_of("nonsense") is None


def test_the_two_vendors_differ_in_shape_not_only_in_oids():
    """If these ever converge, the profile abstraction is not earning its keep."""
    aos, ros = profiles.AOS_S, profiles.ROUTEROS

    # serial: a chosen ENTITY-MIB row versus a vendor scalar
    assert aos.serial.entity_chassis and not aos.serial.scalar_oid
    assert ros.serial.scalar_oid and not ros.serial.entity_chassis

    # cpu: one value versus a column to average
    assert not aos.cpu.table
    assert ros.cpu.table

    # memory: two scalars versus an hrStorage row
    assert aos.memory.free_oid and not aos.memory.storage_match
    assert ros.memory.storage_match and not ros.memory.free_oid

    # poe: addressed by the model's poe_index versus by ifIndex
    assert aos.poe.index == "poe_index"
    assert ros.poe.index == "ifindex"

    # vlan: full Q-BRIDGE versus PVID only
    assert aos.vlan_egress and not ros.vlan_egress


def test_generic_profile_promises_nothing_it_cannot_deliver():
    """An unknown vendor gets standard MIBs, not a guess at a private one."""
    generic = profiles.GENERIC
    assert generic.cpu is None
    assert generic.memory is None
    assert generic.poe is None
    assert generic.wireless is None


def test_poe_status_maps_share_one_vocabulary():
    """A PoE status sensor has to mean the same thing on either vendor."""
    aos_values = set(profiles.AOS_S.poe.status_map.values())
    ros_values = set(profiles.ROUTEROS.poe.status_map.values())
    assert ros_values <= aos_values
    assert "delivering" in aos_values and "delivering" in ros_values


def test_by_key_round_trips_and_falls_back():
    for profile in (*profiles.PROFILES, profiles.GENERIC):
        assert profiles.by_key(profile.key) is profile
    assert profiles.by_key("no-such-vendor") is profiles.GENERIC


def test_profiles_match_the_recorded_devices(aruba, rb2011, capsman):
    """Detection against the sysObjectID each device really returned."""
    for snapshot, expected in ((aruba, "aos_s"), (rb2011, "routeros"), (capsman, "routeros")):
        sys_object_id = snapshot.get(["1.3.6.1.2.1.1.2.0"]).get("1.3.6.1.2.1.1.2.0")
        assert sys_object_id, f"{snapshot.name} has no sysObjectID in its fixture"
        assert profiles.detect(sys_object_id).key == expected


def test_recorded_devices_answer_what_their_profile_claims(aruba, rb2011):
    """A profile that names an OID the device leaves empty is a lie."""
    aos = profiles.AOS_S
    assert aruba.get([aos.cpu.oid]), "AOS-S profile claims a CPU scalar that is empty"
    assert aruba.get([aos.memory.free_oid, aos.memory.used_oid])
    assert aruba.walk(aos.poe.power_oid), "no HP PoE table in the Aruba fixture"

    ros = profiles.ROUTEROS
    assert rb2011.get([ros.serial.scalar_oid]), "no mtxrSerialNumber in the fixture"
    assert rb2011.walk(ros.cpu.oid), "no hrProcessorLoad in the fixture"
    assert "main memory" in rb2011.walk(profiles.OID_HR_STORAGE_DESCR).values()

    # ...and the converse: each vendor's private OIDs are empty on the other
    assert not rb2011.get([aos.cpu.oid])
    assert not aruba.walk(ros.poe.power_oid)


def test_capsman_controller_holds_the_wireless_estate(capsman, rb2011):
    """Managed access points answer nothing; the controller answers for all."""
    wireless = profiles.ROUTEROS.wireless
    ssids = capsman.walk(wireless.registration_ssid_oid)
    signals = capsman.walk(wireless.registration_signal_oid)
    assert len(ssids) == len(signals) > 0
    assert len(set(ssids.values())) >= 2, "fixture should cover more than one SSID"
    assert all(-100 < int(v) < 0 for v in signals.values()), "signal is dBm, negative"

    # a device that is not a controller has an empty registration table
    assert rb2011.walk(wireless.registration_ssid_oid) == {}
