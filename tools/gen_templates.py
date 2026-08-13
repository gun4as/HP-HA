#!/usr/bin/env python3
"""
Generates faceplate templates for hardware whose front panel is known.

A template is geometry and nothing else. The ports themselves always come from
the device, so a slot carries only a shape, a position and which discovered port
belongs in it - never a name. That matters on RouterOS, where an interface is
called whatever the operator typed and a template keyed on `ether1` would break
the moment somebody renamed it.

`index` is the position in the device's own ifIndex order. On every MikroTik
checked, that order runs left to right across the front panel, including a
CRS309 where the RJ45 sits on the right and comes last in ifIndex. Where a future
model disagrees, the index is what gets corrected, not the drawing.

    python tools/gen_templates.py

Front panels read off product photographs. Anything read from convention rather
than from a photograph is marked in the spec below.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "custom_components" / "netviz" / "models"

RJ45_W, RJ45_H = 22, 18
SFP_W, SFP_H = 30, 18
GAP_X, GAP_Y = 4, 6
BLOCK_GAP = 14
MARGIN_X, MARGIN_Y = 26, 26

# A row is a list of blocks; a block is a list of columns; a column is a list of
# (kind, index) from top to bottom. Blocks are separated by a wider gap, the way
# a front panel groups ports.
SPECS = [
    {
        "slug": "mikrotik_crs309",
        "model": "CRS309-1G-8S+",
        "display": "MikroTik CRS309-1G-8S+",
        # Photo: SFP+ 1 through 8 in one row, then the RJ45 marked POE/BOOT.
        "blocks": [
            [[("sfp+", i)] for i in range(8)],
            [[("rj45", 8)]],
        ],
    },
    {
        "slug": "mikrotik_crs112",
        "model": "CRS112-8G-4S",
        "display": "MikroTik CRS112-8G-4S",
        # Photo: eight RJ45 in two rows of four, then four SFP in two rows of two.
        # CONVENTION, not photograph: which of each pair is the lower number.
        # Column-major is what MikroTik and HP both use on two-row panels, so
        # 1 sits above 2. If the card shows a port's state in the wrong place,
        # this is the line to change.
        "blocks": [
            [[("rj45", c * 2), ("rj45", c * 2 + 1)] for c in range(4)],
            [[("sfp+", 8 + c * 2), ("sfp+", 9 + c * 2)] for c in range(2)],
        ],
    },
    {
        "slug": "mikrotik_rb2011",
        "model": "RB2011UiAS",
        "display": "MikroTik RB2011UiAS",
        # Photo: SFP on the left, then ETH1-5 under GIGABIT ETHERNET, then the
        # LED block, then ETH6-10 under FAST ETHERNET.
        "blocks": [
            [[("sfp+", 0)]],
            [[("rj45", i)] for i in range(1, 6)],
            [[("rj45", i)] for i in range(6, 11)],
        ],
    },
    {
        "slug": "mikrotik_rb951",
        "model": "RB951Ui-2HnD",
        "display": "MikroTik RB951Ui-2HnD",
        # Photo: five RJ45 in one row, port 5 marked with the PoE-out bolt.
        "blocks": [[[("rj45", i)] for i in range(5)]],
    },
    {
        "slug": "mikrotik_hap_ac3",
        "model": "RBD53iG-5HacD2HnD",
        "display": "MikroTik hAP ac³",
        # Photo: five RJ45 in one row, 1 marked Internet and 2-5 LAN.
        "blocks": [[[("rj45", i)] for i in range(5)]],
    },
    {
        "slug": "mikrotik_cap_ac",
        "model": "RBcAPGi-5acD2nD",
        "display": "MikroTik cAP ac",
        # Photo: ETH1 and ETH2 side by side on the underside.
        "blocks": [[[("rj45", 0)], [("rj45", 1)]]],
    },
]


def build(spec: dict) -> dict:
    slots: list[dict] = []
    x = MARGIN_X
    rows = max(len(column) for block in spec["blocks"] for column in block)

    for block_number, block in enumerate(spec["blocks"]):
        if block_number:
            x += BLOCK_GAP - GAP_X
        for column in block:
            width = max(SFP_W if kind == "sfp+" else RJ45_W for kind, _ in column)
            for row, (kind, index) in enumerate(column):
                height = SFP_H if kind == "sfp+" else RJ45_H
                slots.append({
                    "index": index,
                    "kind": kind,
                    "x": x,
                    "y": MARGIN_Y + row * (RJ45_H + GAP_Y),
                    "w": width,
                    "h": height,
                })
            x += width + GAP_X

    width = x - GAP_X + MARGIN_X
    height = MARGIN_Y * 2 + RJ45_H * rows + GAP_Y * (rows - 1)
    return {
        "model": spec["model"],
        "vendor": "MikroTik",
        "display": spec["display"],
        # Ports come from the device and are paired with these slots by index.
        # Nothing here names an interface.
        "match": "order",
        "faceplate": {
            "width": width,
            "height": height,
            "viewbox": f"0 0 {width} {height}",
        },
        "ports": sorted(slots, key=lambda s: s["index"]),
    }


def main() -> None:
    for spec in SPECS:
        data = build(spec)
        path = OUT / f"{spec['slug']}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        print(
            f"  {path.name:28} {len(data['ports']):>2} slots  "
            f"viewBox {data['faceplate']['viewbox']}"
        )


if __name__ == "__main__":
    main()
