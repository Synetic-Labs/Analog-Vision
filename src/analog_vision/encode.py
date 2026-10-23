"""A picture into NTSC composite video, as an analog camera sends it.

The camera's R'G'B' (gamma-encoded, as an 8-bit image already is) becomes luma Y' and the
colour differences U and V. Y' is band-limited to 4.2 MHz and U, V to 1.3 MHz, as consumer
encoders do (rather than broadcast's separate 1.3 and 0.4 MHz for I and Q). U and V
quadrature-modulate the 3.58 MHz subcarrier, which rides on the luma:

    composite = Y + U sin(wt) + V cos(wt)        burst = -20 IRE sin(wt)

with Y, U and V scaled from black (7.5 IRE) to white (100 IRE). Each frame's two fields both
come from the one picture, field 2 on the even rows (ntsc.FIRST_LINE).
"""

import numpy as np
from numpy.typing import NDArray
from PIL import Image
from scipy import ndimage

from analog_vision import ntsc
from analog_vision.dsp import lowpass, smoothing

LUMA_HZ = 4.2e6
CHROMA_HZ = 1.3e6
_Y_TAPS = lowpass(31, LUMA_HZ, ntsc.FS)
_C_TAPS = lowpass(41, CHROMA_HZ, ntsc.FS)
_EDGE = smoothing(3)
"""Sync and blanking edges rise in about 140 ns, as SMPTE 170M has them."""


def to_float(image: NDArray[np.generic]) -> NDArray[np.float64]:
    """An H x W x 3 picture, 8-bit or 0 to 1, as 0 to 1 floats."""
    if image.ndim == 2:
        image = np.repeat(image[..., None], 3, axis=2)
    image = image[..., :3]
    if np.issubdtype(image.dtype, np.integer):
        return image.astype(np.float64) / 255.0
    return np.clip(image.astype(np.float64), 0.0, 1.0)


def resize(plane: NDArray[np.float64], width: int, height: int) -> NDArray[np.float64]:
    """One channel to `width` x `height`, filtered as it scales (Lanczos)."""
    if plane.shape == (height, width):
        return plane
    img = Image.fromarray(plane.astype(np.float32), mode="F")
    return np.asarray(img.resize((width, height), Image.Resampling.LANCZOS), dtype=np.float64)


def raster(image: NDArray[np.generic]) -> NDArray[np.float64]:
    """The picture as the camera scans it: 480 lines of 754 samples, R'G'B' 0 to 1."""
    rgb = to_float(image)
    planes = [resize(rgb[..., c], ntsc.ACTIVE, ntsc.ACTIVE_LINES) for c in range(3)]
    return np.clip(np.stack(planes, axis=-1), 0.0, 1.0)


def yuv(rgb: NDArray[np.float64]) -> tuple[NDArray[np.float64], ...]:
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    y = 0.299 * r + 0.587 * g + 0.114 * b
    return y, 0.492111 * (b - y), 0.877283 * (r - y)


def rgb_from_yuv(
    y: NDArray[np.float64], u: NDArray[np.float64], v: NDArray[np.float64]
) -> NDArray[np.float64]:
    r = y + v / 0.877283
    b = y + u / 0.492111
    g = (y - 0.299 * r - 0.114 * b) / 0.587
    return np.stack([r, g, b], axis=-1)


def _sync_and_blanking() -> NDArray[np.float64]:
    """One frame of sync pulses on blanking, edges rounded, the subcarrier left out."""
    out = np.full(ntsc.FRAME, ntsc.BLANK)
    for h in range(2 * ntsc.LINES):
        pulse = ntsc.half_line(h).pulse
        start = h * ntsc.HALF
        out[start : start + pulse] = ntsc.SYNC
    # Round the edges, keeping each pulse's 50 % points where they are.
    return ndimage.convolve1d(out, _EDGE, mode="wrap")


_SYNC = _sync_and_blanking()
_BURST_ENVELOPE = np.convolve(np.ones(ntsc.BURST_LEN - 4), smoothing(5))
"""Nine cycles, rising and falling over about a cycle, as a burst gate does."""
_ACTIVE_ENVELOPE = np.convolve(np.ones(ntsc.ACTIVE - 2), _EDGE)


def subcarrier(start: int, n: int) -> tuple[NDArray[np.float64], NDArray[np.float64]]:
    """sin(wt) and cos(wt) for samples `start` to `start + n`: a quarter cycle a sample."""
    k = (start + np.arange(n)) % 4
    return np.array([0.0, 1.0, 0.0, -1.0])[k], np.array([1.0, 0.0, -1.0, 0.0])[k]


def encode(image: NDArray[np.generic], start: int = 0) -> NDArray[np.float64]:
    """One frame of composite video, IRE, from `image` (H x W x 3, 8-bit or 0 to 1).
    `start` is the frame's first sample in the whole signal: the subcarrier's phase runs on
    from frame to frame, a four-field sequence."""
    y, u, v = yuv(raster(image))
    y = ndimage.convolve1d(y, _Y_TAPS, axis=1, mode="nearest")
    u = ndimage.convolve1d(u, _C_TAPS, axis=1, mode="nearest")
    v = ndimage.convolve1d(v, _C_TAPS, axis=1, mode="nearest")
    span = ntsc.WHITE - ntsc.SETUP
    frame = _SYNC.copy().reshape(ntsc.LINES, ntsc.LINE)
    for line in range(1, ntsc.LINES + 1):
        at = (line - 1) * ntsc.LINE
        if ntsc.has_burst(line):
            b0 = ntsc.BURST_START
            sin, _ = subcarrier(start + at + b0, len(_BURST_ENVELOPE))
            frame[line - 1, b0 : b0 + len(sin)] -= ntsc.BURST * _BURST_ENVELOPE * sin
    for row in range(ntsc.ACTIVE_LINES):
        line = ntsc.picture_line(row)
        a0 = (line - 1) * ntsc.LINE + ntsc.ACTIVE_START
        sin, cos = subcarrier(start + a0, ntsc.ACTIVE)
        video = ntsc.SETUP + span * (y[row] + u[row] * sin + v[row] * cos)
        frame[line - 1, ntsc.ACTIVE_START : ntsc.ACTIVE_START + ntsc.ACTIVE] += (
            video * _ACTIVE_ENVELOPE
        )
    return frame.reshape(-1)
