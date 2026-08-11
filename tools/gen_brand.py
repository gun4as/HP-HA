#!/usr/bin/env python3
"""
Generates the brand images the integration ships with.

Since Home Assistant 2026.3 a custom integration carries its own brand images in
a `brand/` directory next to manifest.json, and HA serves them from
/api/brands/integration/<domain>/<image>, where a local image wins over the CDN.
No pull request against home-assistant/brands is needed - the custom_integrations
folder over there is now marked legacy. On HA older than 2026.3 the directory is
simply ignored and HACS falls back to its generated placeholder.

Both use the same colour language as the Lovelace card: green 1G, blue 10G,
amber 10/100M, grey down, orange PoE.

A real faceplate is roughly 9:1 and cannot fill a square, so the icon is a
square chassis with two rows of three chunky ports - it has to survive being
drawn at 32px in a list. The logo is landscape and can afford to look like the
actual hardware: an SFP+ cage on the left, then two blocks of four RJ45 columns.

Everything is drawn at SS times the target size and downscaled with LANCZOS,
which is the cheapest way to get clean rounded corners out of Pillow.

    python tools/gen_brand.py

Output into custom_components/netviz/brand/, sized per the conventions the brands
repository documents, because those are what HA's own tooling expects:
  icon.png     256x256   square, PNG, transparent, trimmed
  icon@2x.png  512x512
  logo.png     480x160   landscape, shortest side within 128-256
  logo@2x.png  960x320   shortest side within 256-512

`dark_icon.png` and `dark_logo.png` are also supported by HA; this artwork already
sits on a dark chassis and reads on both themes, so there is no separate variant.
"""

from pathlib import Path

from PIL import Image, ImageDraw

SS = 8  # supersampling factor
OUT = Path(__file__).resolve().parent.parent / "custom_components" / "netviz" / "brand"

CHASSIS_FILL = (32, 36, 41, 255)
CHASSIS_EDGE = (72, 80, 88, 255)
PORT_EDGE = (18, 20, 23, 255)

GREEN = (62, 196, 109, 255)
BLUE = (46, 163, 242, 255)
AMBER = (242, 182, 50, 255)
GREY = (111, 115, 120, 255)
POE = (255, 109, 0, 255)
POE_EDGE = (0, 0, 0, 190)

# Two rows of three, drawn chunky. Four columns looked right at 256px and turned
# into confetti at 32px, which is the size that actually matters in a list.
LAYOUT = [
    [GREEN, AMBER, BLUE],
    [GREEN, GREY, GREEN],
]
# Ports drawing PoE, as (row, column)
POE_PORTS = {(0, 1), (1, 0)}


def build(size: int) -> Image.Image:
    s = size * SS
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # --- chassis: fills the whole canvas, so the icon needs no trimming -------
    # Edge to edge on purpose: the brands repo wants the minimum amount of empty
    # space, and a rounded rectangle still touches all four sides at its midpoints.
    inset = 0
    d.rounded_rectangle(
        [inset, inset, s - inset - 1, s - inset - 1],
        radius=s * 0.17,
        fill=CHASSIS_FILL,
        outline=CHASSIS_EDGE,
        width=max(1, int(s * 0.012)),
    )

    # --- ports ---------------------------------------------------------------
    cols, rows = len(LAYOUT[0]), len(LAYOUT)
    margin_x = s * 0.10
    gap_x = s * 0.045
    gap_y = s * 0.07
    port_w = (s - 2 * margin_x - (cols - 1) * gap_x) / cols
    port_h = port_w * 1.05
    block_h = rows * port_h + (rows - 1) * gap_y
    top = (s - block_h) / 2

    for r, row in enumerate(LAYOUT):
        for c, colour in enumerate(row):
            x0 = margin_x + c * (port_w + gap_x)
            y0 = top + r * (port_h + gap_y)
            d.rounded_rectangle(
                [x0, y0, x0 + port_w, y0 + port_h],
                radius=port_w * 0.16,
                fill=colour,
                outline=PORT_EDGE,
                width=max(1, int(s * 0.006)),
            )
            if (r, c) in POE_PORTS:
                # Same idea as on the card: orange fill plus a dark outline, so
                # the dot survives on top of amber as well as green.
                cx = x0 + port_w * 0.80
                cy = y0 + port_h * 0.74
                rad = port_w * 0.135
                d.ellipse(
                    [cx - rad, cy - rad, cx + rad, cy + rad],
                    fill=POE,
                    outline=POE_EDGE,
                    width=max(1, int(s * 0.007)),
                )

    return img.resize((size, size), Image.LANCZOS)


def build_logo(height: int) -> Image.Image:
    """Landscape logo: a faceplate with the SFP+ cage and two blocks of RJ45.

    brands constrains the shortest side to 128-256 (256-512 for hDPI) and asks for
    landscape, so this is 3:1 rather than the 9:1 of the real chassis. Eight RJ45
    columns rather than twenty-four, because at 3:1 more columns only makes each
    port smaller - twelve columns turned the ports into specks.
    """
    h = height * SS
    w = h * 3
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle(
        [0, 0, w - 1, h - 1],
        radius=h * 0.13,
        fill=CHASSIS_FILL,
        outline=CHASSIS_EDGE,
        width=max(1, int(h * 0.02)),
    )

    margin_x = h * 0.11
    gap_x = h * 0.055
    gap_y = h * 0.09
    block_gap = h * 0.16
    sfp_cols, rj_cols, block = 1, 8, 4
    port_w = (
        w - 2 * margin_x - block_gap
        - (sfp_cols + rj_cols - 2) * gap_x
        - (rj_cols // block - 1) * block_gap
    ) / (sfp_cols + rj_cols)
    port_h = port_w * 1.05
    top = (h - (2 * port_h + gap_y)) / 2

    # SFP+ cage on the left, exactly as on a JL357A
    palette = [BLUE, BLUE] + [
        GREEN, GREY, GREEN, GREEN, AMBER, GREEN, GREEN, GREEN, GREY, AMBER, GREEN, GREEN,
        GREEN, GREEN, GREY, GREEN, GREEN, AMBER, GREEN, GREY, GREEN, GREEN, GREEN, GREY,
    ]
    poe_at = {5, 9, 14, 20}

    x = margin_x
    index = 0
    for col in range(sfp_cols + rj_cols):
        if col == sfp_cols:
            x += block_gap
        elif col > sfp_cols and (col - sfp_cols) % block == 0:
            x += block_gap
        for row in (0, 1):
            y = top + row * (port_h + gap_y)
            d.rounded_rectangle(
                [x, y, x + port_w, y + port_h],
                radius=port_w * 0.18,
                fill=palette[index % len(palette)],
                outline=PORT_EDGE,
                width=max(1, int(h * 0.012)),
            )
            if index in poe_at:
                cx, cy = x + port_w * 0.79, y + port_h * 0.75
                rad = port_w * 0.15
                d.ellipse(
                    [cx - rad, cy - rad, cx + rad, cy + rad],
                    fill=POE,
                    outline=POE_EDGE,
                    width=max(1, int(h * 0.012)),
                )
            index += 1
        x += port_w + gap_x

    return img.resize((w // SS, h // SS), Image.LANCZOS)


def main() -> None:
    for height, name in ((160, "logo.png"), (320, "logo@2x.png")):
        img = build_logo(height)
        path = OUT / name
        img.save(path, "PNG", optimize=True)
        print(
            f"  {name:12} {img.size[0]}x{img.size[1]}  "
            f"{path.stat().st_size / 1024:5.1f} KB  shortest side {min(img.size)}"
        )

    for size, name in ((256, "icon.png"), (512, "icon@2x.png")):
        img = build(size)
        path = OUT / name
        # optimize=True gives lossless zlib compression; the brands repo asks for
        # optimised, losslessly compressed PNGs
        img.save(path, "PNG", optimize=True)
        bbox = img.getbbox()
        print(
            f"  {name:12} {img.size[0]}x{img.size[1]}  "
            f"{path.stat().st_size / 1024:5.1f} KB  content bbox {bbox}"
        )


if __name__ == "__main__":
    main()
