"""Model (faceplate) loading.

A model JSON lives in `models/<slug>.json` and holds both the port list with its
SNMP bindings and the SVG geometry. A new switch model is a new JSON file and no
code at all. Generator: tools/gen_model.py
"""

from __future__ import annotations

import json
import logging
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


def generated_geometry(ports: list[dict], display: str) -> dict:
    """Lay discovered ports out when no model file describes the hardware.

    This is a drawing of a port list, not of a chassis: the ports are in the
    order the device reported them, two rows for anything longer than six. It
    cannot know where the SFP cage physically sits or how the front panel is
    numbered - that is what a model file is for - but it beats no faceplate at
    all on a device nobody has drawn yet.
    """
    rows = 2 if len(ports) > 6 else 1
    columns = -(-len(ports) // rows)  # ceiling division
    laid_out = []
    x = _MARGIN_X
    column_x = []
    for column in range(columns):
        if column and rows == 2 and column % (_BLOCK // 2) == 0:
            x += _BLOCK_GAP
        column_x.append(x)
        x += _PORT_W + _GAP_X

    for position, port in enumerate(ports):
        column, row = divmod(position, rows)
        laid_out.append({
            "id": str(port["id"]),
            "label": str(port.get("label", port["id"])),
            "kind": port.get("kind", "rj45"),
            "poe": bool(port.get("poe")),
            "x": column_x[column],
            "y": _MARGIN_Y + row * (_PORT_H + _GAP_Y),
            "w": _PORT_W,
            "h": _PORT_H,
        })

    width = (column_x[-1] if column_x else _MARGIN_X) + _PORT_W + _MARGIN_X
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
