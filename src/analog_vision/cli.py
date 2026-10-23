"""analog-vision: pictures through a simulated analog FPV link.

analog-vision apply in.png out.png --cnr 9
analog-vision apply in.png out.png --distance 1200 --tx-mw 25
analog-vision sweep in.png sweep.png --cnr 30,15,11,9,7,5
analog-vision sweep in.png sweep.png --cnr 22,16 --indoor 0 --speed 5
analog-vision fly in.png frames/ --from 200 --to 3000 --frames 120
"""

import argparse
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image, ImageDraw

from analog_vision.decode import Decoder
from analog_vision.fm import Echo, Link, indoor_echoes, link_cnr_db
from analog_vision.patterns import colour_bars
from analog_vision.pipeline import AnalogVideo, Dvr, degrade


def load(path: str) -> NDArray[np.uint8]:
    if path == "bars":
        return (colour_bars() * 255 + 0.5).astype(np.uint8)
    return np.asarray(Image.open(path).convert("RGB"))


def _cnr(args: argparse.Namespace, distance: float | None = None) -> float:
    distance = distance if distance is not None else args.distance
    if distance is None:
        return args.cnr
    return link_cnr_db(distance, tx_mw=args.tx_mw, extra_loss_db=args.loss)


def _decoder(args: argparse.Namespace) -> Decoder:
    return Decoder(yc=args.yc, on_loss=args.on_loss)


def _echoes(args: argparse.Namespace) -> tuple[Echo, ...]:
    if args.indoor is None:
        return ()
    rng = np.random.default_rng(args.seed)
    return indoor_echoes(rng, k_db=args.indoor, speed_ms=args.speed, count=3)


def _link(args: argparse.Namespace, cnr: float) -> Link:
    return Link(cnr_db=cnr, multipath=_echoes(args))


def _dvr(args: argparse.Namespace) -> Dvr | None:
    if args.capture:
        return Dvr.hdmi_capture()
    return Dvr(quality=args.dvr) if args.dvr else None


def cmd_apply(args: argparse.Namespace) -> None:
    cnr = _cnr(args)
    out = degrade(
        load(args.input),
        link=_link(args, cnr),
        seed=args.seed,
        decoder=_decoder(args),
        dvr=_dvr(args),
    )
    Image.fromarray(out).save(args.output)
    print(f"{args.output}: CNR {cnr:.1f} dB")


def cmd_sweep(args: argparse.Namespace) -> None:
    image = load(args.input)
    levels = [float(c) for c in args.cnr_list.split(",")]
    tiles = []
    for cnr in levels:
        out = degrade(
            image, link=_link(args, cnr), seed=args.seed, decoder=_decoder(args), dvr=_dvr(args)
        )
        tile = Image.fromarray(out)
        draw = ImageDraw.Draw(tile)
        draw.rectangle((0, 0, 150, 22), fill=(0, 0, 0))
        draw.text((6, 5), f"CNR {cnr:g} dB", fill=(255, 255, 255))
        tiles.append(tile)
    w, h = tiles[0].size
    cols = min(args.columns, len(tiles))
    rows = -(-len(tiles) // cols)
    sheet = Image.new("RGB", (cols * w, rows * h))
    for i, tile in enumerate(tiles):
        sheet.paste(tile, ((i % cols) * w, (i // cols) * h))
    sheet.save(args.output)
    print(f"{args.output}: {len(tiles)} levels")


def cmd_fly(args: argparse.Namespace) -> None:
    """A still, flown away from: the link fades frame by frame, the decoder carrying on."""
    image = load(args.input)
    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    sim = AnalogVideo(
        _link(args, _cnr(args, args.start)), _decoder(args), seed=args.seed, dvr=_dvr(args)
    )
    for i, d in enumerate(np.linspace(args.start, args.end, args.frames)):
        sim.set_link(_link(args, _cnr(args, float(d))))
        shown = sim.show(image)
        Image.fromarray(shown.image).save(out / f"{i:04d}.png")
        print(f"{i:4d}  {d:7.0f} m  CNR {sim.link.cnr_db:5.1f} dB  sync {shown.synced:.2f}")


def main() -> None:
    summary = (__doc__ or "").split("\n")[0]
    parser = argparse.ArgumentParser(prog="analog-vision", description=summary)
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("input", help="a picture, or 'bars' for colour bars")
        p.add_argument("output")
        p.add_argument("--seed", type=int, default=None)
        p.add_argument("--tx-mw", type=float, default=25.0, help="with --distance")
        p.add_argument("--loss", type=float, default=0.0, help="extra path loss, dB")
        p.add_argument("--on-loss", choices=["snow", "blue", "black"], default="snow")
        p.add_argument(
            "--dvr", type=int, default=0, metavar="QUALITY", help="as the DVR records it"
        )
        p.add_argument(
            "--indoor",
            type=float,
            default=None,
            metavar="K_DB",
            help="indoor multipath: the direct path this far above the echoes (Rician K)",
        )
        p.add_argument("--speed", type=float, default=3.0, help="with --indoor: m/s")
        p.add_argument(
            "--yc", choices=["notch", "comb"], default="notch", help="comb: an HDZero monitor"
        )
        p.add_argument("--capture", action="store_true", help="as an HDMI capture card records it")

    p = sub.add_parser("apply", help="one picture through the link")
    common(p)
    p.add_argument("--cnr", type=float, default=30.0, help="carrier to noise, dB")
    p.add_argument("--distance", type=float, default=None, help="metres: CNR from the range")
    p.set_defaults(func=cmd_apply)

    p = sub.add_parser("sweep", help="one picture at several CNRs, on one sheet")
    common(p)
    p.add_argument("--cnr", dest="cnr_list", default="30,15,12,10,9,8,7,6,5")
    p.add_argument("--columns", type=int, default=3)
    p.set_defaults(func=cmd_sweep, distance=None)

    p = sub.add_parser("fly", help="frames of a still as the link fades with range")
    common(p)
    p.add_argument("--from", dest="start", type=float, default=100.0, help="metres")
    p.add_argument("--to", dest="end", type=float, default=3000.0, help="metres")
    p.add_argument("--frames", type=int, default=90)
    p.set_defaults(func=cmd_fly, distance=0.0, cnr=0.0)

    args = parser.parse_args()
    args.func(args)
