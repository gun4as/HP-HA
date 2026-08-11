"""The model files and the generator that produces them.

A model is data, not code, which is the whole reason a new switch is supposed to
be a JSON file. That only holds if the data is actually consistent, so these
tests check the invariants the SNMP layer and the card silently rely on.
"""

from __future__ import annotations

import importlib.util
import json
import sys

import pytest

from conftest import ROOT, model

MODELS = sorted((ROOT / "custom_components" / "netviz" / "models").glob("*.json"))


def _gen_model():
    spec = importlib.util.spec_from_file_location(
        "netviz_gen_model", ROOT / "tools" / "gen_model.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_there_is_at_least_one_model():
    assert MODELS, "no model files, the config flow would offer an empty list"


@pytest.mark.parametrize("path", MODELS, ids=lambda p: p.stem)
def test_model_invariants(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    ports = data["ports"]
    assert ports, "a model with no ports is rejected at load time"

    ids = [p["id"] for p in ports]
    assert len(ids) == len(set(ids)), "duplicate port ids collide on unique_id"

    face = data["faceplate"]
    assert face["viewbox"] == f"0 0 {face['width']} {face['height']}"

    for port in ports:
        for key in ("id", "label", "kind", "ifname", "x", "y", "w", "h"):
            assert key in port, f"port {port.get('id')} is missing {key}"
        assert port["x"] + port["w"] <= face["width"], f"port {port['id']} overflows"
        assert port["y"] + port["h"] <= face["height"], f"port {port['id']} overflows"
        # poe_index is what the PoE tables are addressed by; a PoE port without
        # one would silently read nothing
        assert bool(port.get("poe")) == ("poe_index" in port)


@pytest.mark.parametrize("path", MODELS, ids=lambda p: p.stem)
def test_ports_do_not_overlap(path):
    """Overlapping rectangles mean the card draws one port on top of another."""
    data = json.loads(path.read_text(encoding="utf-8"))
    boxes = [(p["id"], p["x"], p["y"], p["w"], p["h"]) for p in data["ports"]]
    for i, (id_a, ax, ay, aw, ah) in enumerate(boxes):
        for id_b, bx, by, bw, bh in boxes[i + 1:]:
            overlap = ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
            assert not overlap, f"ports {id_a} and {id_b} overlap"


def test_jl357a_matches_its_generator_arguments():
    """The committed file must be what the documented command produces."""
    gen = _gen_model()
    built = gen.build(
        rj45=48, sfp=4, block=12, numbering="column", sfp_side="left",
        meta={
            "model": "JL357A",
            "vendor": "HPE Aruba Networking",
            "display": "Aruba 2540-48G-PoE+-4SFP+",
            "os": "ArubaOS-Switch 16.x",
            "poe_budget_w": 370,
        },
    )
    committed = json.loads(
        (ROOT / "custom_components/netviz/models/jl357a.json").read_text(encoding="utf-8")
    )
    assert built == committed


def test_sfp_cage_sits_left_of_port_one():
    """The JL357A has its SFP+ ports to the left, as does its own web UI."""
    data = model.load_model("jl357a")
    ports = {p["id"]: p for p in data["ports"]}
    assert data["faceplate"]["sfp_side"] == "left"
    assert max(ports[i]["x"] for i in ("49", "50", "51", "52")) < ports["1"]["x"]
    assert ports["48"]["x"] > ports["1"]["x"]


def test_column_numbering_puts_odd_on_top():
    ports = {p["id"]: p for p in model.load_model("jl357a")["ports"]}
    assert ports["1"]["row"] == 0 and ports["2"]["row"] == 1
    assert ports["1"]["x"] == ports["2"]["x"]
    assert ports["49"]["row"] == 0 and ports["50"]["row"] == 1


def test_faceplate_geometry_drops_the_snmp_fields():
    """The card gets geometry only; ifname and poe_index are not its business."""
    geometry = model.faceplate_geometry(model.load_model("jl357a"))
    assert len(geometry["ports"]) == 52
    for port in geometry["ports"]:
        assert set(port) == {"id", "label", "kind", "poe", "x", "y", "w", "h"}


def test_available_models_reads_display_names():
    models = model.available_models()
    assert models["jl357a"] == "Aruba 2540-48G-PoE+-4SFP+"


def test_unknown_model_raises():
    with pytest.raises(model.ModelNotFound):
        model.load_model("no-such-switch")


# ------------------------------------------- geometry for discovered hardware


def _discovered(count: int) -> list[dict]:
    return [{"id": f"ether{i}", "label": f"ether{i}", "poe": i == count} for i in range(1, count + 1)]


@pytest.mark.parametrize("count", [2, 5, 11, 24, 52])
def test_generated_geometry_holds_the_same_invariants_as_a_model(count):
    """Whatever the port count, the card must be able to draw it."""
    geometry = model.generated_geometry(_discovered(count), "Test device")
    ports = geometry["ports"]

    assert len(ports) == count
    assert geometry["viewbox"] == f"0 0 {geometry['width']} {geometry['height']}"
    assert geometry["generated"] is True

    for port in ports:
        assert set(port) == {"id", "label", "name", "kind", "poe", "x", "y", "w", "h"}
        assert port["x"] + port["w"] <= geometry["width"]
        # a label wider than its port is what turned the first attempt into mush
        assert len(port["label"]) * 4.8 <= port["w"]
        assert port["y"] + port["h"] <= geometry["height"]

    boxes = [(p["id"], p["x"], p["y"], p["w"], p["h"]) for p in ports]
    for i, (id_a, ax, ay, aw, ah) in enumerate(boxes):
        for id_b, bx, by, bw, bh in boxes[i + 1:]:
            overlap = ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah
            assert not overlap, f"{id_a} and {id_b} overlap at {count} ports"


def test_small_devices_get_one_row():
    """A two-port access point is not a faceplate with an empty second row."""
    two = model.generated_geometry(_discovered(2), "cAP")
    assert len({p["y"] for p in two["ports"]}) == 1

    eleven = model.generated_geometry(_discovered(11), "RB2011")
    assert len({p["y"] for p in eleven["ports"]}) == 2


def test_generated_geometry_keeps_the_poe_flag():
    geometry = model.generated_geometry(_discovered(5), "hAP")
    assert [p["poe"] for p in geometry["ports"]] == [False, False, False, False, True]


def test_long_interface_names_are_shortened_but_not_lost():
    """RouterOS names are whatever an admin typed: "ether1uplink dsl"."""
    ports = [
        {"id": "ether1uplink dsl", "label": "ether1uplink dsl"},
        {"id": "ether2 TV", "label": "ether2 TV"},
        {"id": "internet", "label": "internet"},
        {"id": "sfp1", "label": "sfp1"},
    ]
    geometry = model.generated_geometry(ports, "router")
    labels = [p["label"] for p in geometry["ports"]]
    assert labels == ["ether1", "ether2", "internet", "sfp1"]

    # the full name survives for the tooltip, and only where it differs
    names = [p["name"] for p in geometry["ports"]]
    assert names == ["ether1uplink dsl", "ether2 TV", None, None]

    # and the id, which entities key off, is untouched
    assert [p["id"] for p in geometry["ports"]] == [p["id"] for p in ports]


def test_ports_run_left_to_right_in_reported_order():
    """Column-major is a switch faceplate; a discovered list reads as a list."""
    ports = [{"id": f"ether{i}", "label": f"ether{i}"} for i in range(1, 12)]
    laid = model.generated_geometry(ports, "rb")["ports"]
    top = [p["label"] for p in laid if p["y"] == min(q["y"] for q in laid)]
    assert top == ["ether1", "ether2", "ether3", "ether4", "ether5", "ether6"]
    assert [p["x"] for p in laid[:6]] == sorted(p["x"] for p in laid[:6])
