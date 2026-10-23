"""Composite video over an FM radio link: the video transmitter, the air, the receiver.

The transmitter's oscillator follows the composite signal: its frequency is the carrier's
plus `deviation_hz / 140` per IRE, sync tip low, white high (as the RTC6705 modulates its
VCO, with no video pre-emphasis). The air adds the receiver's thermal noise, at a
carrier-to-noise ratio (CNR) over the receiver's IF bandwidth, and any echoes (multipath).
The receiver filters to that bandwidth and recovers the frequency with a discriminator: the
phase step from each sample to the next. Its video amplifier band-limits and clips the
result.

Nothing else is added. Everything FM does to a picture comes from that chain:

- Well above threshold, noise that rises with frequency ("triangular"): fine grain, worst at
  the colour subcarrier, so colour speckles before brightness does.
- Near the threshold (about 7 to 10 dB CNR), clicks: when noise swings the received phasor
  round the origin the discriminator jumps a whole cycle, a spike of either sign. They show
  as black and white specks ("sparklies"), multiplying fast as the signal fades.
- Below it, noise in the sync and the burst: the receiver's decoder (decode.py) loses lock.

The simulation runs on complex baseband at twice the video's sample rate (8 fsc, 28.6 MHz),
wide enough for the IF bandwidth.
"""

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from analog_vision import ntsc
from analog_vision.dsp import StreamFir, lowpass

FS_RF = 2 * ntsc.FS
"""Complex baseband sample rate, Hz (28.6 MHz)."""
VIDEO_CLIP = (-60.0, 140.0)
"""The receiver's video output can swing this far, IRE, and no further."""


@dataclass(frozen=True)
class Echo:
    """The signal off a wall, a floor, a steel beam: late, weaker, its phase turned.

    Against the direct path its phase depends on the carrier's instantaneous frequency (by
    360 degrees per 1/delay of deviation), so what it does depends on the picture's level: hue
    that shifts with brightness, and, where it nearly cancels the direct path, clicks at that
    level. As the drone moves its phase turns at the Doppler difference, about 19 Hz for each
    m/s the path lengthens at 5.8 GHz, sweeping all that down the picture."""

    delay_s: float
    level_db: float
    """Relative to the direct path: near 0 when the direct path is blocked or in a null."""
    phase_deg: float = 0.0
    doppler_hz: float = 0.0


@dataclass(frozen=True)
class Link:
    """The radio link. Defaults are a typical 5.8 GHz analog FPV pair (RTC6705 transmitter,
    RTC6715 receiver)."""

    cnr_db: float = 30.0
    """Carrier to noise over `if_bandwidth_hz`, dB. 7 to 10 dB is the FM threshold."""
    deviation_hz: float = 5e6
    """Peak-to-peak deviation for 1 Vpp (sync tip to white). The RTC6715's sensitivity is
    specified at +-2.5 MHz; the real video deviation is not published."""
    if_bandwidth_hz: float = 18e6
    """The receiver's IF bandwidth: Carson's rule for this deviation and 4.2 MHz video,
    with margin. Not published for the RTC6715."""
    video_bandwidth_hz: float = 5e6
    """The receiver's video output filter."""
    carrier_offset_hz: float = 0.0
    """Receiver tuned off the transmitter: a DC shift in the video, until it clips."""
    multipath: tuple[Echo, ...] = ()
    """Echoes, indoors tens of nanoseconds late and a few dB down."""


def indoor_echoes(
    rng: np.random.Generator,
    delay_spread_s: float = 30e-9,
    k_db: float = 3.0,
    speed_ms: float = 3.0,
    count: int = 6,
    frequency_hz: float = 5.8e9,
) -> tuple[Echo, ...]:
    """A random indoor channel, as Wi-Fi's indoor models have it (IEEE 802.11 TGn B to D:
    15 to 50 ns of delay spread): `count` echoes, their power falling off exponentially with
    delay, together `k_db` (Rician K) below the direct path; low K is a blocked or nulled
    direct path. Each echo arrives from its own direction, so at `speed_ms` its phase turns
    against the direct path's at up to twice speed / wavelength."""
    delays = np.sort(rng.exponential(delay_spread_s, count)) + 3e-9
    power = np.exp(-delays / delay_spread_s)
    power *= 10 ** (-k_db / 10) / power.sum()
    per_ms = frequency_hz / 299_792_458.0
    direct = math.cos(rng.uniform(0, 2 * math.pi))
    return tuple(
        Echo(
            delay_s=float(d),
            level_db=float(10 * np.log10(pw)),
            phase_deg=float(rng.uniform(0, 360)),
            doppler_hz=float(speed_ms * per_ms * (math.cos(rng.uniform(0, 2 * math.pi)) - direct)),
        )
        for d, pw in zip(delays, power, strict=True)
    )


def free_space_loss_db(distance_m: float, frequency_hz: float) -> float:
    return 20 * math.log10(4 * math.pi * distance_m * frequency_hz / 299_792_458.0)


def link_cnr_db(
    distance_m: float,
    tx_mw: float = 25.0,
    tx_gain_dbi: float = 2.0,
    rx_gain_dbi: float = 2.0,
    frequency_hz: float = 5.8e9,
    noise_figure_db: float = 6.0,
    if_bandwidth_hz: float = Link.if_bandwidth_hz,
    extra_loss_db: float = 0.0,
) -> float:
    """CNR at the receiver, dB, over free space: received power over thermal noise
    (-174 dBm/Hz) in the IF bandwidth, raised by the receiver's noise figure. With the
    defaults the RTC6715's -85 dBm sensitivity is about 10 dB CNR. `extra_loss_db`: bodies,
    trees, buildings, a bad antenna."""
    rx_dbm = (
        10 * math.log10(tx_mw)
        + tx_gain_dbi
        + rx_gain_dbi
        - free_space_loss_db(distance_m, frequency_hz)
        - extra_loss_db
    )
    noise_dbm = -174 + 10 * math.log10(if_bandwidth_hz) + noise_figure_db
    return rx_dbm - noise_dbm


def _upsampler() -> NDArray[np.float64]:
    return 2 * lowpass(63, 5.5e6, FS_RF)


class FmLink:
    """One link, carrying a continuous signal a chunk at a time."""

    def __init__(self, link: Link, rng: np.random.Generator) -> None:
        self.link = link
        self.rng = rng
        self._up = StreamFir(_upsampler())
        self._if = StreamFir(lowpass(63, link.if_bandwidth_hz / 2, FS_RF))
        self._video = StreamFir(lowpass(63, link.video_bandwidth_hz, FS_RF))
        self._phase = 0.0
        self._n = 0
        self._last = np.complex128(1.0)
        longest = max((e.delay_s for e in link.multipath), default=0.0)
        self._history = np.zeros(math.ceil(longest * FS_RF) + 2)
        """The transmitted phase's last samples, for the echoes."""

    def __call__(self, composite: NDArray[np.float64]) -> NDArray[np.float64]:
        """The receiver's video for `composite` (IRE at 4fsc), one sample out for each in."""
        link = self.link
        # Transmitter: up to 8 fsc, then frequency follows the video.
        stuffed = np.zeros(2 * len(composite))
        stuffed[::2] = composite
        video = self._up(stuffed)
        freq = (video - ntsc.MID) * (link.deviation_hz / (ntsc.WHITE - ntsc.SYNC))
        phase = self._phase + np.cumsum(freq) * (2 * math.pi / FS_RF)
        rf = np.exp(1j * phase)
        # The air: echoes, each the transmitted phase a fraction of a sample late, then the
        # receiver's noise.
        t = (self._n + np.arange(len(rf))) / FS_RF
        if link.multipath:
            held = np.concatenate([self._history, phase])
            k = len(self._history) + np.arange(len(rf))
            for e in link.multipath:
                late = np.interp(k - e.delay_s * FS_RF, np.arange(len(held)), held)
                turn = math.radians(e.phase_deg) + 2 * math.pi * e.doppler_hz * t
                rf = rf + 10 ** (e.level_db / 20) * np.exp(1j * (late + turn))
            self._history = held[len(held) - len(self._history) :]
        # Keep the phase small without breaking it.
        wrap = 2 * math.pi * math.floor(phase[-1] / (2 * math.pi))
        self._phase = float(phase[-1] - wrap)
        self._history -= wrap
        n0 = 1.0 / (10 ** (link.cnr_db / 10) * link.if_bandwidth_hz)
        sigma = math.sqrt(n0 * FS_RF / 2)
        rf = rf + sigma * (
            self.rng.standard_normal(len(rf)) + 1j * self.rng.standard_normal(len(rf))
        )
        if link.carrier_offset_hz:
            rf *= np.exp(1j * 2 * math.pi * link.carrier_offset_hz * t)
        self._n += len(rf)
        # Receiver: IF filter, discriminator, video amplifier.
        rf = self._if(rf)
        prev = np.concatenate([[self._last], rf[:-1]])
        self._last = rf[-1]
        freq = np.angle(rf * np.conj(prev)) * (FS_RF / (2 * math.pi))
        video = freq / (link.deviation_hz / (ntsc.WHITE - ntsc.SYNC)) + ntsc.MID
        video = self._video(video)[::2]
        return np.clip(video, *VIDEO_CLIP)
