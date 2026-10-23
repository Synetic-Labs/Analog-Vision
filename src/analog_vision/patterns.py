"""Test pictures."""

import numpy as np
from numpy.typing import NDArray

BARS_75 = [
    (0.75, 0.75, 0.75),
    (0.75, 0.75, 0.0),
    (0.0, 0.75, 0.75),
    (0.0, 0.75, 0.0),
    (0.75, 0.0, 0.75),
    (0.75, 0.0, 0.0),
    (0.0, 0.0, 0.75),
]
"""SMPTE's 75 % colour bars: grey, yellow, cyan, green, magenta, red, blue."""


def colour_bars(width: int = 640, height: int = 480) -> NDArray[np.float64]:
    """Seven 75 % bars over the top two thirds; under them a white-to-black ramp and a
    resolution sweep (0.5 to 5 MHz across, as NTSC carries it)."""
    out = np.zeros((height, width, 3))
    edges = np.linspace(0, width, len(BARS_75) + 1).round().astype(int)
    top = height * 2 // 3
    for (a, b), colour in zip(zip(edges[:-1], edges[1:], strict=True), BARS_75, strict=True):
        out[:top, a:b] = colour
    mid = top + (height - top) // 2
    out[top:mid] = np.linspace(1.0, 0.0, width)[None, :, None]
    # A chirp whose frequency climbs from 0.5 to 5 MHz over the 52.7 us of a line.
    t = np.linspace(0, 52.66e-6, width)
    f0, f1 = 0.5e6, 5e6
    phase = 2 * np.pi * (f0 * t + (f1 - f0) * t**2 / (2 * t[-1]))
    out[mid:] = (0.5 + 0.5 * np.sin(phase))[None, :, None]
    return out
