"""Model (faceplate) loading.

A model JSON lives in `models/<slug>.json` and holds both the port list with its
SNMP bindings and the SVG geometry. A new switch model is a new JSON file and no
code at all. Generator: tools/gen_model.py
"""

from __future__ import annotations

import json
import logging
import re
from functools import lru_cache
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"


class ModelNotFound(Exception):
    """The requested model is not bundled."""


def available_models() -> dict[str, str]:
    """{slug: human readable name}."""
    out: dict[str, str] = {}
    for path in sorted(MODELS_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _LOGGER.warning("broken model file: %s", path.name)
            continue
        out[path.stem] = data.get("display", path.stem)
    return out


@lru_cache(maxsize=16)
def load_model(slug: str) -> dict:
    path = MODELS_DIR / f"{slug}.json"
    if not path.is_file():
        raise ModelNotFound(slug)
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if not data.get("ports"):
        raise ModelNotFound(f"{slug}: no ports")
    return data


# Same units the generator uses, so a laid-out faceplate and a bundled one look
# like the same product rather than two different drawings.
_PORT_W, _PORT_H, _GAP_X, _GAP_Y = 22, 18, 4, 6
_BLOCK_GAP, _MARGIN_X, _MARGIN_Y, _BLOCK = 14, 26, 26, 12


# A port token at the start of an interface name: "ether2 TV" -> "ether2",
# "ether1uplink dsl" -> "ether1". Anything else gets truncated instead.
_RE_PORT_TOKEN = re.compile(r"^(sfp[a-z+-]*\d+|[a-z]+\d+)", re.IGNORECASE)
_LABEL_MAX = 10
# Roughly the advance width of one character at font-size 8 in viewBox units.
# The card draws labels at that size, and a label wider than its port turns a
# faceplate into overlapping mush.
_CHAR_W = 4.8


def short_label(name: str) -> str:
    """A label that fits on a port.

    Discovered ports are named by whoever configured the device, and on RouterOS
    that means things like "ether1uplink dsl". Drawn in full at port width they
    overlap into nonsense, so keep the port token and let the tooltip carry the
    rest.
    """
    text = str(name).strip()
    if match := _RE_PORT_TOKEN.match(text):
        return match.group(1)
    return text[:_LABEL_MAX]


_RE_TRAILING_NUMBER = re.compile(r"(\d+)\D*$")


def label_number(name: str) -> str | None:
    """The port number out of an interface name, if it has one.

    A front panel prints `SFP+ 1` and `ETH10`, not `sfp-sfpplus1` and `ether10`,
    so when a name will not fit its slot the number is what the hardware itself
    would have written there.
    """
    match = _RE_TRAILING_NUMBER.search(str(name).strip())
    return match.group(1) if match else None


def fits(text: str, width: int) -> bool:
    """Whether a label drawn at the card's font size stays inside its slot."""
    return len(text) * _CHAR_W <= width - 4


def generated_geometry(ports: list[dict], display: str) -> dict:
    """Lay discovered ports out when no model file describes the hardware.

    This is a drawing of a port list, not of a chassis: ports run left to right
    in the order the device reported them, wrapping to a second row past six. It
    cannot know where an SFP cage physically sits or how a front panel is
    numbered - that is what a model file is for - but it beats no faceplate at
    all on hardware nobody has drawn yet.

    Port widths follow their labels rather than a fixed 22 units, because a
    generated faceplate is a list of named ports and the names have to be
    readable for it to be worth drawing.
    """
    if not ports:
        return {
            "model": None, "display": display, "width": 0, "height": 0,
            "viewbox": "0 0 0 0", "generated": True, "ports": [],
        }

    rows = 2 if len(ports) > 6 else 1
    per_row = -(-len(ports) // rows)  # ceiling division
    labels = [short_label(p.get("label", p["id"])) for p in ports]
    widths = [max(_PORT_W, round(len(label) * _CHAR_W) + 10) for label in labels]

    laid_out = []
    row_width = [_MARGIN_X] * rows
    for position, port in enumerate(ports):
        row = position // per_row
        x = row_width[row]
        full = str(port.get("label", port["id"]))
        laid_out.append({
            "id": str(port["id"]),
            "label": labels[position],
            # the full interface name, for the tooltip - shortening the label is
            # a drawing decision and must not lose what the operator called it
            "name": full if full != labels[position] else None,
            "kind": port.get("kind", "rj45"),
            "poe": bool(port.get("poe")),
            "x": x,
            "y": _MARGIN_Y + row * (_PORT_H + _GAP_Y),
            "w": widths[position],
            "h": _PORT_H,
        })
        row_width[row] = x + widths[position] + _GAP_X

    width = max(row_width) - _GAP_X + _MARGIN_X
    height = _MARGIN_Y * 2 + _PORT_H * rows + _GAP_Y * (rows - 1)
    return {
        "model": None,
        "display": display,
        "width": width,
        "height": height,
        "viewbox": f"0 0 {width} {height}",
        "generated": True,
        "ports": laid_out,
    }


_RADIO_W, _RADIO_H = 34, 18


def radio_slots(radios: dict, x: int, y: int) -> list[dict]:
    """Blocks for the radios a device serves itself, placed after the ports.

    A radio is not a socket on a front panel, but the card is a summary of what
    the device is doing rather than a photograph, and on an access point the
    radios are the interesting half. Only locally served radios get a block -
    a controller reports a radio for every managed AP, and those belong to the
    other device's faceplate, not to this one.
    """
    slots = []
    for offset, (ifindex, radio) in enumerate(
        sorted(
            ((i, r) for i, r in radios.items() if "ssid" in r),
            key=lambda kv: (kv[1].get("frequency") or 0, int(kv[0])),
        )
    ):
        slots.append({
            "id": f"radio-{ifindex}",
            "label": radio.get("band") or short_label(radio.get("name", "")),
            "kind": "radio",
            "x": x + offset * (_RADIO_W + _GAP_X),
            "y": y,
            "w": _RADIO_W,
            "h": _RADIO_H,
        })
    return slots


def with_radios(geometry: dict, radios: dict) -> dict:
    """Widen a faceplate to make room for its radios."""
    if not geometry.get("ports") or not radios:
        return geometry
    ports = geometry["ports"]
    x = max(p["x"] + p["w"] for p in ports) + _BLOCK_GAP
    y = min(p["y"] for p in ports)
    slots = radio_slots(radios, x, y)
    if not slots:
        return geometry
    width = max(s["x"] + s["w"] for s in slots) + _MARGIN_X
    return {
        **geometry,
        "width": width,
        "viewbox": f"0 0 {width} {geometry['height']}",
        "radios": slots,
    }


def is_template(model: dict) -> bool:
    """A template carries geometry only; its ports come from the device."""
    return bool(model) and model.get("match") == "order"


def template_geometry(model: dict, ports: list[dict]) -> dict | None:
    """Pair a template's slots with discovered ports, or None if they disagree.

    A slot says what shape sits where and which discovered port belongs in it,
    by position in the device's own ifIndex order. Identity, PoE and the label
    come from the port, never from the template - on RouterOS an interface is
    named whatever the operator typed, and a template keyed on `ether1` would
    break the moment somebody renamed it.

    Returning None rather than half a drawing is deliberate: a template picked
    for the wrong hardware should fall back to the automatic layout, not draw a
    faceplate with holes in it.
    """
    slots = model.get("ports") or []
    if len(slots) != len(ports):
        _LOGGER.warning(
            "template %s describes %d ports but the device has %d; "
            "falling back to the automatic layout",
            model.get("display") or model.get("model"),
            len(slots),
            len(ports),
        )
        return None

    for slot in slots:
        index = slot.get("index")
        if not isinstance(index, int) or not 0 <= index < len(ports):
            _LOGGER.warning(
                "template %s has a slot pointing at port %r, which does not exist",
                model.get("display") or model.get("model"),
                index,
            )
            return None

    # A slot is a fixed physical size, so unlike the automatic layout the label
    # cannot widen to fit - it has to shrink. Decided once for the whole
    # faceplate rather than per slot, because a row reading "1 2 3 sfp9 sfp10"
    # looks like a mistake even when every label technically fits.
    names = [str(ports[slot["index"]].get("label", ports[slot["index"]]["id"]))
             for slot in slots]
    use_numbers = any(
        not fits(short_label(name), slot["w"])
        for name, slot in zip(names, slots)
    )

    numbers = [label_number(name) for name in names]
    # A number alone is ambiguous where a panel mixes cages: a CRS309 has both an
    # SFP+ 1 and an ether1, and the hardware tells them apart by the SFP+ and
    # POE/BOOT markings rather than by the digit. Prefix with the kind only when
    # the digits would actually collide.
    prefix_kind = use_numbers and len(set(numbers)) < len(numbers)

    laid_out = []
    for slot, name, number in zip(slots, names, numbers):
        port = ports[slot["index"]]
        label = short_label(name)
        if use_numbers and number:
            initial = "S" if slot.get("kind") == "sfp+" else "E"
            label = f"{initial}{number}" if prefix_kind else number
        if not fits(label, slot["w"]):
            label = label[: max(1, int((slot["w"] - 4) // _CHAR_W))]
        laid_out.append({
            "id": str(port["id"]),
            "label": label,
            "name": name if name != label else None,
            "kind": slot.get("kind", "rj45"),
            "poe": bool(port.get("poe")),
            "x": slot["x"],
            "y": slot["y"],
            "w": slot["w"],
            "h": slot["h"],
        })

    faceplate = model.get("faceplate", {})
    return {
        "model": model.get("model"),
        "display": model.get("display"),
        "width": faceplate.get("width"),
        "height": faceplate.get("height"),
        "viewbox": faceplate.get("viewbox"),
        "ports": laid_out,
    }


def faceplate_geometry(model: dict) -> dict:
    """Compact geometry for the card - without the SNMP fields."""
    return {
        "model": model.get("model"),
        "display": model.get("display"),
        "width": model.get("faceplate", {}).get("width"),
        "height": model.get("faceplate", {}).get("height"),
        "viewbox": model.get("faceplate", {}).get("viewbox"),
        "ports": [
            {
                "id": p["id"],
                "label": p.get("label", p["id"]),
                "kind": p.get("kind", "rj45"),
                "poe": bool(p.get("poe")),
                "x": p.get("x"),
                "y": p.get("y"),
                "w": p.get("w"),
                "h": p.get("h"),
            }
            for p in model["ports"]
        ],
    }
