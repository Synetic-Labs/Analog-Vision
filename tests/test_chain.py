"""The whole chain: levels in, pictures out, and what noise does between."""

import numpy as np
import pytest

from analog_vision import (
    AnalogVideo,
    Decoder,
    Dvr,
    Echo,
    FmLink,
    Link,
    degrade,
    encode,
    hdzero_monitor,
    indoor_echoes,
    link_cnr_db,
    ntsc,
)
from analog_vision.dsp import StreamFir, lowpass
from analog_vision.encode import yuv
from analog_vision.fm import free_space_loss_db
from analog_vision.patterns import BARS_75, colour_bars

BARS = colour_bars()


def bar_centres(image: np.ndarray, row: int = 160) -> list[np.ndarray]:
    w = image.shape[1]
    return [
        image[row - 4 : row + 4, int((i + 0.5) * w / 7) - 8 : int((i + 0.5) * w / 7) + 8]
        .reshape(-1, 3)
        .mean(0)
        for i in range(7)
    ]


def test_vertical_interval_has_the_standard_pulses() -> None:
    pulses = [ntsc.half_line(h).pulse for h in range(2 * ntsc.LINES)]
    assert pulses.count(ntsc.EQUALIZING) == 24
    assert pulses.count(ntsc.BROAD) == 12
    # Field 2's broad pulses start halfway through line 266.
    assert pulses[2 * (266 - 1) + 1] == ntsc.BROAD and pulses[2 * (266 - 1)] == ntsc.EQUALIZING


def test_every_picture_row_has_its_own_line_with_a_burst() -> None:
    lines = [ntsc.picture_line(r) for r in range(ntsc.ACTIVE_LINES)]
    assert len(set(lines)) == ntsc.ACTIVE_LINES
    assert all(ntsc.has_burst(line) for line in lines)


def test_composite_levels() -> None:
    frame = encode(BARS).reshape(ntsc.LINES, ntsc.LINE)
    line = frame[ntsc.picture_line(100) - 1]
    assert line[20:50].mean() == pytest.approx(ntsc.SYNC)
    assert line[ntsc.BACK_PORCH[0] : ntsc.BACK_PORCH[1]].mean() == pytest.approx(0, abs=0.1)
    burst = line[ntsc.BURST_START + 8 : ntsc.BURST_START + 28]
    assert burst.max() == pytest.approx(ntsc.BURST, abs=0.5)
    # The 75 % grey bar: black 7.5 IRE plus three quarters of the way to white, no chroma.
    grey = line[ntsc.ACTIVE_START + 20 : ntsc.ACTIVE_START + 80]
    assert grey.mean() == pytest.approx(7.5 + 0.75 * 92.5, abs=0.3)


def test_strong_signal_gives_the_picture_back() -> None:
    out = degrade(BARS, cnr_db=50, seed=0)
    for got, want in zip(bar_centres(out), BARS_75, strict=True):
        assert got == pytest.approx(np.array(want) * 255, abs=4)


def test_noise_grows_as_the_signal_fades() -> None:
    clean = degrade(BARS, cnr_db=60, seed=0).astype(float)
    errors = [np.sqrt(np.mean((degrade(BARS, cnr_db=c, seed=0) - clean) ** 2)) for c in (30, 15, 9)]
    assert errors[0] < errors[1] < errors[2]


def _clicks(cnr: float) -> int:
    """Specks in a flat grey: samples far off the grey, as an FM click makes them."""
    grey = np.full((480, 640, 3), 0.5)
    y, _, _ = yuv(degrade(grey, cnr_db=cnr, seed=4)[:, 8:-8] / 255.0)
    return int(np.sum(np.abs(y - np.median(y)) > 0.35))


def test_clicks_come_in_below_threshold() -> None:
    assert _clicks(16) == 0
    assert _clicks(6) > 50
    assert _clicks(4) > 3 * _clicks(6)


def _colour(cnr: float) -> float:
    sim = AnalogVideo(Link(cnr_db=cnr), seed=5)
    shown = sim.show(BARS)
    for _ in range(3):
        shown = sim.show(BARS)
    return shown.colour


def test_colour_killer_cuts_in_below_threshold_while_the_picture_holds() -> None:
    assert _colour(12) == 1.0
    assert _colour(4) == 0.0
    sim = AnalogVideo(Link(cnr_db=4), seed=5)
    shown = sim.show(BARS)
    for _ in range(3):
        shown = sim.show(BARS)
    assert shown.synced > 0.9


def test_dvr_records_one_field_compressed() -> None:
    live = degrade(BARS, cnr_db=40, seed=0)
    dvr = degrade(BARS, cnr_db=40, seed=0, dvr=Dvr(quality=40))
    assert dvr.shape == live.shape
    # Compression moves pixels, but the bars stay the bars.
    assert not np.array_equal(dvr, live)
    for got, want in zip(bar_centres(dvr), BARS_75, strict=True):
        assert got == pytest.approx(np.array(want) * 255, abs=10)


def test_colour_killer_and_lost_sync_with_no_signal() -> None:
    sim = AnalogVideo(Link(cnr_db=-10), seed=2)
    shown = sim.show(BARS)
    for _ in range(3):
        shown = sim.show(BARS)
    assert shown.synced < 0.2
    assert shown.colour < 0.5


def test_a_blue_screen_with_no_signal_if_asked() -> None:
    sim = AnalogVideo(Link(cnr_db=-10), Decoder(on_loss="blue"), seed=2)
    shown = sim.show(BARS)
    for _ in range(2):
        shown = sim.show(BARS)
    assert shown.image[240, 320].tolist() == [0, 0, 191]


def test_same_seed_same_picture() -> None:
    a = degrade(BARS, cnr_db=8, seed=7)
    b = degrade(BARS, cnr_db=8, seed=7)
    c = degrade(BARS, cnr_db=8, seed=8)
    assert np.array_equal(a, b)
    assert not np.array_equal(a, c)


def test_any_size_in_is_the_size_out() -> None:
    img = np.zeros((123, 77, 3), np.uint8)
    assert degrade(img, seed=0).shape == (123, 77, 3)
    sim = AnalogVideo(seed=0, size=(320, 240))
    assert sim(img).shape == (240, 320, 3)


def test_a_stream_keeps_its_lock_while_the_link_changes() -> None:
    sim = AnalogVideo(Link(cnr_db=30), seed=0)
    shown = sim.show(BARS)
    for cnr in (20, 12, 20, 30):
        sim.set_link(Link(cnr_db=cnr))
        shown = sim.show(BARS)
    assert shown.synced > 0.95
    for got, want in zip(bar_centres(shown.image), BARS_75, strict=True):
        assert got == pytest.approx(np.array(want) * 255, abs=12)


def test_link_budget() -> None:
    assert free_space_loss_db(1000, 5.8e9) == pytest.approx(107.7, abs=0.1)
    # The RTC6715's -85 dBm sensitivity, with the default receiver: about 10 dB CNR.
    noise_dbm = -174 + 10 * np.log10(Link.if_bandwidth_hz) + 6
    assert -85 - noise_dbm == pytest.approx(10.4, abs=0.1)
    near, far = link_cnr_db(100), link_cnr_db(1000)
    assert near - far == pytest.approx(20, abs=0.01)


def test_stream_fir_is_one_filter_over_the_chunks() -> None:
    rng = np.random.default_rng(0)
    x = rng.standard_normal(5000)
    taps = lowpass(31, 2e6, 14.3e6)
    fir = StreamFir(taps)
    chunked = np.concatenate([fir(x[:1234]), fir(x[1234:4000]), fir(x[4000:])])
    whole = np.convolve(x, taps)[: len(x)]
    assert np.allclose(chunked, whole)


def test_an_echo_is_one_continuous_signal_across_chunks() -> None:
    link = Link(cnr_db=300, multipath=(Echo(37e-9, -3, 40, 90),))
    x = encode(BARS)
    whole = FmLink(link, np.random.default_rng(0))(x)
    fm = FmLink(link, np.random.default_rng(0))
    parts = np.concatenate([fm(x[:100_000]), fm(x[100_000:300_001]), fm(x[300_001:])])
    assert np.allclose(whole, parts, atol=1e-6)


def test_a_strong_echo_shifts_hue_with_level() -> None:
    clean = degrade(BARS, cnr_db=40, seed=0)
    echo = degrade(BARS, link=Link(cnr_db=40, multipath=(Echo(40e-9, -1, 170),)), seed=0)
    _, u0, v0 = yuv(clean / 255.0)
    _, u1, v1 = yuv(echo / 255.0)
    hue0 = np.angle(u0[100:300] + 1j * v0[100:300]).mean(0)
    hue1 = np.angle(u1[100:300] + 1j * v1[100:300]).mean(0)
    # On the bars, not one hue held.
    shift = [abs(hue1[x] - hue0[x]) for x in (140, 230, 320, 410, 500)]
    assert max(shift) > 0.3


def test_indoor_echoes() -> None:
    a = indoor_echoes(np.random.default_rng(1), k_db=3, speed_ms=5)
    b = indoor_echoes(np.random.default_rng(1), k_db=3, speed_ms=5)
    assert a == b
    power = sum(10 ** (e.level_db / 10) for e in a)
    assert 10 * np.log10(power) == pytest.approx(-3)
    assert all(e.delay_s > 0 for e in a)
    # At most twice speed over wavelength (5.17 cm at 5.8 GHz).
    assert all(abs(e.doppler_hz) <= 2 * 5 / 0.0517 for e in a)


def test_comb_decoder_gives_the_bars_back() -> None:
    out = degrade(BARS, cnr_db=50, seed=0, decoder=hdzero_monitor())
    for got, want in zip(bar_centres(out), BARS_75, strict=True):
        assert got == pytest.approx(np.array(want) * 255, abs=4)


def test_comb_keeps_fine_luma_out_of_the_colour() -> None:
    """The sweep under the bars runs up through the subcarrier: a notch decodes it as false
    colour, a comb (the same on every line, so it cancels) as luma."""

    def false_colour(decoder: Decoder) -> float:
        _, u, v = yuv(degrade(BARS, cnr_db=50, seed=0, decoder=decoder) / 255.0)
        rows = slice(410, 470)
        return float(np.hypot(u[rows, 330:600], v[rows, 330:600]).mean())

    assert false_colour(hdzero_monitor()) < 0.3 * false_colour(Decoder())
