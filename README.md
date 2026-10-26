# analog-vision

Analog NTSC video over an FM radio link, simulated from the signal up: what a camera on an
analog FPV drone sends, and what the pilot's goggles show, at any signal strength.

A picture is encoded as composite video, frequency-modulated as the video transmitter does
it, given the receiver's thermal noise at a carrier-to-noise ratio (CNR), demodulated, and
decoded as the goggles' decoder does it. Nothing is painted on. Every artifact comes out of
that chain: the grain, the colour speckle, the black and white "sparklies" near the FM
threshold, lines torn sideways, the picture rolling, colour dropping out, then snow.

![Colour bars through the simulated link: clean, grain, sparklies, colour killer, tearing,
snow, and two kinds of multipath](docs/effects.jpg)

*Colour bars (75 %, over a grey ramp and a 0.5 to 5 MHz sweep) through the link at falling
signal strength, and with echoes. Made by `uv run python scripts/effects.py`.*

**[Try it live in the browser](https://synetic-labs.github.io/Analog-Vision/)**: every
setting, on colour bars, our lab captures or a picture or video of your own.

Use it to train and test vision models on what an analog link really delivers, to judge a
link budget by eye, or live in a browser: the same chain runs on the GPU in
`src/analog_vision/web/analog.js` (below).

```bash
uv sync
uv run analog-vision sweep bars sweep.png                     # colour bars at 30 to 5 dB
uv run analog-vision apply photo.jpg out.png --cnr 9
uv run analog-vision apply photo.jpg out.png --distance 1500 --tx-mw 25
uv run analog-vision fly photo.jpg frames/ --from 200 --to 4000 --frames 120
uv run analog-vision sweep photo.jpg sweep.png --dvr 50       # as the goggles' DVR records it
uv run analog-vision sweep photo.jpg sweep.png --cnr 22,16 --indoor 0 --speed 5   # indoors
uv run analog-vision sweep photo.jpg sweep.png --yc comb --capture   # HDZero monitor, HDMI capture
```

```python
from analog_vision import AnalogVideo, Dvr, Link, degrade, link_cnr_db

out = degrade(image, cnr_db=9, seed=0)        # H x W x 3 in, same size uint8 out
dvr = degrade(image, cnr_db=9, dvr=Dvr(quality=50))   # what a DVR keeps: one field, JPEG

sim = AnalogVideo(Link(cnr_db=link_cnr_db(distance_m=800, tx_mw=25)), seed=0)
for frame in video:                            # 29.97 frames a second
    shown = sim.show(frame)                    # .image, .synced, .colour
```

`degrade` runs two frames (the decoder locks on the first), about 0.3 s on one core.
`AnalogVideo` carries the signal on from frame to frame, as a real link does: the
decoder's lock, its AGC, the subcarrier's phase. `set_link` changes the conditions between
frames without breaking them.

## In the browser

`uv run analog-vision view` opens a page that runs the link live, at 60 fields a second: a
picture (colour bars, anything under `reference/`, or a picture or video of your own) goes
through it beside the original, and every field of `Link`, `Echo`, `Decoder` and `Dvr` is a
control, with its documentation, that the picture follows as it moves. Any control can be
swept: a still at each value along its range, everything else as set. **vs Python** sets
the Python's picture for the same settings beside the live one. The page shows the
settings as code, Python and JavaScript, and keeps them in its address.
`uv run analog-vision view --export site/` writes it as static files, with colour bars and
our lab captures, to host anywhere (without the Python beside it): `.github/workflows/pages.yml`
does that on every push to `main` and publishes it to GitHub Pages.

The live chain is `src/analog_vision/web/analog.js`, a WebGL2 port of this package, stage
for stage, by the same settings' names; about 1 ms of GPU a field. It is held to the Python
by `tests/test_web.py`, in headless Chrome: without noise the two pictures agree to a level
or two in 255 (notch and comb, echoes, tuning offset, filters, levels); with noise, the
grain's strength agrees to 0.1 dB from 20 to 3 dB, and colour and sync go at the same CNR.
Its noise is its own draw, so no picture with noise is the Python's to the pixel; its
recorder compresses with the browser's JPEG encoder, close to PIL's but not the same.

```js
import { AnalogFeed, linkCnrDb } from "./analog.js";

const feed = new AnalogFeed(canvas, { link: { cnr_db: 9 }, decoder: { yc: "comb" } });
function draw(now) {
  feed.cnrDb = linkCnrDb(distanceM, 25);           // or feed.set({ link: {...}, ... })
  feed.frame(videoOrCanvas, null, now);            // the lines due since the last frame
  requestAnimationFrame(draw);
}
requestAnimationFrame(draw);
```

## How bad, how far

The FM threshold is about 7 to 10 dB CNR. Above it, noise grows slowly as the signal falls;
below it, everything goes at once.

| CNR | What the goggles show |
|---|---|
| 30 dB and up | Clean: the softness, dot crawl and colour fringing analog always has. |
| 15 to 20 dB | Fine grain, blotchy colour noise in saturated areas. |
| 8 to 12 dB | Heavy grain and colour noise; the first sparklies. |
| Below about 7 dB | The colour killer: black and white, sparklies, the odd line torn sideways. |
| 0 to 4 dB | Tearing, the picture slipping and rolling. |
| Below 0 dB | Snow (or blue or black, `Decoder(on_loss=...)`). |

Real flights fade and recover by several dB a second (antenna angles, bodies, multipath),
so they flicker between rows of this table; vary `cnr_db` from frame to frame with
`set_link` to get that.

## Indoors: multipath

Indoors, short range does not mean a clean picture. Walls, floors and steel beams send the
signal back tens of nanoseconds late, often nearly as strong as the direct path when that is
blocked or in an antenna's null. In FM an echo's phase against the direct path follows the
carrier's instantaneous frequency, that is the picture's level, so it does what thermal noise
cannot: hue that shifts with brightness (rainbows along smooth shading, white walls gone
purple, a yellow gate green), and, at the levels where it nearly cancels the direct path,
clicks and dropouts. As the drone moves each echo's phase turns at its Doppler difference
(about 19 Hz per m/s at 5.8 GHz), so all that sweeps down the picture in bands.

```python
from analog_vision import Echo, Link, indoor_echoes

link = Link(cnr_db=18, multipath=(Echo(delay_s=40e-9, level_db=-1, doppler_hz=90),))
link = Link(cnr_db=18, multipath=indoor_echoes(rng, k_db=0, speed_ms=5, count=3))
```

`indoor_echoes` draws a channel as Wi-Fi's indoor models do (IEEE 802.11 TGn: exponential
power delay profile, 15 to 50 ns of delay spread, Rician K for the direct path). Frames from
a BETAFPV Air75 flown in a large hall (lab captures, NTSC) look like K of 0 dB and below,
with a few strong echoes (`count=3`) rather than many weak ones.

## Range

`link_cnr_db` gives the CNR from range over free space: transmitter power, antenna gains,
receiver noise figure (6 dB) and IF bandwidth (18 MHz). With the defaults, the RTC6715
receiver's -85 dBm sensitivity is about 10 dB CNR; 25 mW is at 9 dB by 700 m and gone by
2 km, 600 mW still at 13 dB at 2 km, in free space. `extra_loss_db` takes bodies, trees and
buildings.

## The chain

1. **Camera** (`encode.py`): R'G'B' to Y'UV, luma band-limited to 4.2 MHz and chroma to
   1.3 MHz, chroma quadrature-modulated on the 3.579545 MHz subcarrier; sync, blanking,
   equalizing and broad pulses, colour burst, two interlaced fields, all to SMPTE 170M, at
   four times the subcarrier (14.318 MHz, 910 samples a line). NTSC-M with 7.5 IRE setup.
2. **Link** (`fm.py`): the video frequency-modulates the carrier (5 MHz peak to peak for
   1 Vpp, no video pre-emphasis, as the RTC6705 does it), on complex baseband at 28.6 MHz.
   White Gaussian noise at the CNR, optional echoes (multipath) and tuning offset; the
   receiver's IF filter, a discriminator (the phase step between samples), its video filter
   and clipping.
3. **Goggles** (`decode.py`): sync slicer, a horizontal flywheel (phase-locked loop) that
   coasts through missing syncs and searches when it has lost them, vertical sync by
   integrating the broad pulses with a free-running vertical oscillator, back-porch clamp,
   AGC on the sync depth, notch Y/C separation with a 4.2 MHz luma low-pass (luma runs to
   about 2.3 MHz, as notch decoders do) or an adaptive two-line comb (`Decoder(yc="comb")`,
   `hdzero_monitor()`: luma to 4.2 MHz, chroma noise shared by neighbouring lines, the notch
   where the lines differ), burst-locked chroma demodulation at 0.6 MHz with
   ACC, a lock detector and a colour killer that judges the burst's own signal to noise, once
   a field; weave or bob deinterlacing to the output size.
4. **Recorder** (`pipeline.Dvr`, optional): one field of each frame line-doubled, 640 x 480,
   JPEG-compressed, as MJPEG goggle DVRs keep it; or `Dvr.hdmi_capture()`, both fields at
   720p, lightly compressed, as a monitor's HDMI into a capture card.

Every setting is a field of `Link` or `Decoder`, documented where it is defined.

## What is assumed, and how it was checked

The real video deviation and the receiver's IF bandwidth are not published; the defaults
come from the RTC6715's sensitivity test (+-2.5 MHz) and Carson's rule. The decoder is a
generic one, not a particular chip; receivers differ most in their colour killer (some keep
colour through dense sparklies, some go black and white early).

Indoors it was compared against 35 lab captures from a BETAFPV Air75 (NTSC) flown in a
large hall, received by an HDZero monitor and recorded from its HDMI by an Elgato capture
card (`reference/lab/`), where multipath, not noise, does the damage (above). The monitor's comb filter shows
in them: no line structure, and colour noise in short vertical streaks.

It was compared against stills from analog FPV DVR recordings of range tests (25 to 500 mW,
out to 11 km) and an analog satellite sparklies test (third-party, so not in the repository:
`reference/web/SOURCES.md` lists each, to the second). It reproduces their sequence: grain and blotchy colour noise, then
sparklies (dark over bright, light over dark), the colour killer, tearing, snow. Those
recordings went through a DVR and a YouTube re-encode, which smear fine detail, so the
noise's per-pixel texture (how long a sparklie's dash is, how coarse the snow is) is not
calibrated yet: that needs an uncompressed capture of a real receiver's output.

Not modelled yet: the camera itself (lens, sensor noise, rolling shutter, exposure), the 6.0
and 6.5 MHz audio subcarriers, receiver diversity switching, fading within a frame.

## Checks

```bash
uv run ruff check src tests scripts && uv run basedpyright src tests scripts && uv run pytest -q
```

`tests/test_web.py` needs Chrome or Chromium (on the `PATH`, or `ANALOG_VISION_CHROME`) and
is skipped without one; a GPU makes it quick.
