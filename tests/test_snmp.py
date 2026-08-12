"""The SNMP layer, against snapshots of two real devices.

Every expectation here was checked against the hardware first - the PoE figures
against the switch's own web UI, the VLAN decoding against its VLAN table - so a
failure means the code drifted, not that the fixture is a guess.
"""

from __future__ import annotations

import logging

import pytest

from conftest import FixtureClient, snmp

# --------------------------------------------------------------- pure functions


def test_portlist_decodes_the_bitmap_msb_first():
    # bit 0 of byte 0 is port 1, so 0b10000001 is ports 1 and 8
    assert snmp._portlist(bytes([0b10000001])) == {1, 8}
    assert snmp._portlist(bytes([0x00, 0b01000000])) == {10}
    assert snmp._portlist(b"") == set()


def test_as_int_falls_back_instead_of_raising():
    assert snmp._as_int("42") == 42
    assert snmp._as_int(None) is None
    assert snmp._as_int("no such object", default=-1) == -1


@pytest.mark.parametrize(
    ("descr", "expected"),
    [
        # the real thing: the ROM field and the build path come after the one we want
        (
            "Aruba JL357A 2540-48G-PoE+-4SFP+ Switch, revision YC.16.11.0029, "
            "ROM YC.16.01.0003 (/ws/swbuildm/rel_beluru/code/build/cpm(x))",
            "YC.16.11.0029",
        ),
        ("RouterOS RB2011UiAS-2HnD", None),
        ("Some Switch v3.14.15 build 9", "v3.14.15"),  # vendor prefix kept as written
        ("", None),
        (None, None),
    ],
)
def test_sw_version_comes_from_the_revision_field(descr, expected):
    assert snmp.sw_version_from_descr(descr) == expected


# ------------------------------------------------------------------ serial number


async def test_serial_prefers_the_chassis_over_a_module(aruba):
    """The chassis is index 1001 and a transceiver is 27052; lowest index wins."""
    client = FixtureClient(aruba)
    assert await client._serial() == "TESTSERIAL1"


async def test_serial_strips_and_skips_placeholders(aruba):
    table = aruba.walk(snmp.OID_ENT_SERIAL_TABLE)
    assert "Not Avail" in table.values(), "fixture lost its placeholder row"
    assert any(v != v.strip() for v in table.values()), "fixture lost its padded row"
    assert await FixtureClient(aruba)._serial() == "TESTSERIAL1"


async def test_serial_rejects_a_component_name(rb2011):
    """RB2011 answers entPhysicalSerialNum with 'rb400_usb'.

    That is a component name, identical on every RB2011 ever made. Accepting it
    would give two different devices the same unique_id, and the second one
    could never be added.
    """
    table = rb2011.walk(snmp.OID_ENT_SERIAL_TABLE)
    assert [v for v in table.values() if v.strip()] == ["rb400_usb"]
    assert await FixtureClient(rb2011)._serial() is None


# -------------------------------------------------------------------------- poll


async def test_every_model_port_matches(aruba):
    ports = _aruba_ports()
    data = await FixtureClient(aruba).poll(ports)
    assert len(data["ports"]) == 52
    assert data["system"]["ports_total"] == 52


async def test_ports_up_matches_ifoperstatus(aruba):
    oper = aruba.walk(snmp.OID_IF_OPER)
    names = aruba.walk(snmp.OID_IF_NAME)
    expected = sum(
        1 for idx, state in oper.items()
        if state == "1" and names.get(idx, "").strip().isdigit()
        and 1 <= int(names[idx]) <= 52
    )
    data = await FixtureClient(aruba).poll(_aruba_ports())
    assert data["system"]["ports_up"] == expected


async def test_poe_power_is_milliwatts_divided_by_a_thousand(aruba):
    """The HP MIB reports mW. Getting this wrong is a factor of 1000."""
    milliwatts = aruba.walk(snmp.OID_HP_POE_MW)
    data = await FixtureClient(aruba).poll(_aruba_ports())

    live = {p: int(v) for p, v in milliwatts.items() if int(v) > 0}
    assert live, "fixture has no PoE load, this test would prove nothing"

    for poe_index, mw in live.items():
        port_id = poe_index.split(".")[1]
        assert data["ports"][port_id]["poe_power"] == round(mw / 1000, 1)
        assert data["ports"][port_id]["poe_status"] == "delivering"

    drawing = {p for p, v in data["ports"].items() if (v.get("poe_power") or 0) > 0}
    assert drawing == {i.split(".")[1] for i in live}


async def test_alias_has_no_leading_space(aruba):
    """AOS-S returns ifAlias exactly as configured, spaces and all."""
    raw = aruba.walk(snmp.OID_IF_ALIAS)
    assert any(v.startswith(" ") for v in raw.values()), "fixture lost the quirk"

    data = await FixtureClient(aruba).poll(_aruba_ports())
    aliases = [p["alias"] for p in data["ports"].values() if p["alias"]]
    assert aliases, "no port descriptions in the fixture"
    assert all(a == a.strip() for a in aliases)


async def test_vlan_membership_and_mode(aruba):
    """Checked against the switch's own VLAN table, all sixteen columns."""
    data = await FixtureClient(aruba).poll(_aruba_ports())
    port1 = data["ports"]["1"]
    assert port1["pvid"] == 20
    assert port1["vlans"] == [20, 50]
    assert port1["mode"] == "trunk"       # untagged in 20, tagged in 50

    port15 = data["ports"]["15"]
    assert port15["vlans"] == [30]
    assert port15["mode"] == "access"

    port47 = data["ports"]["47"]
    assert port47["pvid"] == 1            # PVID pointing at a VLAN it is not in
    assert port47["vlans"] == [100]
    assert port47["mode"] == "trunk"


async def test_vlans_can_be_skipped(aruba):
    data = await FixtureClient(aruba).poll(_aruba_ports(), with_vlans=False)
    assert all("pvid" not in p for p in data["ports"].values())


async def test_rates_need_two_samples(aruba):
    client = FixtureClient(aruba)
    first = await client.poll(_aruba_ports())
    assert all(p["rx_bps"] is None for p in first["ports"].values())

    client.advance(aruba.gap)
    second = await client.poll(_aruba_ports())

    t0 = aruba.walk(snmp.OID_IF_HCIN)
    t1 = aruba.walk(snmp.OID_IF_HCIN, second=True)
    moved = [k for k in t0 if k in t1 and int(t1[k]) > int(t0[k])]
    assert moved, "counters did not move in the fixture"

    checked = 0
    for port in second["ports"].values():
        key = str(port["ifindex"])
        if key not in moved:
            continue
        expected = (int(t1[key]) - int(t0[key])) * 8 / aruba.gap
        assert port["rx_bps"] == pytest.approx(expected, rel=1e-3)
        checked += 1
    assert checked, "no model port had a moving counter"


async def test_counter_going_backwards_yields_no_rate(aruba):
    """A reboot or a wrap must not produce a negative or absurd rate."""
    client = FixtureClient(aruba)
    await client.poll(_aruba_ports())
    for ifindex in list(client._prev.counters):
        rx, tx = client._prev.counters[ifindex]
        client._prev.counters[ifindex] = (rx + 10**12, tx + 10**12)
    client.advance(aruba.gap)
    data = await client.poll(_aruba_ports())
    assert all(p["rx_bps"] is None for p in data["ports"].values())


async def test_unmatched_ports_are_reported(aruba, caplog):
    """Silently losing every port is the worst failure mode this thing has."""
    ports = _aruba_ports() + [{"id": "99", "ifname": "does-not-exist"}]
    with caplog.at_level(logging.WARNING):
        data = await FixtureClient(aruba).poll(ports)
    assert "99" not in data["ports"]
    assert "did not match" in caplog.text
    assert "'99'" in caplog.text


async def test_system_values(aruba):
    data = await FixtureClient(aruba).poll(_aruba_ports())
    system = data["system"]
    assert system["poe_budget"] == 370
    assert system["poe_used"] > 0
    assert system["cpu"] is not None
    assert system["uptime"] > 0        # sysUpTime is centiseconds, we store seconds


# ------------------------------------------------------- the other vendor's shape


async def test_routeros_ports_are_found_by_iftype(rb2011):
    ports = rb2011.physical_ports()
    assert len(ports) == 11
    data = await FixtureClient(rb2011).poll(ports)
    assert len(data["ports"]) == 11


async def test_routeros_reports_no_vlan_mode_without_egress(rb2011):
    """RouterOS fills dot1qPvid but leaves dot1qVlanStaticEgressPorts empty.

    With no egress data there is no evidence for access versus trunk, and a
    trunk port carrying every VLAN would be labelled `access` - a wrong answer
    dressed as a real one. Report the PVID, say nothing about the mode.
    """
    assert rb2011.walk(snmp.OID_VLAN_EGRESS) == {}
    assert rb2011.walk(snmp.OID_DOT1Q_PVID), "fixture lost its PVID table"

    data = await FixtureClient(rb2011).poll(rb2011.physical_ports())
    with_pvid = [p for p in data["ports"].values() if p.get("pvid") is not None]
    assert with_pvid, "no port picked up a PVID"
    assert all("mode" not in p for p in data["ports"].values())
    assert all(p.get("vlans", []) == [] for p in data["ports"].values())


def _aruba_ports() -> list[dict]:
    """The JL357A model, as the integration loads it."""
    from conftest import model

    return [dict(p) for p in model.load_model("jl357a")["ports"]]


# ------------------------------------------------------ profile-driven polling


async def test_profile_is_detected_on_the_first_poll(aruba, rb2011):
    """The coordinator polls straight after a restart, without probing first.

    If detection only happened in probe(), every device would sit on the generic
    profile - no PoE, no CPU - until something happened to call it.
    """
    for snapshot, expected in ((aruba, "aos_s"), (rb2011, "routeros")):
        client = FixtureClient(snapshot)
        assert client.profile.key == "generic"
        data = await client.poll(snapshot.physical_ports())
        assert client.profile.key == expected
        assert data["system"]["profile"] == expected


async def test_routeros_cpu_is_averaged_over_the_cores(capsman):
    """hrProcessorLoad is one row per core; a sensor shows one number."""
    from conftest import profiles

    loads = [int(v) for v in capsman.walk(profiles.OID_HR_CPU).values()]
    assert len(loads) > 1, "fixture should have a multi-core device"

    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    assert data["system"]["cpu"] == round(sum(loads) / len(loads))


async def test_routeros_memory_comes_from_hrstorage(rb2011):
    """Two vendor scalars on AOS-S, one hrStorage row in allocation units here."""
    from conftest import profiles

    descrs = rb2011.walk(profiles.OID_HR_STORAGE_DESCR)
    index = next(i for i, v in descrs.items() if v == "main memory")
    unit = int(rb2011.walk(profiles.OID_HR_STORAGE_UNITS)[index])
    size = int(rb2011.walk(profiles.OID_HR_STORAGE_SIZE)[index])
    used = int(rb2011.walk(profiles.OID_HR_STORAGE_USED)[index])

    system = (await FixtureClient(rb2011).poll(rb2011.physical_ports()))["system"]
    assert system["mem_used"] == used * unit
    assert system["mem_free"] == (size - used) * unit
    assert unit > 1, "allocation units matter; a fixture with unit 1 proves nothing"


async def test_ports_are_discovered_without_a_model_file(rb2011, capsman):
    """ifType 6 is ethernetCsmacd everywhere; ifName is whatever an admin typed."""
    for snapshot, expected in ((rb2011, 11), (capsman, 5)):
        client = FixtureClient(snapshot)
        await client._ensure_profile()
        ports = await client.discover_ports()
        assert len(ports) == expected
        # radios, bridges and VLAN interfaces must not be mistaken for ports
        names = {p["id"] for p in ports}
        assert not any(n.startswith(("wlan", "bridge", "vlan", "lo")) for n in names)


async def test_discovery_marks_poe_ports_by_ifindex(rb2011):
    """RouterOS addresses its PoE table by ifIndex, not by port number."""
    from conftest import profiles

    poe_table = rb2011.walk(profiles.ROUTEROS.poe.power_oid)
    assert len(poe_table) == 1, "an RB2011 has exactly one PoE-out port"

    client = FixtureClient(rb2011)
    await client._ensure_profile()
    ports = await client.discover_ports()
    with_poe = [p for p in ports if p["poe"]]
    assert len(with_poe) == 1
    assert str(with_poe[0]["ifindex"]) in poe_table


async def test_polling_discovered_routeros_ports(rb2011):
    client = FixtureClient(rb2011)
    await client._ensure_profile()
    data = await client.poll(await client.discover_ports())

    assert len(data["ports"]) == 11
    assert data["system"]["ports_up"] > 0
    # PoE exists as a concept on this device, so the one PoE port reports a status
    poe_ports = [p for p in data["ports"].values() if "poe_status" in p]
    assert len(poe_ports) == 1
    # ...but the HP-only system counters must not be invented
    assert data["system"]["poe_budget"] is None


async def test_generic_profile_reads_no_private_oids(aruba):
    """An unrecognised vendor gets standard MIBs and honest gaps."""
    from conftest import profiles

    client = FixtureClient(aruba)
    client.profile = profiles.GENERIC
    client._detected = True

    data = await client.poll(_aruba_ports())
    assert len(data["ports"]) == 52          # IF-MIB still works
    assert data["system"]["cpu"] is None
    assert data["system"]["poe_budget"] is None
    assert all("poe_power" not in p for p in data["ports"].values())
    assert not any("14988" in oid or "2.14.11" in oid for oid in client.walked)


# ------------------------------------------------------------------- wireless


async def test_capsman_aggregates_clients_by_ssid_and_by_radio(capsman):
    from conftest import profiles

    registrations = capsman.walk(profiles.ROUTEROS.wireless.registration_ssid_oid)
    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    wireless = data["wireless"]

    assert wireless["clients"] == len(registrations)
    assert data["system"]["wireless_clients"] == len(registrations)

    # every client is counted once per view, and only once. The radios this
    # controller manages for itself contribute None rather than 0 - see
    # test_a_managed_radio_reports_unknown_rather_than_zero.
    assert sum(v["clients"] for v in wireless["ssids"].values()) == len(registrations)
    assert sum(
        v["clients"] or 0 for v in wireless["radios"].values()
    ) == len(registrations)
    assert len(wireless["ssids"]) >= 2


async def test_signal_statistics_are_consistent(capsman):
    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    buckets = [
        *data["wireless"]["ssids"].values(),
        *data["wireless"]["radios"].values(),
    ]
    # A radio the device serves itself has no per-client registrations, so it has
    # no signal statistics either - None is the correct answer there.
    measured = [b for b in buckets if b["signal_avg"] is not None]
    assert measured, "nothing in the fixture had a client to measure"
    for bucket in measured:
        assert bucket["signal_min"] <= bucket["signal_avg"] <= bucket["signal_max"]
        assert -100 < bucket["signal_min"] and bucket["signal_max"] < 0


async def test_radios_are_named_from_their_interface(capsman):
    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    names = capsman.walk(snmp.OID_IF_NAME)
    for ifindex, radio in data["wireless"]["radios"].items():
        assert radio["name"] == names[ifindex].strip()


async def test_wireless_never_exposes_a_client(capsman):
    """Aggregates only.

    The registration table is keyed by client MAC address. Turning those into
    entities would be tracking everyone in the building, Home Assistant has an
    integration for that already, and this is not it.
    """
    import json
    import re

    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    blob = json.dumps(data["wireless"])
    assert not re.search(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", blob)
    # the fixture's re-keyed MACs are six dotted octets; none may survive either
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){5}\b", blob)

    counted = sum(v["clients"] for v in data["wireless"]["ssids"].values())
    assert counted > 10, "the fixture has plenty of clients, and none are listed"


async def test_devices_that_are_not_controllers_report_no_wireless(rb2011, aruba):
    for snapshot in (rb2011, aruba):
        data = await FixtureClient(snapshot).poll(snapshot.physical_ports())
        assert data["wireless"] == {}
        assert data["system"]["wireless_clients"] is None


# --------------------------------------------------- a RouterOS switch, not a router


async def test_a_routeros_switch_also_leaves_qbridge_empty(crs309):
    """The profile claims this of the vendor, not of routers and access points.

    A CRS309 is a switch with bridge VLAN filtering, and the obvious objection to
    `vlan_egress=False` was that it had only been checked on routers and APs.
    It leaves the egress table empty too.
    """
    assert crs309.walk(snmp.OID_VLAN_EGRESS) == {}
    assert crs309.walk(snmp.OID_DOT1Q_PVID), "fixture lost its PVID table"

    data = await FixtureClient(crs309).poll(crs309.physical_ports())
    assert all("mode" not in p for p in data["ports"].values())
    assert any(p.get("pvid") is not None for p in data["ports"].values())


async def test_sfp_ports_are_discovered_like_any_other(crs309):
    """SFP+ cages report ifType 6 as well, so nothing special is needed."""
    ports = crs309.physical_ports()
    assert len(ports) == 9
    names = [p["id"] for p in ports]
    assert sum(1 for n in names if n.startswith("sfp")) == 8

    data = await FixtureClient(crs309).poll(ports)
    assert len(data["ports"]) == 9
    # no PoE table and no radios on this box, and nothing may be invented
    assert all("poe_power" not in p for p in data["ports"].values())
    assert data["wireless"] == {}


async def test_cpu_averaging_works_at_two_cores_as_well(crs309):
    from conftest import profiles

    loads = [int(v) for v in crs309.walk(profiles.OID_HR_CPU).values()]
    assert len(loads) == 2
    data = await FixtureClient(crs309).poll(crs309.physical_ports())
    assert data["system"]["cpu"] == round(sum(loads) / len(loads))


async def test_delivering_with_zero_power_reports_unknown(rb2011):
    """Passive PoE-out has no measurement hardware.

    An RB2011 says `delivering` while voltage, current and power all read zero.
    0 W on a port that is powering something is a false measurement; unknown is
    the true answer.
    """
    from conftest import profiles

    client = FixtureClient(rb2011)
    await client._ensure_profile()
    poe = profiles.ROUTEROS.poe
    # force the fixture's one PoE port into the delivering-but-unmeasured state
    ports = await client.discover_ports()
    poe_port = next(p for p in ports if p["poe"])
    key = str(poe_port["ifindex"])
    rb2011.data["walks"][poe.power_oid][key] = "0"
    rb2011.data["walks"][poe.status_oid][key] = "3"

    data = await client.poll(ports)
    result = data["ports"][poe_port["id"]]
    assert result["poe_status"] == "delivering"
    assert result["poe_power"] is None


async def test_locally_served_radios_are_included(capsman):
    """A controller serves a couple of radios itself, and mtxrWlAp reports them.

    Those four columns were declared in the profile and never read - this is the
    fixture that proves they carry SSID, noise floor and transmit quality.
    """
    from conftest import profiles

    wireless = profiles.ROUTEROS.wireless
    ap_ssids = capsman.walk(wireless.ap_ssid_oid)
    assert ap_ssids, "fixture has no locally served radio"

    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    radios = data["wireless"]["radios"]

    for index in ap_ssids:
        ifindex = index.split(".")[0]
        radio = radios[ifindex]
        assert radio["ssid"], f"radio {ifindex} has no SSID"
        assert -120 < radio["noise_floor"] < 0, "noise floor is dBm, negative"
        assert 0 <= radio["quality"] <= 100, "CCQ is a percentage"

    # radios attributed from the controller's registrations carry no such fields
    from_registrations = [r for r in radios.values() if "ssid" not in r]
    assert from_registrations, "fixture should have both kinds of radio"


async def test_a_controller_counts_registrations_over_the_radio_tally(capsman):
    """Both sources report clients; the per-client one is exact."""
    data = await FixtureClient(capsman).poll(capsman.physical_ports())
    total = sum(
        r["clients"] for r in data["wireless"]["radios"].values() if "ssid" not in r
    )
    assert total == data["wireless"]["clients"]


# ----------------------------------------------- a standalone AP, no controller


async def test_standalone_ap_counts_its_own_clients(rb951):
    """A radio in AP mode with no controller keeps its clients in mtxrWlRtab.

    That table has no SSID column, so the SSID has to be attributed from
    mtxrWlAp for the same interface. Reading only the CAPsMAN table - which is
    what the first attempt did - meant such a device reported no wireless at all.
    """
    from conftest import profiles

    wireless = profiles.ROUTEROS.wireless
    assert rb951.walk(wireless.registration_ssid_oid) == {}, "not a controller"
    local = rb951.walk(wireless.local_signal_oid)
    assert local, "fixture lost its connected client"

    data = await FixtureClient(rb951).poll(rb951.physical_ports())
    result = data["wireless"]
    assert result["clients"] == len(local)
    assert data["system"]["wireless_clients"] == len(local)

    ssid, bucket = next(iter(result["ssids"].items()))
    assert ssid != "(unknown)", "SSID was not attributed from mtxrWlAp"
    assert bucket["clients"] == len(local)
    assert -100 < bucket["signal_avg"] < 0

    radio = next(r for r in result["radios"].values() if r["clients"])
    assert radio["ssid"] == ssid
    assert radio["signal_avg"] == bucket["signal_avg"]
    assert -120 < radio["noise_floor"] < 0
    assert 0 <= radio["quality"] <= 100


async def test_a_local_client_never_reaches_the_output_either(rb951):
    """The local registration table is MAC-keyed too."""
    import json
    import re

    data = await FixtureClient(rb951).poll(rb951.physical_ports())
    blob = json.dumps(data["wireless"])
    assert not re.search(r"(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}", blob)
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){5}\b", blob)


async def test_a_radio_in_ap_mode_appears_even_with_no_clients(capsman):
    """mtxrWlAp is about configuration, not about traffic.

    An earlier comment claimed the table only fills for a radio that is up. It
    fills for one configured in AP mode; a radio in station mode has no row.
    """
    radios = (await FixtureClient(capsman).poll(capsman.physical_ports()))["wireless"]["radios"]
    configured = [r for r in radios.values() if "ssid" in r and not r["clients"]]
    assert configured, "fixture should have a configured radio with nothing attached"
    for radio in configured:
        assert radio["ssid"]
        assert radio["noise_floor"] is not None


async def test_a_managed_radio_reports_unknown_rather_than_zero(capsman):
    """A radio a controller provisions cannot count its own clients.

    This controller runs CAPsMAN for its own radios too, so mtxrWlAp describes
    the local configuration nobody is served by - default SSID, zero clients -
    while the clients sit on the controller's own dynamic interfaces. Reporting
    that zero would paint an idle radio that is in fact carrying two dozen
    clients, the same mistake as reporting 0 W for an unmetered PoE port.
    """
    radios = (await FixtureClient(capsman).poll(capsman.physical_ports()))["wireless"]["radios"]
    local = [r for r in radios.values() if "ssid" in r]
    assert local, "fixture should expose local radio configuration"
    for radio in local:
        assert radio["managed"] is True
        assert radio["clients"] is None, "a managed radio must not claim zero"


async def test_a_provisioned_access_point_admits_it_cannot_count(capac):
    """The device this behaviour was built for.

    Six radios up against two mtxrWlAp rows: four of them were created by the
    controller, which is where the clients are counted. Before this, the card
    drew two idle green radios on an access point serving eighteen clients.
    """
    data = await FixtureClient(capac).poll(capac.physical_ports())
    radios = data["wireless"]["radios"]
    assert len(radios) == 2, "only the locally configured radios have rows"
    for radio in radios.values():
        assert radio["managed"] is True
        assert radio["clients"] is None
        assert radio["up"] is True, "the radio is transmitting, just not for us"
    # and the device total must not pretend to a number either
    assert data["wireless"]["clients"] == 0
    assert data["system"]["wireless_clients"] == 0


async def test_a_standalone_radio_still_counts_its_own_clients(rb951):
    """The heuristic must not fire where no controller is involved.

    One radio interface up and one row in mtxrWlAp means the device serves that
    radio itself, so its own numbers are the only ones there are.
    """
    radios = (await FixtureClient(rb951).poll(rb951.physical_ports()))["wireless"]["radios"]
    local = [r for r in radios.values() if "ssid" in r]
    assert local, "fixture should expose local radio configuration"
    for radio in local:
        assert radio["managed"] is False
        assert isinstance(radio["clients"], int)
    assert any(r["clients"] > 0 for r in local), "fixture lost its connected client"


async def test_discovery_detects_poe_without_a_prior_probe(rb2011):
    """The coordinator discovers ports before anything has probed the device.

    Detection used to happen only in poll(), so discovery ran on the generic
    profile, profile.poe was None, and not a single port was ever marked as PoE.
    No PoE entities and no orange dots on any device added by discovery - which
    is every MikroTik.
    """
    client = FixtureClient(rb2011)
    assert client.profile.key == "generic", "fixture would not exercise the bug"

    ports = await client.discover_ports()          # no _ensure_profile() first
    assert client.profile.key == "routeros"
    assert sum(1 for p in ports if p["poe"]) == 1

    data = await client.poll(ports)
    poe_port = next(p for p in data["ports"].values() if "poe_status" in p)
    assert poe_port["poe_status"] in ("searching", "delivering", "disabled")
