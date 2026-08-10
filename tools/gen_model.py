#!/usr/bin/env python3
"""
Ģenerē modeļa JSON ar portu sarakstu un faceplate ģeometriju.

Ģeometrija ir SVG koordinātas, ko vēlāk lasīs Lovelace karte. Vienības -
patvaļīgas viewBox vienības, karte mērogo pēc konteinera platuma.

Numerācija: HP/Aruba fiksētajos 48 portu korpusos porti iet pa kolonnām -
augšā nepāra, apakšā pāra. Pārslēdz ar --numbering row, ja izrādās citādi.
"""

import argparse
import json

PORT_W = 22
PORT_H = 18
GAP_X = 4
GAP_Y = 6
BLOCK_GAP = 14      # atstarpe starp 12 portu blokiem
MARGIN_X = 26
MARGIN_Y = 26
SFP_W = 30
SFP_H = 18
SFP_GAP = 42        # atstarpe starp RJ45 lauku un SFP+ bloku


def build(rj45: int, sfp: int, block: int, numbering: str) -> dict:
    cols = rj45 // 2
    ports = []
    x = MARGIN_X
    col_x = []
    for c in range(cols):
        if c and c % (block // 2) == 0:
            x += BLOCK_GAP
        col_x.append(x)
        x += PORT_W + GAP_X

    for c in range(cols):
        for row in (0, 1):
            if numbering == "column":
                num = c * 2 + row + 1
            else:
                num = row * cols + c + 1
            ports.append({
                "id": str(num),
                "label": str(num),
                "kind": "rj45",
                "poe": True,
                "ifname": str(num),
                "poe_index": f"1.{num}",
                "x": col_x[c],
                "y": MARGIN_Y + row * (PORT_H + GAP_Y),
                "w": PORT_W,
                "h": PORT_H,
                "row": row,
                "col": c,
            })

    sfp_x0 = col_x[-1] + PORT_W + SFP_GAP
    for i in range(sfp):
        num = rj45 + i + 1
        row = i % 2
        col = i // 2
        ports.append({
            "id": str(num),
            "label": str(num),
            "kind": "sfp+",
            "poe": False,
            "ifname": str(num),
            "x": sfp_x0 + col * (SFP_W + GAP_X),
            "y": MARGIN_Y + row * (SFP_H + GAP_Y),
            "w": SFP_W,
            "h": SFP_H,
            "row": row,
            "col": cols + col,
        })

    ports.sort(key=lambda p: int(p["id"]))
    width = ports[-1]["x"] + ports[-1]["w"] + MARGIN_X
    height = MARGIN_Y * 2 + PORT_H * 2 + GAP_Y

    return {
        "model": "JL357A",
        "vendor": "HPE Aruba Networking",
        "display": "Aruba 2540-48G-PoE+-4SFP+",
        "os": "ArubaOS-Switch 16.x",
        "poe_budget_w": 370,
        "faceplate": {
            "width": width,
            "height": height,
            "viewbox": f"0 0 {width} {height}",
            "numbering": numbering,
        },
        "ports": ports,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rj45", type=int, default=48)
    ap.add_argument("--sfp", type=int, default=4)
    ap.add_argument("--block", type=int, default=12)
    ap.add_argument("--numbering", choices=["column", "row"], default="column")
    ap.add_argument("-o", "--output", default="models/jl357a.json")
    a = ap.parse_args()
    model = build(a.rj45, a.sfp, a.block, a.numbering)
    with open(a.output, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"{a.output}: {len(model['ports'])} porti, "
          f"viewBox {model['faceplate']['viewbox']}")


if __name__ == "__main__":
    main()
