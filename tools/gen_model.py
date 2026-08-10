#!/usr/bin/env python3
"""
Ģenerē modeļa JSON ar portu sarakstu un faceplate ģeometriju.

Ģeometrija ir SVG koordinātas, ko vēlāk lasīs Lovelace karte. Vienības -
patvaļīgas viewBox vienības, karte mērogo pēc konteinera platuma.

Numerācija: HP/Aruba fiksētajos 48 portu korpusos porti iet pa kolonnām -
augšā nepāra, apakšā pāra. Pārslēdz ar --numbering row, ja izrādās citādi.

SFP+ puse: uz JL357A tie fiziski ir pa KREISI no porta 1, un tāpat tos zīmē
switch'a paša web saskarne. Uz citiem korpusiem uplinki mēdz būt pa labi -
tad --sfp-side right.
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


def build(
    rj45: int,
    sfp: int,
    block: int,
    numbering: str,
    sfp_side: str,
    meta: dict,
) -> dict:
    cols = rj45 // 2
    sfp_cols = (sfp + 1) // 2
    ports: list[dict] = []

    # --- kolonnu x koordinātas -----------------------------------------------
    x = MARGIN_X
    sfp_x: list[int] = []
    if sfp and sfp_side == "left":
        sfp_x = [x + i * (SFP_W + GAP_X) for i in range(sfp_cols)]
        x = sfp_x[-1] + SFP_W + SFP_GAP

    col_x: list[int] = []
    for c in range(cols):
        if c and c % (block // 2) == 0:
            x += BLOCK_GAP
        col_x.append(x)
        x += PORT_W + GAP_X

    if sfp and sfp_side == "right":
        x0 = col_x[-1] + PORT_W + SFP_GAP
        sfp_x = [x0 + i * (SFP_W + GAP_X) for i in range(sfp_cols)]

    # `col` ir vizuālais kolonnas indekss no kreisās puses - to lieto karte
    rj45_col0 = sfp_cols if sfp_side == "left" else 0
    sfp_col0 = 0 if sfp_side == "left" else cols

    # --- RJ45 ----------------------------------------------------------------
    for c in range(cols):
        for row in (0, 1):
            num = c * 2 + row + 1 if numbering == "column" else row * cols + c + 1
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
                "col": rj45_col0 + c,
            })

    # --- SFP+ ----------------------------------------------------------------
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
            "x": sfp_x[col],
            "y": MARGIN_Y + row * (SFP_H + GAP_Y),
            "w": SFP_W,
            "h": SFP_H,
            "row": row,
            "col": sfp_col0 + col,
        })

    ports.sort(key=lambda p: int(p["id"]))
    # pēc x, nevis pēc pēdējā porta: ar SFP+ pa kreisi pēdējais ports nav
    # arī tālākais pa labi
    width = max(p["x"] + p["w"] for p in ports) + MARGIN_X
    height = MARGIN_Y * 2 + PORT_H * 2 + GAP_Y

    return {
        **meta,
        "faceplate": {
            "width": width,
            "height": height,
            "viewbox": f"0 0 {width} {height}",
            "numbering": numbering,
            "sfp_side": sfp_side,
        },
        "ports": ports,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rj45", type=int, default=48)
    ap.add_argument("--sfp", type=int, default=4)
    ap.add_argument("--block", type=int, default=12)
    ap.add_argument("--numbering", choices=["column", "row"], default="column")
    ap.add_argument("--sfp-side", choices=["left", "right"], default="left")
    ap.add_argument("--model", default="JL357A")
    ap.add_argument("--vendor", default="HPE Aruba Networking")
    ap.add_argument("--display", default="Aruba 2540-48G-PoE+-4SFP+")
    ap.add_argument("--os", dest="os_name", default="ArubaOS-Switch 16.x")
    ap.add_argument("--poe-budget", type=int, default=370)
    ap.add_argument("-o", "--output", default="custom_components/netviz/models/jl357a.json")
    a = ap.parse_args()

    model = build(
        a.rj45, a.sfp, a.block, a.numbering, a.sfp_side,
        {
            "model": a.model,
            "vendor": a.vendor,
            "display": a.display,
            "os": a.os_name,
            "poe_budget_w": a.poe_budget,
        },
    )
    with open(a.output, "w", encoding="utf-8") as fh:
        json.dump(model, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"{a.output}: {len(model['ports'])} porti, "
          f"viewBox {model['faceplate']['viewbox']}, SFP+ {a.sfp_side}")


if __name__ == "__main__":
    main()
