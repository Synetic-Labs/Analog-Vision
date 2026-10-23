"""Linear-phase FIR filters, run over a signal that arrives a chunk at a time."""

from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy import signal

KAISER_BETA = 6.0
"""About 60 dB of stopband: below anything the picture shows."""


_WINDOW: Any = ("kaiser", KAISER_BETA)


def lowpass(taps: int, cutoff_hz: float, fs: float) -> NDArray[np.float64]:
    return np.asarray(signal.firwin(taps, cutoff_hz, fs=fs, window=_WINDOW), dtype=np.float64)


def bandpass(taps: int, low_hz: float, high_hz: float, fs: float) -> NDArray[np.float64]:
    h = signal.firwin(taps, [low_hz, high_hz], pass_zero=False, fs=fs, window=_WINDOW)
    return np.asarray(h, dtype=np.float64)


def smoothing(taps: int) -> NDArray[np.float64]:
    """A raised-cosine pulse of `taps` samples, summing to 1: a signal's edges, rounded."""
    w = np.hanning(taps + 2)[1:-1]
    return w / w.sum()


class StreamFir:
    """An FIR filter applied to consecutive chunks of one signal as if to the whole: each
    chunk out is as long as the chunk in, and output n is input n - delay, filtered."""

    def __init__(self, taps: NDArray[np.float64]) -> None:
        if len(taps) % 2 == 0:
            raise ValueError("odd length only: a whole-sample delay")
        self.taps = taps
        self.delay = (len(taps) - 1) // 2
        self._tail: NDArray[np.generic] | None = None

    def __call__[T: np.generic](self, x: NDArray[T]) -> NDArray[T]:
        if self._tail is None:
            self._tail = np.zeros(len(self.taps) - 1, dtype=x.dtype)
        buf = np.concatenate([self._tail, x])
        self._tail = buf[len(buf) - (len(self.taps) - 1) :]
        return signal.oaconvolve(buf, self.taps, mode="valid").astype(x.dtype, copy=False)
