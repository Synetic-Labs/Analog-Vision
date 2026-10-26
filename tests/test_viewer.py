"""The viewer: every setting on the page, and the page's picture the library's."""

import json
import re
from dataclasses import fields
from pathlib import Path

import numpy as np
from PIL import Image

from analog_vision import Decoder, Dvr, Echo, Link, degrade
from analog_vision.patterns import colour_bars
from analog_vision.viewer import build, export, render, schema

BARS = (colour_bars() * 255 + 0.5).astype(np.uint8)


def test_every_setting_has_a_control() -> None:
    s = json.loads(json.dumps(schema([{"name": "bars", "url": "bars.png"}])))
    controls = s["controls"]
    for cls, key in ((Link, "link"), (Decoder, "decoder"), (Echo, "echo"), (Dvr, "dvr")):
        shown = {c["name"] for c in controls[key]}
        missing = {f.name for f in fields(cls)} - shown - {"multipath"}
        assert not missing, f"{cls.__name__} fields with no control in viewer.py: {missing}"
    assert all(c["doc"] for c in controls["link"])


def test_the_page_shows_what_degrade_does() -> None:
    state = {"link": {"cnr_db": 9}, "seed": 1, "frames": 2}
    out, info = render(state, BARS)
    assert np.array_equal(out, degrade(BARS, cnr_db=9, seed=1))
    assert info["cnr_db"] == 9


def test_settings_come_back_as_their_types() -> None:
    d = build(Decoder, {"h_window": 12.4, "agc_range": [0.5, 2], "yc": "comb"})
    assert d.h_window == 12 and d.agc_range == (0.5, 2.0) and d.yc == "comb"
    assert build(Dvr, {"size": [320.0, 240.0], "one_field": 0}) == Dvr(
        size=(320, 240), one_field=False
    )
    assert build(Echo, {"delay_s": 4e-8, "level_db": -1}) == Echo(4e-8, -1.0)


def test_the_page_exports_as_static_files(tmp_path: Path) -> None:
    picture = tmp_path / "in.png"
    Image.fromarray(BARS).save(picture)
    export([picture], tmp_path / "site")
    s = json.loads((tmp_path / "site/api/schema").read_text())
    assert s["python"] is False
    assert [p["url"] for p in s["pictures"]] == ["pictures/bars.png", "pictures/in.png"]
    for url in ("index.html", "analog.js", *(p["url"] for p in s["pictures"])):
        assert (tmp_path / "site" / url).is_file()
    # What the page's head points at (icons, the social card), relative or at its home.
    head = (tmp_path / "site/index.html").read_text().split("</head>")[0]
    linked = re.findall(
        r'(?:href|content)="(?:https://synetic-labs\.github\.io/Analog-Vision/)?([\w.-]+\.(?:svg|png|jpg))"',
        head,
    )
    assert {"favicon.svg", "icon.png", "social.jpg"} <= set(linked)
    for name in linked:
        assert (tmp_path / "site" / name).is_file(), name
