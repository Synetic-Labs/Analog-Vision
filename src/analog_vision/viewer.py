"""A web page for trying the simulation's settings on a picture, and seeing what each does.

    analog-vision view                     # the pictures under ./reference, and colour bars
    analog-vision view photo.jpg --port 8000
    analog-vision view --export site/      # the page as static files, to host anywhere

The page (web/index.html) runs the chain live on the GPU (web/analog.js, held to this
package by tests/test_web.py), so it plays as video and follows every control as it moves.
Every setting of the link, the decoder and the recorder is a control, with the note it is
documented with where it is defined, and any one can be swept across its range: a picture at
each value. This server gives it the controls, the pictures, and the Python's own picture
for any settings, to set beside the GPU's.
"""

import ast
import inspect
import io
import json
import os
import threading
import time
import webbrowser
from concurrent.futures import ProcessPoolExecutor
from dataclasses import MISSING, asdict, fields, replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from typing import Any, Literal, get_args, get_origin
from urllib.parse import parse_qs, quote, urlparse

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from analog_vision.decode import Decoder
from analog_vision.encode import to_float
from analog_vision.fm import Echo, Link, indoor_echoes, link_cnr_db
from analog_vision.patterns import colour_bars
from analog_vision.pipeline import AnalogVideo, Dvr

Control = dict[str, Any]
"""How a setting is shown: its range and step in the unit shown, `scale` from its own unit
to that one, `log` for a slider that runs in ratios, `group` to set it with its kind."""

MHZ = {"scale": 1e-6, "unit": "MHz"}
NS = {"scale": 1e9, "unit": "ns"}

RUN: dict[str, Control] = {
    "seed": {
        "default": 0, "min": 0, "max": 999, "step": 1,
        "doc": "The receiver noise's draw: another seed, another picture at the same CNR.",
    },
    "frames": {
        "default": 4, "min": 1, "max": 12, "step": 1,
        "doc": "Frames through the link before a still is taken (a sweep's, the Python's, or "
        "the live view's while paused). The decoder locks on the first; more let its AGC and "
        "colour killer settle, and moving echoes turn.",
    },
    "deinterlace": {
        "default": "weave", "choices": ["weave", "bob"],
        "doc": "Weave the last two fields together, or line-double the last one.",
    },
}  # fmt: skip

LINK: dict[str, Control] = {
    "cnr_db": {"min": -10, "max": 40, "step": 0.5, "unit": "dB"},
    "deviation_hz": {"min": 0.5, "max": 12, "step": 0.1, **MHZ},
    "if_bandwidth_hz": {"min": 4, "max": 28, "step": 0.5, **MHZ},
    "video_bandwidth_hz": {"min": 0.5, "max": 7, "step": 0.1, **MHZ},
    "carrier_offset_hz": {"min": -6, "max": 6, "step": 0.05, **MHZ},
}

RANGE: dict[str, Control] = {
    "distance_m": {
        "default": 500.0, "min": 10, "max": 20000, "step": 1, "unit": "m", "log": True,
        "doc": "From the transmitter, over free space.",
    },
    "tx_mw": {
        "min": 1, "max": 2000, "step": 1, "unit": "mW", "log": True,
        "doc": "The video transmitter's power.",
    },
    "tx_gain_dbi": {"min": -5, "max": 15, "step": 0.5, "unit": "dBi", "doc": "Its antenna."},
    "rx_gain_dbi": {"min": -5, "max": 15, "step": 0.5, "unit": "dBi", "doc": "The goggles'."},
    "frequency_hz": {"min": 0.9, "max": 6, "step": 0.01, "scale": 1e-9, "unit": "GHz"},
    "noise_figure_db": {"min": 0, "max": 15, "step": 0.5, "unit": "dB",
                        "doc": "The receiver's noise figure."},
    "extra_loss_db": {"min": 0, "max": 40, "step": 0.5, "unit": "dB",
                      "doc": "Bodies, trees, buildings, a bad antenna."},
}  # fmt: skip

ECHO: dict[str, Control] = {
    "delay_s": {"min": 0, "max": 300, "step": 1, **NS},
    "level_db": {"min": -30, "max": 3, "step": 0.5, "unit": "dB"},
    "phase_deg": {"min": 0, "max": 360, "step": 1, "unit": "°"},
    "doppler_hz": {"min": -400, "max": 400, "step": 1, "unit": "Hz"},
}

INDOOR: dict[str, Control] = {
    "k_db": {"min": -10, "max": 20, "step": 0.5, "unit": "dB",
             "doc": "Rician K: the direct path over all the echoes together."},
    "delay_spread_s": {"min": 5, "max": 100, "step": 1, **NS},
    "speed_ms": {"min": 0, "max": 20, "step": 0.5, "unit": "m/s"},
    "count": {"min": 1, "max": 12, "step": 1},
    "seed": {"default": 0, "min": 0, "max": 999, "step": 1, "doc": "The channel's draw."},
}  # fmt: skip

SYNC = "Sync and flywheel"
VERTICAL = "Vertical"
YC = "Luma and chroma"
COLOUR = "Colour and the colour killer"
LEVELS = "Levels"
LOSS = "Signal loss"

DECODER: dict[str, Control] = {
    "sync_bandwidth_hz": {"group": SYNC, "min": 0.1, "max": 5, "step": 0.05, **MHZ},
    "sync_slice_ire": {"group": SYNC, "min": -40, "max": 10, "step": 1, "unit": "IRE"},
    "h_window": {"group": SYNC, "min": 2, "max": 200, "step": 1, "unit": "samples"},
    "h_phase_gain": {"group": SYNC, "min": 0, "max": 1, "step": 0.01},
    "h_freq_gain": {"group": SYNC, "min": 0, "max": 0.1, "step": 0.001},
    "h_search_after": {"group": SYNC, "min": 1, "max": 100, "step": 1, "unit": "lines"},
    "h_lock_smoothing": {"group": SYNC, "min": 0.001, "max": 1, "step": 0.001, "log": True},
    "v_accept_after": {"group": VERTICAL, "min": 100, "max": 262, "step": 1, "unit": "lines"},
    "v_free_lines": {"group": VERTICAL, "min": 240, "max": 330, "step": 1, "unit": "lines"},
    "yc": {"group": YC},
    "luma_bandwidth_hz": {"group": YC, "min": 0.5, "max": 6, "step": 0.05, **MHZ},
    "chroma_bandwidth_hz": {"group": YC, "min": 0.2, "max": 2.5, "step": 0.05, **MHZ},
    "chroma_lowpass_hz": {"group": YC, "min": 0.1, "max": 2, "step": 0.05, **MHZ},
    "burst_smoothing": {"group": COLOUR, "min": 0.001, "max": 1, "step": 0.001, "log": True},
    "acc_max_gain": {"group": COLOUR, "min": 1, "max": 10, "step": 0.1},
    "lock_smoothing": {"group": COLOUR, "min": 0.001, "max": 1, "step": 0.001, "log": True},
    "killer_off": {"group": COLOUR, "min": 0, "max": 1, "step": 0.01},
    "killer_on": {"group": COLOUR, "min": 0, "max": 1, "step": 0.01},
    "killer_snr_off": {"group": COLOUR, "min": 0, "max": 6, "step": 0.05},
    "killer_snr_on": {"group": COLOUR, "min": 0, "max": 6, "step": 0.05},
    "clamp_smoothing": {"group": LEVELS, "min": 0.01, "max": 1, "step": 0.01, "log": True},
    "agc_smoothing": {"group": LEVELS, "min": 0.001, "max": 1, "step": 0.001, "log": True},
    "agc_range": {
        "group": LEVELS,
        "parts": [
            {"label": "least", "min": 0.05, "max": 1, "step": 0.01},
            {"label": "most", "min": 1, "max": 20, "step": 0.1},
        ],
    },
    "lost_below": {"group": LOSS, "min": 0, "max": 1, "step": 0.01},
    "on_loss": {"group": LOSS},
}

DVR: dict[str, Control] = {
    "quality": {"min": 1, "max": 95, "step": 1},
    "one_field": {},
    "size": {
        "parts": [
            {"label": "width", "min": 160, "max": 1920, "step": 1},
            {"label": "height", "min": 120, "max": 1080, "step": 1},
        ]
    },
}

MOVING = (Echo(30e-9, -1, 0, doppler_hz=90), Echo(80e-9, -4, 90, doppler_hz=-60))
PRESETS: list[tuple[str, str, dict[str, Any]]] = [
    ("Clean", "30 dB: soft, dot crawl", {}),
    ("Grain", "12 dB: grain, colour noise", {"link": {"cnr_db": 12}, "seed": 1}),
    ("Sparklies", "7 dB, near the FM threshold", {"link": {"cnr_db": 7}, "seed": 2}),
    ("Colour killer", "5 dB: black and white", {"link": {"cnr_db": 5}, "seed": 3}),
    ("Tearing", "3 dB: syncs lost, lines torn", {"link": {"cnr_db": 3}, "seed": 4}),
    ("Snow", "-8 dB: no signal", {"link": {"cnr_db": -8}, "seed": 5}),
    (
        "Multipath: hue",
        "An echo 40 ns late, 1 dB down: hue moves with brightness",
        {"echoes": [asdict(Echo(40e-9, -1, 170))], "seed": 6},
    ),
    (
        "Multipath: moving",
        "A blocked direct path and two walls, flying at 4 m/s: bands",
        {"link": {"cnr_db": 20}, "echoes": [asdict(e) for e in MOVING], "seed": 7},
    ),
    (
        "HDZero monitor",
        "Comb decoder, its HDMI into a capture card",
        {"decoder": {"yc": "comb"}, "dvr": asdict(Dvr.hdmi_capture())},
    ),
    ("Goggles DVR", "One field, 640 x 480, JPEG at 50", {"dvr": asdict(Dvr())}),
]
"""The tiles of docs/effects.jpg (scripts/effects.py), and two ways of seeing it."""

UPLOAD_WIDTH = 1280
"""Pictures sent from the page are scaled down to this: the link carries far less."""


def field_docs(cls: type) -> dict[str, str]:
    """The docstring under each field of a dataclass."""
    body = ast.parse(inspect.getsource(cls)).body[0]
    assert isinstance(body, ast.ClassDef)
    docs: dict[str, str] = {}
    for a, b in zip(body.body, body.body[1:], strict=False):
        if (
            isinstance(a, ast.AnnAssign)
            and isinstance(a.target, ast.Name)
            and isinstance(b, ast.Expr)
            and isinstance(b.value, ast.Constant)
            and isinstance(b.value.value, str)
        ):
            docs[a.target.id] = inspect.cleandoc(b.value.value)
    return docs


def dataclass_controls(cls: type, hints: dict[str, Control]) -> list[Control]:
    docs = field_docs(cls)
    out = []
    for f in fields(cls):
        if f.name in hints:
            default = None if f.default is MISSING else f.default
            c = {"name": f.name, "default": default, "doc": docs.get(f.name, ""), **hints[f.name]}
            if get_origin(f.type) is Literal:
                c["choices"] = list(get_args(f.type))
            out.append(c)
    return out


def function_controls(fn: Any, hints: dict[str, Control]) -> list[Control]:  # noqa: ANN401
    params = inspect.signature(fn).parameters
    return [
        {"name": name, "default": _default(params[name]), "doc": "", **hint}
        for name, hint in hints.items()
        if name in params
    ] + [{"name": name, **hint} for name, hint in hints.items() if name not in params]


def _default(param: inspect.Parameter) -> object:
    return None if param.default is inspect.Parameter.empty else param.default


def schema(pictures: list[dict[str, str]], python: bool = True) -> dict[str, Any]:
    """Everything the page builds its controls from. `pictures`: each one's name and URL;
    `python`: whether this server renders the Python's picture (not a static export)."""
    return {
        "pictures": pictures,
        "python": python,
        "controls": {
            "run": [{"name": k, **v} for k, v in RUN.items()],
            "link": dataclass_controls(Link, LINK),
            "range": function_controls(link_cnr_db, RANGE),
            "echo": dataclass_controls(Echo, ECHO),
            "indoor": function_controls(indoor_echoes, INDOOR),
            "decoder": dataclass_controls(Decoder, DECODER),
            "dvr": dataclass_controls(Dvr, DVR),
        },
        "docs": {
            "link": inspect.getdoc(Link),
            "range": inspect.getdoc(link_cnr_db),
            "echo": inspect.getdoc(Echo),
            "indoor": inspect.getdoc(indoor_echoes),
            "decoder": inspect.getdoc(Decoder),
            "dvr": inspect.getdoc(Dvr),
        },
        "presets": [{"name": n, "note": note, "state": s} for n, note, s in PRESETS],
    }


def build[T](cls: type[T], values: dict[str, Any], **extra: Any) -> T:  # noqa: ANN401
    """`cls` from the page's values for its fields, each as the type of its default (a float
    without one)."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):  # pyright: ignore[reportArgumentType]
        if f.name not in values or f.name in extra:
            continue
        value, default = values[f.name], f.default
        if default is MISSING:
            value = float(value)
        elif isinstance(default, tuple):
            value = tuple(type(d)(v) for d, v in zip(default, value, strict=True))
        elif isinstance(default, int) and not isinstance(default, bool):
            value = round(value)
        elif isinstance(default, str) and value not in get_args(f.type):
            raise ValueError(f"{f.name} {value!r}: one of {get_args(f.type)}")
        else:
            value = type(default)(value)
        kwargs[f.name] = value
    return cls(**kwargs, **extra)


def render(state: dict[str, Any], image: NDArray[np.uint8]) -> tuple[NDArray[np.uint8], dict]:
    """`image` through the link, decoder and recorder `state` sets out, as the page sends it;
    and how the signal was."""
    echoes = tuple(build(Echo, e) for e in state.get("echoes", []))
    link = build(Link, state.get("link", {}), multipath=echoes)
    if state.get("range"):
        params = inspect.signature(link_cnr_db).parameters
        r = {k: float(v) for k, v in state["range"].items() if k in params}
        link = replace(link, cnr_db=link_cnr_db(**r, if_bandwidth_hz=link.if_bandwidth_hz))
    sim = AnalogVideo(
        link,
        build(Decoder, state.get("decoder", {})),
        seed=int(state.get("seed", 0)),
        deinterlace=state.get("deinterlace", "weave"),
        dvr=build(Dvr, state["dvr"]) if state.get("dvr") else None,
    )
    rgb = to_float(image)
    for _ in range(max(1, min(int(state.get("frames", 4)), 30)) - 1):
        sim.show(rgb)
    shown = sim.show(rgb)
    return shown.image, {"cnr_db": link.cnr_db, "synced": shown.synced, "colour": shown.colour}


def _render_timed(
    state: dict[str, Any], image: NDArray[np.uint8]
) -> tuple[NDArray[np.uint8], dict]:
    start = time.perf_counter()
    out, info = render(state, image)
    return out, {**info, "seconds": time.perf_counter() - start}


def picture_bytes(image: NDArray[np.uint8], fmt: str = "png", width: int | None = None) -> bytes:
    img = Image.fromarray(image)
    if width and width < img.width:
        img = img.resize((width, round(img.height * width / img.width)), Image.Resampling.LANCZOS)
    buf = io.BytesIO()
    if fmt == "jpeg":
        img.save(buf, "JPEG", quality=90)
    else:
        img.save(buf, "PNG", compress_level=1)
    return buf.getvalue()


class Pictures:
    """What can go through the link: colour bars, files, and pictures sent from the page."""

    def __init__(self, paths: list[Path], root: Path) -> None:
        self._files: dict[str, Path] = {}
        for p in paths:
            p = p.resolve()
            self._files[str(p.relative_to(root)) if p.is_relative_to(root) else p.name] = p
        self._loaded: dict[str, NDArray[np.uint8]] = {
            "bars": (colour_bars() * 255 + 0.5).astype(np.uint8)
        }
        self._names = ["bars", *self._files]
        self._lock = threading.Lock()

    def names(self) -> list[str]:
        return list(self._names)

    def entries(self) -> list[dict[str, str]]:
        """Each picture's name and where the page gets it."""
        return [{"name": n, "url": f"api/picture?name={quote(n)}"} for n in self._names]

    def __getitem__(self, name: str) -> NDArray[np.uint8]:
        with self._lock:
            if name not in self._loaded:
                if name not in self._files:
                    raise KeyError(f"no picture {name!r}")
                img = Image.open(self._files[name]).convert("RGB")
                self._loaded[name] = np.asarray(img)
            return self._loaded[name]

    def add(self, filename: str, data: bytes) -> str:
        img = Image.open(io.BytesIO(data)).convert("RGB")
        if img.width > UPLOAD_WIDTH:
            height = round(img.height * UPLOAD_WIDTH / img.width)
            img = img.resize((UPLOAD_WIDTH, height), Image.Resampling.LANCZOS)
        with self._lock:
            name, n = f"upload/{Path(filename).name}", 1
            while name in self._loaded:
                n += 1
                name = f"upload/{n}-{Path(filename).name}"
            self._loaded[name] = np.asarray(img)
            self._names.append(name)
        return name


def find_pictures(root: Path) -> list[Path]:
    return sorted(
        p for p in (root / "reference").rglob("*") if p.suffix.lower() in {".png", ".jpg", ".jpeg"}
    )


def web_file(name: str) -> bytes:
    return resources.files("analog_vision").joinpath("web", name).read_bytes()


WEB_FILES = {
    "index.html": "text/html; charset=utf-8",
    "analog.js": "text/javascript",
    "favicon.svg": "image/svg+xml",
    "icon.png": "image/png",
    "social.jpg": "image/jpeg",
}


def handler(pictures: Pictures, pool: ProcessPoolExecutor) -> type[BaseHTTPRequestHandler]:

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: Any) -> None:  # noqa: ANN401
            pass

        def do_GET(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            query = parse_qs(url.query)
            try:
                name = url.path.lstrip("/") or "index.html"
                if name in WEB_FILES:
                    self._send(web_file(name), WEB_FILES[name])
                elif url.path == "/api/schema":
                    self._json(schema(pictures.entries()))
                elif url.path == "/api/picture":
                    self._send(picture_bytes(pictures[query["name"][0]]), "image/png")
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 400)

        def do_POST(self) -> None:  # noqa: N802
            url = urlparse(self.path)
            body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            try:
                if url.path == "/api/render":
                    state = json.loads(body)
                    job = pool.submit(_render_timed, state, pictures[state["picture"]])
                    out, info = job.result()
                    fmt = "jpeg" if state.get("format") == "jpeg" else "png"
                    data = picture_bytes(out, fmt, state.get("width"))
                    self._send(data, f"image/{fmt}", {"X-Info": json.dumps(info)})
                elif url.path == "/api/upload":
                    name = pictures.add(parse_qs(url.query)["name"][0], body)
                    self._json({"name": name, "pictures": pictures.entries()})
                else:
                    self._json({"error": "not found"}, 404)
            except Exception as e:
                self._json({"error": f"{type(e).__name__}: {e}"}, 400)

        def _json(self, value: object, status: int = 200) -> None:
            self._send(json.dumps(value).encode(), "application/json", status=status)

        def _send(
            self,
            data: bytes,
            content_type: str,
            headers: dict[str, str] | None = None,
            status: int = 200,
        ) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            for k, v in (headers or {}).items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

    return Handler


def serve(
    paths: list[Path], host: str = "127.0.0.1", port: int = 8000, browser: bool = True
) -> None:
    root = Path.cwd().resolve()
    pictures = Pictures(paths or find_pictures(root), root)
    workers = max(1, min(12, (os.cpu_count() or 2) - 1))
    with ProcessPoolExecutor(workers) as pool:
        server = ThreadingHTTPServer((host, port), handler(pictures, pool))
        url = f"http://{host}:{server.server_address[1]}/"
        print(
            f"{url}  ({len(pictures.names())} pictures, {workers} workers; Ctrl-C to stop)",
            flush=True,
        )
        if browser:
            webbrowser.open(url)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()


def export(paths: list[Path], out: Path) -> None:
    """The page as static files in `out`, with colour bars and `paths` (default: our own lab
    captures, which we may share; never reference/web's) as its pictures. Without this
    server it has no Python picture to compare with; the rest works as served."""
    root = Path.cwd().resolve()
    paths = paths or sorted((root / "reference/lab").glob("*.jpeg"))
    (out / "pictures").mkdir(parents=True, exist_ok=True)
    (out / "api").mkdir(exist_ok=True)
    for name in WEB_FILES:
        (out / name).write_bytes(web_file(name))
    entries = [{"name": "bars", "url": "pictures/bars.png"}]
    Image.fromarray((colour_bars() * 255 + 0.5).astype(np.uint8)).save(out / "pictures/bars.png")
    for p in paths:
        file = f"pictures/{p.name}"
        (out / file).write_bytes(p.read_bytes())
        name = str(p.resolve().relative_to(root)) if p.resolve().is_relative_to(root) else p.name
        entries.append({"name": name, "url": file})
    (out / "api/schema").write_text(json.dumps(schema(entries, python=False)))
    print(f"{out}: {len(entries)} pictures")
