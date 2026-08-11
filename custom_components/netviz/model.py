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
