"""Composite video back into pictures, as the video decoder in a pair of goggles does it.

Everything it knows it takes from the signal, as a real decoder must, so noise in the signal
reaches the picture the same way:

- Sync: the signal, low-passed, is sliced halfway down the sync pulses. A flywheel
  (phase-locked loop) follows the horizontal syncs from line to line and coasts through
  missing ones; noisy syncs jitter the lines sideways, a wrong one tears the picture.
  Vertical sync is the broad pulses, found by integrating the sliced signal; without it the
  vertical oscillator runs free, a little slow, and the picture rolls.
- Levels: each line is clamped to its own back porch (black level), and an AGC holds the
  sync's depth at 40 IRE.
- Colour: a band-pass at 3.58 MHz splits chroma from luma (a notch decoder: what is left
  of the subcarrier in the luma crawls as dots), and the luma is low-passed at 4.2 MHz. So
  luma runs to about 2.3 MHz: the softness of analog FPV, and noise in dashes, not dots.
  Or (yc "comb", as better decoders do) a comb filter: the line before, through a fixed one
  line delay, subtracted for the chroma and added for the luma, since the subcarrier turns
  over from line to line; where the colour changes from one line to the next it falls back
  to the notch (adaptive). Luma keeps its detail to 4.2 MHz, and chroma noise is shared by
  neighbouring lines: it streaks vertically.
  The burst, averaged over lines, sets the hue and the colour gain (ACC). A lock detector
  checks each burst against that reference, in step and across it; with too little burst in
  step, or too much jitter across (the burst's own signal to noise), the colour killer turns
  colour off for the next field, well before the picture goes. So does losing horizontal
  lock: the burst gate is timed from the syncs. The chroma is filtered to 0.6 MHz, as
  consumer decoders do: its noise comes out in coarse blotches.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray

from analog_vision import ntsc
from analog_vision.dsp import StreamFir, bandpass, lowpass


@dataclass(frozen=True)
class Decoder:
    """How the goggles' decoder behaves."""

    sync_bandwidth_hz: float = 1.5e6
    sync_slice_ire: float = -20.0
    h_window: int = 40
    """How far either side of where it expects a sync the flywheel looks, samples."""
    h_phase_gain: float = 0.3
    """How much of a sync's timing error the flywheel takes up each line."""
    h_freq_gain: float = 0.01
    h_search_after: int = 8
    """Lines without a sync before it searches the whole line."""
    v_accept_after: int = 230
    """Lines after a vertical retrace before it takes another vertical sync."""
    v_free_lines: int = 272
    """Lines the vertical oscillator runs to on its own (262.5 locked)."""
    yc: Literal["notch", "comb"] = "notch"
    """How chroma and luma are split: a notch (goggles) or an adaptive comb (the HDZero
    monitor and other better decoders)."""
    luma_bandwidth_hz: float = 4.2e6
    chroma_bandwidth_hz: float = 1.3e6
    """Half the width of the band-pass that takes the chroma (and notches the luma)."""
    chroma_lowpass_hz: float = 0.6e6
    """The demodulated U and V."""
    burst_smoothing: float = 0.1
    """How much of each line's burst goes into the colour reference."""
    lock_smoothing: float = 0.02
    """How much of each line goes into the lock detector: the burst in step with the
    reference before it, a few milliseconds' worth."""
    killer_off: float = 0.25
    """Burst in step, relative to its proper 20 IRE, below which colour turns off..."""
    killer_on: float = 0.35
    """...and above which it comes back."""
    killer_snr_off: float = 2.2
    """Burst in step over its jitter across (amplitude), below which colour turns off (about
    7 dB CNR with the default link; receivers differ, some keep colour lower)..."""
    killer_snr_on: float = 2.5
    """...and above which it comes back (about 8 dB)."""
    acc_max_gain: float = 4.0
    clamp_smoothing: float = 0.5
    agc_smoothing: float = 0.05
    """How much of each line's sync depth goes into the AGC (lines with a sync only)."""
    agc_range: tuple[float, float] = (0.25, 4.0)
    """The AGC's gain, least and most: 12 dB either way."""
    h_lock_smoothing: float = 0.05
    """How much of each line goes into the horizontal lock detector: a sync found or not."""
    lost_below: float = 0.5
    """A field with syncs on fewer of its lines than this has no signal."""
    on_loss: Literal["snow", "blue", "black"] = "snow"
    """What it shows with no signal: the noise, or a blue or black screen."""


def hdzero_monitor() -> Decoder:
    """The HDZero monitor's analog decoder: an adaptive comb, deinterlaced and upscaled to
    720p for its screen and HDMI (with `Dvr.hdmi_capture` for what a capture card records).
    Its chip is not published; the rest is the generic decoder."""
    return Decoder(yc="comb")


@dataclass
class Field:
    """One decoded field: 240 lines of 754 samples, Y' 0 to 1 at black to white, U and V."""

    parity: int
    """1 or 2: field 2 is the upper of the two on screen."""
    y: NDArray[np.float64] = field(repr=False)
    u: NDArray[np.float64] = field(repr=False)
    v: NDArray[np.float64] = field(repr=False)
    synced: float = 0.0
    """The share of its lines that had a horizontal sync."""
    colour: float = 0.0
    """The share of its lines decoded in colour."""


_VSYNC_WINDOW = 351
"""Integrator for vertical sync, samples (24.5 us): broad pulses fill it, others do not."""
_VSYNC_FILL = 0.6


class VideoDecoder:
    """Decodes one continuous composite signal, fed a chunk at a time."""

    def __init__(self, decoder: Decoder | None = None) -> None:
        decoder = decoder or Decoder()
        self.d = decoder
        self._sync = StreamFir(lowpass(41, decoder.sync_bandwidth_hz, ntsc.FS))
        self._bp = StreamFir(
            bandpass(
                41,
                ntsc.FSC - decoder.chroma_bandwidth_hz,
                ntsc.FSC + decoder.chroma_bandwidth_hz,
                ntsc.FS,
            )
        )
        self._demod = StreamFir(lowpass(61, decoder.chroma_lowpass_hz, ntsc.FS))
        self._luma = StreamFir(lowpass(31, decoder.luma_bandwidth_hz, ntsc.FS))
        # The burst is only nine cycles: it is read through a wider filter than the picture.
        self._burst_demod = StreamFir(lowpass(41, decoder.chroma_bandwidth_hz, ntsc.FS))
        self._vsync = StreamFir(np.full(_VSYNC_WINDOW, 1.0 / _VSYNC_WINDOW))
        if decoder.yc == "comb":
            self._comb = _Comb(self._bp.taps, decoder)
        else:
            self._comb = None
        db = self._bp.delay
        self._delay = {
            "sync": self._sync.delay,
            "y": db + self._luma.delay,
            "z": db + self._demod.delay,
            "zb": db + self._burst_demod.delay,
            "v": self._sync.delay + self._vsync.delay,
        }
        if self._comb:
            self._delay.update(self._comb.delays(db))
        # Every stream is indexed alike: sample i is at absolute position base + i, and holds
        # what the raw signal had `delay` samples earlier.
        self._base = -db
        self._raw = np.zeros(db)
        self._streams: dict[str, NDArray[Any]] = {
            "sync": np.zeros(db),
            "y": np.zeros(db),
            "z": np.zeros(db, dtype=np.complex128),
            "zb": np.zeros(db, dtype=np.complex128),
            "v": np.zeros(db),
        }
        if self._comb:
            for name in ("yc", "zc", "w"):
                self._streams[name] = np.zeros(db, dtype=np.complex128 if name == "zc" else None)
        self._n = 0
        """Absolute position of the next raw sample."""
        # Horizontal flywheel.
        self._p: float | None = None
        """Where the current line's sync is, absolute samples; None before the first."""
        self._period = float(ntsc.LINE)
        self._missed = 0
        self._h_lock = 1.0
        # Vertical.
        self._line_no = 0
        """The current line's number in the frame, as the decoder counts it."""
        self._since_retrace = decoder.v_accept_after
        self._field: Field | None = None
        self._synced_lines = 0
        self._colour_lines = 0
        # Levels and colour.
        self._clamp = 0.0
        self._agc: float | None = None
        self._burst = 1j * ntsc.BURST
        self._lock = ntsc.BURST
        self._burst_noise = 0.0
        """The burst's jitter across the reference: noise power, IRE squared."""
        self._colour = True
        """Colour on: the killer decides once a field, at the vertical retrace."""
        self._colour_ok = True
        self._colour_good = True

    def __call__(self, composite: NDArray[np.float64]) -> list[Field]:
        """Decode the next chunk of composite video (IRE at 4fsc); the fields completed."""
        self._append(composite)
        out: list[Field] = []
        if self._p is None:
            self._p = self._acquire()
            if self._p is None:
                return out
        margin = ntsc.LINE + 2 * ntsc.HALF + max(self._delay.values()) + 2
        while self._p + margin < self._base + len(self._raw):
            out.extend(self._line(self._p))
            self._p = self._next_sync(self._p)
        self._trim(int(self._p) - ntsc.LINE)
        return out

    # -- streams ---------------------------------------------------------------------

    def _append(self, x: NDArray[np.float64]) -> None:
        n = np.arange(self._n, self._n + len(x))
        self._n += len(x)
        self._raw = np.concatenate([self._raw, x])
        sync = self._sync(x)
        bp = self._bp(x)
        # Luma: the signal, delayed to match the band-pass, less the band-pass (a notch).
        db = self._bp.delay
        end = len(self._raw) - db
        y = self._luma(self._raw[end - len(x) : end] - bp)
        # Chroma to baseband against a free-running subcarrier: the burst sorts out its phase.
        k = (n - db) % 4
        baseband = bp * np.array([2, -2j, -2, 2j])[k]
        z = self._demod(baseband)
        zb = self._burst_demod(baseband)
        v = self._vsync((sync < self.d.sync_slice_ire).astype(np.float64))
        new = {"sync": sync, "y": y, "z": z, "zb": zb, "v": v}
        if self._comb:
            new.update(self._comb(x, self._raw[end - len(x) : end], bp, k))
        for name, part in new.items():
            self._streams[name] = np.concatenate([self._streams[name], part])

    def _trim(self, keep_from: int) -> None:
        cut = keep_from - self._base
        if cut <= 0:
            return
        self._raw = self._raw[cut:]
        for name in self._streams:
            self._streams[name] = self._streams[name][cut:]
        self._base += cut

    def _at(self, name: str, t: float, n: int) -> NDArray[Any]:
        """`n` samples of stream `name` from what the raw signal had at `t`, interpolated."""
        x = t + self._delay[name] - self._base
        i = math.floor(x)
        f = x - i
        s = self._streams[name]
        return s[i : i + n] * (1 - f) + s[i + 1 : i + n + 1] * f

    def _mean(self, name: str, t: float, span: tuple[int, int]) -> complex:
        return complex(np.mean(self._at(name, t + span[0], span[1] - span[0])))

    # -- horizontal ------------------------------------------------------------------

    def _crossings(self, start: float, n: int) -> list[float]:
        """Sync leading edges (falling through the slice) from `start` for `n` samples, kept
        when the signal stays down a while after (2.5 us): sync, not a noise spike."""
        seg = np.real(self._at("sync", math.floor(start), n + 48))
        level = self.d.sync_slice_ire
        k = np.nonzero((seg[:n] >= level) & (seg[1 : n + 1] < level))[0]
        out = []
        for i in k:
            if np.mean(seg[i + 6 : i + 41]) < level:
                frac = (seg[i] - level) / (seg[i] - seg[i + 1])
                out.append(math.floor(start) + i + frac)
        return out

    def _acquire(self) -> float | None:
        """The first sync in what has arrived, to start the flywheel from."""
        if len(self._raw) < 4 * ntsc.LINE:
            return None
        start = self._base + ntsc.HALF
        found = self._crossings(start, ntsc.LINE)
        return found[0] if found else float(start)

    def _next_sync(self, p: float) -> float:
        d = self.d
        expect = p + self._period
        w = ntsc.HALF + d.h_window if self._missed >= d.h_search_after else d.h_window
        found = self._crossings(expect - w, 2 * w)
        if not found:
            self._missed += 1
            return expect
        best = min(found, key=lambda t: abs(t - expect))
        err = best - expect
        self._missed = 0
        self._synced_lines += 1
        if w > d.h_window:  # searching: jump straight to it
            return best
        self._period = float(np.clip(self._period + d.h_freq_gain * err, 890, 930))
        return expect + d.h_phase_gain * err

    # -- a line ----------------------------------------------------------------------

    def _line(self, p: float) -> list[Field]:
        d = self.d
        out: list[Field] = []
        # Vertical: broad pulses in this line, and where.
        vs = np.real(self._at("v", p, ntsc.LINE))
        hit = np.nonzero(vs > _VSYNC_FILL)[0]
        if len(hit) and self._since_retrace >= d.v_accept_after:
            parity = 1 if hit[0] < ntsc.HALF else 2
            out.extend(self._retrace(parity))
        elif self._since_retrace >= d.v_free_lines:
            last = self._field.parity if self._field else 2
            out.extend(self._retrace(2 if last == 1 else 1))
        # Levels, from ordinary lines (not the vertical interval, by the decoder's count) the
        # flywheel found a sync for.
        frame_line = (self._line_no - 1) % ntsc.LINES + 1
        ordinary = ntsc.has_burst(frame_line)
        if ordinary and self._missed == 0:
            blank = self._mean("y", p, ntsc.BACK_PORCH).real
            tip = self._mean("y", p, ntsc.SYNC_TIP).real
            self._clamp += d.clamp_smoothing * (blank - self._clamp)
            gain = float(np.clip((ntsc.BLANK - ntsc.SYNC) / max(blank - tip, 1.0), *d.agc_range))
            self._agc = (
                gain if self._agc is None else self._agc + d.agc_smoothing * (gain - self._agc)
            )
        agc = self._agc or 1.0
        # Colour reference from the burst.
        b0, b1 = ntsc.BURST_START + 8, ntsc.BURST_START + ntsc.BURST_LEN - 8
        if ordinary:
            burst = self._mean("zb", p, (b0, b1))
            ref = self._burst / max(abs(self._burst), 1e-9)
            step = burst * ref.conjugate()
            self._lock += d.lock_smoothing * (step.real - self._lock)
            self._burst_noise += d.lock_smoothing * (step.imag**2 - self._burst_noise)
            self._burst += d.burst_smoothing * (burst - self._burst)
        self._h_lock += d.h_lock_smoothing * ((self._missed == 0) - self._h_lock)
        strength = self._lock * agc / ntsc.BURST if self._h_lock > 0.5 else 0.0
        snr = self._lock / math.sqrt(max(self._burst_noise, 1e-9))
        self._colour_ok = strength > d.killer_off and snr > d.killer_snr_off
        self._colour_good = strength > d.killer_on and snr > d.killer_snr_on
        # The picture.
        if self._field is not None:
            row = self._line_no - ntsc.FIRST_LINE[self._field.parity]
            if 0 <= row < ntsc.FIELD_LINES:
                span = ntsc.WHITE - ntsc.SETUP
                t = p + ntsc.ACTIVE_START
                y = np.real(self._at("y", t, ntsc.ACTIVE))
                z = self._at("z", t, ntsc.ACTIVE)
                if self._comb:
                    w = np.real(self._at("w", t, ntsc.ACTIVE))
                    y = w * y + (1 - w) * np.real(self._at("yc", t, ntsc.ACTIVE))
                    z = w * z + (1 - w) * self._at("zc", t, ntsc.ACTIVE)
                self._field.y[row] = ((y - self._clamp) * agc - ntsc.SETUP) / span
                if self._colour:
                    acc = min(ntsc.BURST / max(abs(self._burst), 1e-6), d.acc_max_gain)
                    turn = np.exp(1j * (math.pi / 2 - np.angle(self._burst)))
                    c = z * (turn * acc / span)
                    self._field.v[row] = c.real
                    self._field.u[row] = -c.imag
                    self._colour_lines += 1
        self._line_no += 1
        self._since_retrace += 1
        return out

    # -- vertical --------------------------------------------------------------------

    def _retrace(self, parity: int) -> list[Field]:
        """Vertical retrace: the field so far is done; the next starts, at the line its
        broad pulses start in."""
        done = self._finish()
        self._colour = self._colour_good or (self._colour and self._colour_ok)
        shape = (ntsc.FIELD_LINES, ntsc.ACTIVE)
        self._field = Field(parity, np.zeros(shape), np.zeros(shape), np.zeros(shape))
        self._line_no = ntsc.VSYNC_LINE[parity]
        self._since_retrace = 0
        self._synced_lines = 0
        self._colour_lines = 0
        return [done] if done else []

    def _finish(self) -> Field | None:
        f = self._field
        if f is None:
            return None
        lines = max(self._since_retrace, 1)
        f.synced = min(self._synced_lines / lines, 1.0)
        f.colour = min(self._colour_lines / ntsc.FIELD_LINES, 1.0)
        if f.synced < self.d.lost_below and self.d.on_loss != "snow":
            f.y[:] = 0.0
            f.u[:] = 0.0
            f.v[:] = 0.0
            if self.d.on_loss == "blue":  # sRGB (0, 0, 0.75) as Y'UV
                f.y[:] = 0.114 * 0.75
                f.u[:] = 0.492111 * (0.75 - 0.114 * 0.75)
                f.v[:] = 0.877283 * (0 - 0.114 * 0.75)
        return f


class _Comb:
    """An adaptive two-line comb filter's streams, beside the notch decoder's: comb luma and
    chroma, and how far to trust the notch instead (w, 0 comb to 1 notch)."""

    def __init__(self, bp_taps: NDArray[np.float64], d: Decoder) -> None:
        self._held = np.zeros(ntsc.LINE)
        """The one line delay: the last line of raw signal."""
        self._diff = StreamFir(bp_taps)
        self._bp_before = StreamFir(bp_taps)
        self._luma = StreamFir(lowpass(31, d.luma_bandwidth_hz, ntsc.FS))
        self._demod = StreamFir(lowpass(61, d.chroma_lowpass_hz, ntsc.FS))
        self._env = StreamFir(lowpass(61, d.chroma_lowpass_hz, ntsc.FS))
        self._env_line = StreamFir(lowpass(61, d.chroma_lowpass_hz, ntsc.FS))
        self._edge = StreamFir(lowpass(61, 1.0e6, ntsc.FS))
        """The two lines' difference below the chroma: a vertical edge in the luma."""

    def delays(self, db: int) -> dict[str, int]:
        return {
            "yc": db + self._luma.delay,
            "zc": db + self._demod.delay,
            "w": db + self._env.delay,
        }

    def __call__(
        self,
        x: NDArray[np.float64],
        delayed: NDArray[np.float64],
        bp: NDArray[np.float64],
        k: NDArray[np.int_],
    ) -> dict[str, NDArray[Any]]:
        """For chunk `x`: `delayed` is the raw signal matching the band-pass `bp`, `k` the
        subcarrier phase of each sample."""
        held = np.concatenate([self._held, x])
        before = held[: len(x)]
        self._held = held[len(held) - ntsc.LINE :]
        carrier = np.array([2, -2j, -2, 2j])[k]
        # The subcarrier turns over from line to line: the difference is chroma, twice over.
        chroma = self._diff(x - before) / 2
        luma = self._luma(delayed - chroma)
        z = self._demod(chroma * carrier)
        # Where the lines differ, the comb would mix them: a vertical edge in the luma, or the
        # colour's strength changing from one line to the next. There, the notch.
        edge = np.abs(self._edge(x - before))
        here = np.abs(self._env_line(bp * carrier))
        there = np.abs(self._env(self._bp_before(before) * carrier))
        change = np.abs(here - there) / (here + there + 4.0)
        w = np.clip(np.maximum((edge - 4.0) / 8.0, (change - 0.2) / 0.3), 0.0, 1.0)
        return {"yc": luma, "zc": z, "w": w}
