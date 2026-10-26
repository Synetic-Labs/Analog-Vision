"""docs/effects.jpg: colour bars through the link, one tile for each kind of damage; and from
the same tiles the viewer's social card (web/social.jpg, 1200 x 630, for Open Graph and X)
and its home-screen icon (web/icon.png, colour bars as web/favicon.svg draws them).

uv run python scripts/effects.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from analog_vision import AnalogVideo, Echo, Link
from analog_vision.patterns import BARS_75, colour_bars

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs/effects.jpg"
WEB = ROOT / "src/analog_vision/web"
CARD = (1200, 630)
ICON = 180
BG = "#0f1012"
ACCENT = "#e3a33b"
TILE = (400, 300)
CAPTION = 52
GAP = 6
COLUMNS = 4

MOVING = (Echo(30e-9, -1, 0, doppler_hz=90), Echo(80e-9, -4, 90, doppler_hz=-60))
"""A blocked direct path and two walls, the drone flying at about 4 m/s."""
SEEDS = {"Sparklies": 2, "Tearing": 4, "Multipath: moving": 7}
"""Draws that show each effect plainly at this size."""
EFFECTS = [
    ("Clean", "30 dB: soft, dot crawl", Link(cnr_db=30)),
    ("Grain, colour noise", "12 dB", Link(cnr_db=12)),
    ("Sparklies", "7 dB, near the FM threshold", Link(cnr_db=7)),
    ("Colour killer", "5 dB: black and white", Link(cnr_db=5)),
    ("Tearing", "3 dB: syncs lost, lines torn", Link(cnr_db=3)),
    ("Snow", "-8 dB: no signal", Link(cnr_db=-8)),
    (
        "Multipath: hue",
        "echo 40 ns, -1 dB: hue moves with brightness",
        Link(cnr_db=30, multipath=(Echo(40e-9, -1, 170),)),
    ),
    ("Multipath: moving", "echoes turning as it flies: bands", Link(cnr_db=20, multipath=MOVING)),
]


def shown(image: np.ndarray, link: Link, seed: int) -> Image.Image:
    sim = AnalogVideo(link, seed=seed)
    for _ in range(3):  # lock, then let the AGC and colour killer settle
        sim(image)
    return Image.fromarray(sim(image))


def sheet(tiles: list[Image.Image]) -> Image.Image:
    rows = -(-len(EFFECTS) // COLUMNS)
    w, h = TILE
    out = Image.new(
        "RGB", (COLUMNS * w + (COLUMNS + 1) * GAP, rows * (h + CAPTION + GAP) + GAP), "#111"
    )
    draw = ImageDraw.Draw(out)
    title = ImageFont.load_default(size=19)
    note = ImageFont.load_default(size=14)
    for i, ((name, detail, _), tile) in enumerate(zip(EFFECTS, tiles, strict=True)):
        x = GAP + (i % COLUMNS) * (w + GAP)
        y = GAP + (i // COLUMNS) * (h + CAPTION + GAP)
        out.paste(tile.resize(TILE, Image.Resampling.LANCZOS), (x, y))
        draw.text((x + 2, y + h + 6), name, font=title, fill="#f2f2f2")
        draw.text((x + 2, y + h + 30), detail, font=note, fill="#a8a8a8")
    return out


def card(tiles: list[Image.Image]) -> Image.Image:
    """The social card: the name, what it is, and every tile, two rows of four."""
    width, height = CARD
    margin, gap = 36, 12
    w = (width - 2 * margin - (COLUMNS - 1) * gap) // COLUMNS
    h = w * 3 // 4
    top = height - margin - 2 * h - gap
    out = Image.new("RGB", CARD, BG)
    draw = ImageDraw.Draw(out)
    draw.text((margin, 28), "analog-vision", font=ImageFont.load_default(size=54), fill="#f2f2f2")
    draw.text(
        (margin, 96),
        "Analog NTSC video over an FM link, simulated signal by signal",
        font=ImageFont.load_default(size=26),
        fill="#a8a8a8",
    )
    draw.text(
        (margin, 134),
        "Live in the browser: every setting a control",
        font=ImageFont.load_default(size=21),
        fill=ACCENT,
    )
    label = ImageFont.load_default(size=15)
    for i, ((name, _, _), tile) in enumerate(zip(EFFECTS, tiles, strict=True)):
        x = margin + (i % COLUMNS) * (w + gap)
        y = top + (i // COLUMNS) * (h + gap)
        out.paste(tile.resize((w, h), Image.Resampling.LANCZOS), (x, y))
        box = draw.textbbox((x + 8, y + h - 24), name, font=label)
        draw.rectangle((box[0] - 5, box[1] - 4, box[2] + 5, box[3] + 4), fill=(0, 0, 0))
        draw.text((x + 8, y + h - 24), name, font=label, fill="#f2f2f2")
    return out


def icon() -> Image.Image:
    """Colour bars over a grey ramp, as web/favicon.svg draws them."""
    out = Image.new("RGB", (ICON, ICON), BG)
    split = ICON * 11 // 16
    for i, colour in enumerate(BARS_75):
        x0, x1 = round(i * ICON / 7), round((i + 1) * ICON / 7)
        out.paste(tuple(round(c * 255) for c in colour), (x0, 0, x1, split))
    ramp = np.linspace(255, 0, ICON).round().astype(np.uint8)
    out.paste(Image.fromarray(np.repeat(ramp[None, :], ICON - split, 0)).convert("RGB"), (0, split))
    return out


def main() -> None:
    frame = (colour_bars() * 255 + 0.5).astype(np.uint8)
    tiles = []
    for i, (name, _, link) in enumerate(EFFECTS):
        tiles.append(shown(frame, link, seed=SEEDS.get(name, i)))
        print(name)
    OUT.parent.mkdir(exist_ok=True)
    sheet(tiles).save(OUT, quality=92)
    card(tiles).save(WEB / "social.jpg", quality=90)
    icon().save(WEB / "icon.png")
    print(OUT, WEB / "social.jpg", WEB / "icon.png", sep="\n")


if __name__ == "__main__":
    main()
