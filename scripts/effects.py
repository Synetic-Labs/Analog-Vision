"""docs/effects.jpg: one lab frame through the link, one tile for each kind of damage.

uv run python scripts/effects.py
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from analog_vision import AnalogVideo, Echo, Link

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "reference/lab/lab_02.jpeg"
OUT = ROOT / "docs/effects.jpg"
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
    return Image.fromarray(sim(image)).resize(TILE, Image.Resampling.LANCZOS)


def main() -> None:
    frame = np.asarray(Image.open(SOURCE).convert("RGB"))[:, 106:746]
    rows = -(-len(EFFECTS) // COLUMNS)
    w, h = TILE
    sheet = Image.new(
        "RGB", (COLUMNS * w + (COLUMNS + 1) * GAP, rows * (h + CAPTION + GAP) + GAP), "#111"
    )
    draw = ImageDraw.Draw(sheet)
    title = ImageFont.load_default(size=19)
    note = ImageFont.load_default(size=14)
    for i, (name, detail, link) in enumerate(EFFECTS):
        x = GAP + (i % COLUMNS) * (w + GAP)
        y = GAP + (i // COLUMNS) * (h + CAPTION + GAP)
        sheet.paste(shown(frame, link, seed=SEEDS.get(name, i)), (x, y))
        draw.text((x + 2, y + h + 6), name, font=title, fill="#f2f2f2")
        draw.text((x + 2, y + h + 30), detail, font=note, fill="#a8a8a8")
        print(name)
    OUT.parent.mkdir(exist_ok=True)
    sheet.save(OUT, quality=92)
    print(OUT)


if __name__ == "__main__":
    main()
