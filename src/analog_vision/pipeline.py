"""Pictures through the whole chain: camera, radio link, goggles.

    sim = AnalogVideo(Link(cnr_db=9), seed=1)
    for frame in frames:
        shown = sim(frame)          # what the goggles show, same size as `frame`

    degrade(image, cnr_db=9)       # one picture, on its own

Frames go in at the video's frame rate (29.97 a second): each is one frame of composite, its
two fields both from it. Out comes the latest two fields woven together (or, deinterlace
"bob", the latest field line-doubled), scaled to the size asked for, as the goggles' screen
would show it. A frame shown is the field before and the field just finished.

With a `Dvr`, it is what the goggles' recorder keeps instead: as most do, one field of each
frame, line-doubled, scaled to 640 x 480 and compressed (JPEG frames, as MJPEG recorders
store them). Its compression smooths the fine noise into blotches and smears it sideways.
"""

import io
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from analog_vision import ntsc
from analog_vision.decode import Decoder, Field, VideoDecoder
from analog_vision.encode import encode, resize, rgb_from_yuv, to_float
from analog_vision.fm import FmLink, Link


@dataclass(frozen=True)
class Dvr:
    """A goggles' video recorder."""

    quality: int = 50
    """JPEG quality, 1 to 95: low-bitrate DVRs are 30 to 60."""
    one_field: bool = True
    """Keep one field of each frame, line-doubled, as most DVRs do."""
    size: tuple[int, int] = (640, 480)
    """What it records at."""

    @classmethod
    def hdmi_capture(cls) -> "Dvr":
        """A monitor's HDMI out into a capture card (an HDZero monitor into an Elgato): both
        fields deinterlaced, upscaled to 720p, lightly compressed."""
        return cls(quality=90, one_field=False, size=(960, 720))

    def record(self, rgb: NDArray[np.float64]) -> NDArray[np.float64]:
        """`rgb` (480 x 754, 0 to 1) as the recording has it, at `size`."""
        w, h = self.size
        planes = [resize(rgb[..., c], w, h) for c in range(3)]
        img = Image.fromarray((np.clip(np.stack(planes, -1), 0, 1) * 255 + 0.5).astype(np.uint8))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=self.quality, subsampling=2)
        buf.seek(0)
        return np.asarray(Image.open(buf).convert("RGB"), dtype=np.float64) / 255.0


@dataclass(frozen=True)
class Shown:
    """A picture as the goggles show it, and how the signal behind it was."""

    image: NDArray[np.uint8]
    synced: float
    """The share of its lines with a horizontal sync: 1 locked, near 0 lost."""
    colour: float
    """The share of its lines in colour: 0 once the colour killer is on."""


@dataclass
class AnalogVideo:
    """One camera, link and receiver, carrying a stream of frames."""

    link: Link = field(default_factory=Link)
    decoder: Decoder = field(default_factory=Decoder)
    seed: int | None = None
    deinterlace: Literal["weave", "bob"] = "weave"
    size: tuple[int, int] | None = None
    """Output (width, height); None: the size of each frame in."""
    dvr: Dvr | None = None
    """Show what the goggles' recorder keeps rather than their screen."""

    def __post_init__(self) -> None:
        self._rng = np.random.default_rng(self.seed)
        self._fm = FmLink(self.link, self._rng)
        self._dec = VideoDecoder(self.decoder)
        self._n = 0
        self._fields: dict[int, Field] = {}
        self._last: Field | None = None

    def set_link(self, link: Link) -> None:
        """Change the link's conditions from the next frame (a drone flying away), keeping
        the decoder's lock and the signal's continuity."""

        def shape(k: Link) -> tuple[object, ...]:
            return (k.if_bandwidth_hz, k.video_bandwidth_hz, k.multipath)

        if shape(link) != shape(self.link):
            self._fm = FmLink(link, self._rng)
        else:
            self._fm.link = link
        self.link = link

    def __call__(self, frame: NDArray[np.generic]) -> NDArray[np.uint8]:
        return self.show(frame).image

    def show(self, frame: NDArray[np.generic]) -> Shown:
        composite = encode(frame, self._n)
        self._n += len(composite)
        for f in self._dec(self._fm(composite)):
            self._fields[f.parity] = f
            self._last = f
        height, width = frame.shape[:2]
        if self.size:
            width, height = self.size
        return self._picture(width, height)

    def _picture(self, width: int, height: int) -> Shown:
        last = self._last
        if last is None:
            return Shown(np.zeros((height, width, 3), np.uint8), 0.0, 0.0)
        if self.deinterlace == "bob" or len(self._fields) < 2 or (self.dvr and self.dvr.one_field):
            planes = [np.repeat(getattr(last, c), 2, axis=0) for c in "yuv"]
            used = [last]
        else:
            used = [self._fields[2], self._fields[1]]
            planes = []
            for c in "yuv":
                woven = np.empty((ntsc.ACTIVE_LINES, ntsc.ACTIVE))
                woven[0::2] = getattr(self._fields[2], c)
                woven[1::2] = getattr(self._fields[1], c)
                planes.append(woven)
        rgb = np.clip(rgb_from_yuv(*planes), 0.0, 1.0)
        if self.dvr:
            rgb = self.dvr.record(rgb)
        out = np.stack([resize(rgb[..., c], width, height) for c in range(3)], axis=-1)
        image = (np.clip(out, 0.0, 1.0) * 255 + 0.5).astype(np.uint8)
        return Shown(
            image,
            float(np.mean([f.synced for f in used])),
            float(np.mean([f.colour for f in used])),
        )


def degrade(
    image: NDArray[np.generic],
    cnr_db: float = 30.0,
    seed: int | None = None,
    link: Link | None = None,
    decoder: Decoder | None = None,
    deinterlace: Literal["weave", "bob"] = "weave",
    dvr: Dvr | None = None,
) -> NDArray[np.uint8]:
    """`image` as analog goggles would show it over a link at `cnr_db` (or `link`): the
    same size, 8-bit RGB. The decoder locks on a first frame, then shows the second."""
    sim = AnalogVideo(
        link or Link(cnr_db=cnr_db),
        decoder or Decoder(),
        seed=seed,
        deinterlace=deinterlace,
        dvr=dvr,
    )
    rgb = to_float(image)
    sim(rgb)
    return sim(rgb)
