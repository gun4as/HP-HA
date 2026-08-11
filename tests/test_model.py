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
