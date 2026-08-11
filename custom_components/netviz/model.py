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
