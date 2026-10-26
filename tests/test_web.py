"""The GPU port (web/analog.js) against the Python, in a headless browser.

Both run the same picture through the same settings at the decoder's own 754 x 480. Without
noise (60 dB) the pictures must agree to the level, nearly: same filters, same decoder, in
float32 rather than float64. With noise they cannot (another random generator), so they
must agree in what the noise does: how strong the grain is, when colour goes, when sync
goes.

Needs Chrome or Chromium (ANALOG_VISION_CHROME, or on the PATH) and is skipped without one.
A GPU makes it quick; without one Chrome's software renderer is used.
"""

import base64
import functools
import http.server
import os
import shutil
import threading
from collections.abc import Iterator
from dataclasses import asdict, fields
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from numpy.typing import NDArray
from PIL import Image

from analog_vision import AnalogVideo, Decoder, Dvr, Echo, Link, link_cnr_db
from analog_vision.patterns import colour_bars

WEB = Path(__file__).resolve().parents[1] / "src/analog_vision/web"
LAB = Path(__file__).resolve().parents[1] / "reference/lab/lab_02.jpeg"
SIZE = (754, 480)
FRAMES = 4
"""Frames through the link before the picture is taken: the decoder locks, levels settle."""

HARNESS = """<!doctype html><meta charset="utf-8">
<canvas id="c" width="754" height="480"></canvas>
<script type="module">
import { AnalogFeed, DEFAULTS, DVR, HDMI_CAPTURE, linkCnrDb } from "./analog.js";
const feed = new AnalogFeed(document.getElementById("c"), {}, { fit: false });
const pictures = {};
for (const name of ["bars", "lab"]) {
  const img = new Image();
  img.src = name + ".png";
  await img.decode();
  pictures[name] = img;
}
window.defaults = { ...DEFAULTS, dvr: DVR, hdmi_capture: HDMI_CAPTURE };
window.ok = feed.ok;
window.render = (picture, settings, seed, lines) => {
  feed.set(DEFAULTS);
  feed.set({ ...settings, seed });
  feed.reset();
  feed.run(pictures[picture], lines);
  const px = feed.pixels();
  let s = "";
  for (let i = 0; i < px.length; i += 0x8000) {
    s += String.fromCharCode(...px.subarray(i, i + 0x8000));
  }
  return { pixels: btoa(s), stats: feed.stats() };
};
window.recorded = async (picture, settings, seed, lines) => {
  window.render(picture, settings, seed, lines);
  const canvas = await feed.recorded();
  const px = canvas.getContext("2d").getImageData(0, 0, canvas.width, canvas.height).data;
  let s = "";
  for (let i = 0; i < px.length; i += 0x8000) {
    s += String.fromCharCode(...px.subarray(i, i + 0x8000));
  }
  return { pixels: btoa(s), width: canvas.width, height: canvas.height };
};
window.linkCnrDb = linkCnrDb;
window.ready = true;
</script>"""


def _chrome() -> str | None:
    found = os.environ.get("ANALOG_VISION_CHROME")
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        found = found or shutil.which(name)
    return found


def _pictures() -> dict[str, NDArray[np.uint8]]:
    lab = Image.open(LAB).convert("RGB").crop((106, 0, 746, 480))
    return {
        "bars": (colour_bars(*SIZE) * 255 + 0.5).astype(np.uint8),
        "lab": np.asarray(lab.resize(SIZE, Image.Resampling.LANCZOS)),
    }


PICTURES = _pictures()


class Gpu:
    """The page in the browser: renders as the Python's AnalogVideo does."""

    def __init__(self, page: Any) -> None:  # noqa: ANN401
        self.page = page

    def render(
        self, picture: str, settings: dict[str, Any], seed: int = 1, frames: int = FRAMES
    ) -> tuple[NDArray[np.uint8], dict[str, float]]:
        r = self.page.evaluate(
            "([p, s, seed, lines]) => window.render(p, s, seed, lines)",
            [picture, settings, seed, frames * 525],
        )
        px = np.frombuffer(base64.b64decode(r["pixels"]), np.uint8)
        return px.reshape(SIZE[1], SIZE[0], 4)[..., :3], r["stats"]


@pytest.fixture(scope="module")
def gpu(tmp_path_factory: pytest.TempPathFactory) -> Iterator[Gpu]:
    chrome = _chrome()
    sync_api = pytest.importorskip("playwright.sync_api")
    if not chrome:
        pytest.skip("no Chrome or Chromium: set ANALOG_VISION_CHROME")
    root = tmp_path_factory.mktemp("web")
    shutil.copy(WEB / "analog.js", root / "analog.js")
    (root / "index.html").write_text(HARNESS)
    for name, image in PICTURES.items():
        Image.fromarray(image).save(root / f"{name}.png")
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *_: None  # type: ignore[method-assign]
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    # The GPU where Chrome can have it; its software renderer where not.
    args = ["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=vulkan"]
    args.append("--enable-unsafe-swiftshader")
    with sync_api.sync_playwright() as p:
        browser = p.chromium.launch(executable_path=chrome, args=args)
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(f"http://127.0.0.1:{server.server_address[1]}/index.html")
        page.wait_for_function("window.ready === true || window.ok === false", timeout=60_000)
        assert not errors, errors
        if not page.evaluate("window.ok"):
            pytest.skip("no WebGL2 with float render targets in this browser")
        yield Gpu(page)
        browser.close()
    server.shutdown()


def python(
    picture: str, settings: dict[str, Any], seed: int = 1, frames: int = FRAMES
) -> tuple[NDArray[np.uint8], dict[str, float]]:
    link = dict(settings.get("link", {}))
    echoes = tuple(Echo(**e) for e in link.pop("multipath", []))
    decoder = dict(settings.get("decoder", {}))
    if "agc_range" in decoder:
        decoder["agc_range"] = tuple(decoder["agc_range"])
    sim = AnalogVideo(
        Link(**link, multipath=echoes),
        Decoder(**decoder),
        seed=seed,
        deinterlace=settings.get("deinterlace", "weave"),
        size=SIZE,
    )
    for _ in range(frames - 1):
        sim.show(PICTURES[picture])
    shown = sim.show(PICTURES[picture])
    return shown.image, {"synced": shown.synced, "colour": shown.colour}


def luma(image: NDArray[np.uint8]) -> NDArray[np.float64]:
    return image.astype(np.float64) @ np.array([0.299, 0.587, 0.114])


INNER = (slice(30, 450), slice(40, 714))
"""Away from the picture's edges, where the two scale and blank alike but not exactly."""


def test_settings_default_as_in_python(gpu: Gpu) -> None:
    js = gpu.page.evaluate("window.defaults")
    for cls, key in ((Link, "link"), (Decoder, "decoder")):
        py = asdict(cls())
        py = {k: list(v) if isinstance(v, tuple) else v for k, v in py.items()}
        assert js[key] == pytest.approx(py), f"{cls.__name__} defaults differ"
    assert {f.name for f in fields(Link)} == set(js["link"])
    for js_dvr, py_dvr in ((js["dvr"], Dvr()), (js["hdmi_capture"], Dvr.hdmi_capture())):
        assert js_dvr == {**asdict(py_dvr), "size": list(py_dvr.size)}
    assert js["deinterlace"] == "weave" and js["dvr"] is not None


CLEAN = {"link": {"cnr_db": 60}}
DETERMINISTIC: dict[str, tuple[str, dict[str, Any]]] = {
    "bars": ("bars", CLEAN),
    "lab": ("lab", CLEAN),
    "bob": ("lab", {**CLEAN, "deinterlace": "bob"}),
    "comb": ("bars", {**CLEAN, "decoder": {"yc": "comb"}}),
    "comb lab": ("lab", {**CLEAN, "decoder": {"yc": "comb"}}),
    "echo": (
        "lab",
        {"link": {"cnr_db": 60, "multipath": [asdict(Echo(40e-9, -1, 170))]}},
    ),
    "echoes": (
        "bars",
        {
            "link": {
                "cnr_db": 60,
                "multipath": [asdict(Echo(30e-9, -3, 40)), asdict(Echo(95.5e-9, -6, 200))],
            }
        },
    ),
    "tuned off": ("bars", {"link": {"cnr_db": 60, "carrier_offset_hz": 0.4e6}}),
    "narrow": (
        "lab",
        {
            "link": {"cnr_db": 60, "if_bandwidth_hz": 10e6, "deviation_hz": 3e6},
            "decoder": {"luma_bandwidth_hz": 2e6, "chroma_lowpass_hz": 0.3e6},
        },
    ),
    "levels": (
        "bars",
        {"link": {"cnr_db": 60}, "decoder": {"acc_max_gain": 1.2, "agc_range": [0.9, 1.1]}},
    ),
}


@pytest.mark.parametrize("case", DETERMINISTIC)
def test_without_noise_the_pictures_agree(gpu: Gpu, case: str) -> None:
    picture, settings = DETERMINISTIC[case]
    a, sa = gpu.render(picture, settings)
    b, sb = python(picture, settings)
    d = np.abs(a.astype(np.float64) - b)[INNER]
    assert d.mean() < 0.3, f"{case}: mean difference {d.mean():.2f} levels"
    assert d.max() <= 4, f"{case}: {d.max():.0f} levels apart"
    assert sa == pytest.approx(sb, abs=0.02)


def noise_db(render: Any, cnr: float, seeds: range) -> float:  # noqa: ANN401
    """How strong the grain is: the luma's difference from the clean picture, rms, in dB."""
    clean = luma(render("lab", CLEAN, 1)[0])[INNER]
    power = [
        np.mean((luma(render("lab", {"link": {"cnr_db": cnr}}, s)[0])[INNER] - clean) ** 2)
        for s in seeds
    ]
    return float(10 * np.log10(np.mean(power)))


@pytest.mark.parametrize("cnr", [15, 10, 7])
def test_the_grain_is_as_strong(gpu: Gpu, cnr: float) -> None:
    g = noise_db(gpu.render, cnr, range(1, 7))
    p = noise_db(python, cnr, range(1, 4))
    assert g == pytest.approx(p, abs=0.25), f"{cnr} dB: GPU {g:.2f} dB, Python {p:.2f} dB"


@pytest.mark.parametrize(
    ("cnr", "colour", "synced"),
    [(11, True, True), (4, False, True), (-6, False, False)],
)
def test_colour_and_sync_go_at_the_same_signal(
    gpu: Gpu, cnr: float, colour: bool, synced: bool
) -> None:
    for render in (gpu.render, python):
        stats = [render("bars", {"link": {"cnr_db": cnr}}, s)[1] for s in (1, 2)]
        assert all((st["colour"] > 0.5) == colour for st in stats), (render, stats)
        assert all((st["synced"] > 0.8) == synced for st in stats), (render, stats)


def test_no_signal_shows_the_blue_screen(gpu: Gpu) -> None:
    settings = {"link": {"cnr_db": -15}, "decoder": {"on_loss": "blue"}}
    for render in (gpu.render, python):
        image = render("bars", settings)[0]
        assert np.abs(image[INNER].reshape(-1, 3).mean(0) - (0, 0, 191)).max() < 2


@pytest.mark.parametrize("dvr", [Dvr(), Dvr.hdmi_capture()], ids=["goggles", "hdmi"])
def test_the_recorder_keeps_much_the_same(gpu: Gpu, dvr: Dvr) -> None:
    """The browser's JPEG encoder and scaler are not PIL's: close, not to the level."""
    settings = {"link": {"cnr_db": 60}, "dvr": {**asdict(dvr), "size": list(dvr.size)}}
    r = gpu.page.evaluate(
        "([p, s, seed, lines]) => window.recorded(p, s, seed, lines)",
        ["lab", settings, 1, FRAMES * 525],
    )
    px = np.frombuffer(base64.b64decode(r["pixels"]), np.uint8)
    a = px.reshape(r["height"], r["width"], 4)[..., :3]
    sim = AnalogVideo(Link(cnr_db=60), seed=1, size=dvr.size, dvr=dvr)
    for _ in range(FRAMES - 1):
        sim.show(PICTURES["lab"])
    d = np.abs(a.astype(np.float64) - sim.show(PICTURES["lab"]).image)
    assert d.mean() < 2 and np.percentile(d, 99) < 10, (d.mean(), np.percentile(d, 99))


def test_the_link_budget_is_the_same(gpu: Gpu) -> None:
    more = {
        "frequency_hz": 5.7e9,
        "noise_figure_db": 7,
        "extra_loss_db": 4,
        "if_bandwidth_hz": 16e6,
    }
    js = gpu.page.evaluate(
        "m => window.linkCnrDb(1234, 200, 1.5, 3, m)",
        more,
    )
    assert js == pytest.approx(link_cnr_db(1234, 200, 1.5, 3, **more))
