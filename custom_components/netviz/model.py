"""Modeļu (faceplate) ielāde.

Modeļa JSON dzīvo `models/<slug>.json` un satur gan portu sarakstu ar SNMP
piesaisti, gan SVG ģeometriju. Jauns switch modelis = jauns JSON, nulle koda.
Ģenerators: tools/gen_model.py
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

_LOGGER = logging.getLogger(__name__)

MODELS_DIR = Path(__file__).parent / "models"


class ModelNotFound(Exception):
    """Pieprasītais modelis nav iepakots."""


def available_models() -> dict[str, str]:
    """{slug: cilvēkam lasāms nosaukums}."""
    out: dict[str, str] = {}
    for path in sorted(MODELS_DIR.glob("*.json")):
        try:
            with path.open(encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, json.JSONDecodeError):
            _LOGGER.warning("bojāts modeļa fails: %s", path.name)
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
        raise ModelNotFound(f"{slug}: nav portu")
    return data


def faceplate_geometry(model: dict) -> dict:
    """Kompakta ģeometrija priekškartei - bez SNMP laukiem."""
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
