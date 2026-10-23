# Reference stills: analog 5.8 GHz FM FPV video

These are third-party works (frames of other people's YouTube videos), used to calibrate the
simulator against. They are not ours to redistribute, so the stills themselves are not in the
repository (git-ignored): this file says where each came from, to the second, so they can be
taken again with `yt-dlp` and `ffmpeg -ss <t> -frames:v 1`.

Every still is a single frame taken from a YouTube upload, collected 2026-10-22. I downloaded
each video at up to 720p, video only, used `ffmpeg -ss <t> -frames:v 1` to take the frame, and
then deleted the clip. The timestamp `tNNNN.N` in each file name is seconds into the YouTube
video. A PiP or split-screen source was cropped to its goggle panel.

**Caveat for every file:** YouTube re-encodes everything as H.264 or VP9 at 0.7 to 3.5 Mb/s. Fine
noise is therefore partly smeared into blocks, and single-pixel sparkles lose contrast.
Treat the noise *structure*, its *colour behaviour* and its *spatial extent* as reliable. Do
not trust absolute noise power or pixel-exact grain. A goggle DVR adds its own MJPEG or H.264
compression before YouTube does.

## File naming

`<stage>_<what>_<power-distance>_<source>_t<seconds>.png`

| Prefix | Meaning |
|---|---|
| `base_` | Clean baseline of a CMOS FPV camera (softness, colour bleed, cross-colour) |
| `s0_` | Clean signal, possibly at distance |
| `s1_` | Slight grain and chroma noise, picture fully intact |
| `s2_` | Sparkles (FM clicks) or heavy chroma noise, picture still readable |
| `s3_` | Colour killed (black and white), click streaks, horizontal shifts or tearing |
| `s4_` | Snow, sync loss, white or black bands |
| `sat*` | Analog C-band satellite TV (FM video) threshold sparklies, the control case |
| `cmp_` | The same moment shown by two different receivers |

## Sources (videos)

| Key | URL | Author / channel | Setup (from description and OSD) | Std / capture |
|---|---|---|---|---|
| rizalyusan-11km | https://www.youtube.com/watch?v=3ygyKqO4VsU "Raw DVR, Analog FPV Range Test 11 km" (2025-03-02) | Rizal Yusan | Chimera 7. VTX Rush Max Solo 2.5 W, "@1W" per the description but the OSD reads 25MW at takeoff and 500MW in cruise (VTX power switching). Receiver EV800D with 12-turn helical. Control link ELRS 2.4 GHz; its RSSI is the OSD "-xx:2" figure, not video RSSI. The OSD shows home distance. | Raw goggle DVR (EV800D), 600x480 upload, 30 fps. The uploader blurred parts of the OSD. |
| ichsan-3km | https://www.youtube.com/watch?v=0vSu8neuA6M "ONLY 25mW Analog FPV Goes 3KM!" (2026-07-21) | Ichsan_channel | Mark4 5", camera **Caddx Ratel 2**, VTX JHEMCU Ruibet 1.6 W. The description says "set 25mW" but the OSD shows 25MW, then 50MW, then **100MW** at the far end. TX antenna Pagoda 2. Receiver EV800DM (AKK diversity mod) with 7-turn helical. The OSD gives home distance and ELRS RSSI. The video is edited or sped up: the OSD timer runs to 7:27 in a 1:44 video. | Goggle DVR, 640x480 upload, 30 fps. Probably NTSC. |
| jani-25mW-pip | https://www.youtube.com/watch?v=5aINewhS4DU "5.8GHz @ 25mW VTX range test" (2019-01-13) | Jani Lamminen | C1 Chaser wing. Camera **RunCam Split Mini V1**. VTX FuriousFPV Stealth LR at **25 mW**. Receiver FR632 with a self-made 12-turn helicoil and pagoda. iNav OSD with home distance. The flight is over a frozen lake, so there is little multipath. | The FPV feed is a PiP inset (about 470x349 crop) in a 1280x720 onboard HD video. It looks like a receiver/DVR capture, not a screen filmed by a camera, but the PiP is downscaled. The OSD looks PAL-style (Finland). |
| splitshorts-unify25mW | https://www.youtube.com/watch?v=_k6E1tS4Tl8 "TBS Unify Pro HV, 25mw vs. 800mw 1000m Range Test" (2020-03-12) | Split-Shorts | iFlight Nazgul5, VTX **TBS Unify Pro HV at 25 mW** (left panel) versus 800 mW (right panel), receiver Fatshark Recon V3, out and back to about 1000 m (editor's overlay and map). | Split screen. The left 25 mW panel is cropped to 628x428, and its bottom-right corner includes part of the Google Maps overlay. The capture method isn't stated (the Recon V3 has no DVR), so it is probably an external DVR. The editor's "100" overlay sits on some frames. |
| vampie-night-fog-250mW | https://www.youtube.com/watch?v=jN0iB-BIR6s "An analog FPV video signal loss and recovery - in bad conditions" (2026-01-08) | VampieFPV | Night, low cloud or fog, among trees. The OSD shows **250MW** VTX power and ELRS RSSI. The camera picture is effectively monochrome (night or low light), so colour behaviour can't be judged from it. | The first section is the FPV DVR (stated in the description), pillarboxed in 1280x720 and cropped to 900x720 (DVR upscaled). |
| pekka-ratel2-cobrax | https://www.youtube.com/watch?v=roQDCsd6pAI "Caddx ratel 2 + Eachine Skyzone Cobra X raw DVR" (2021-03-22) | Pekka Vallo | Camera **Caddx Ratel 2**, goggles Skyzone Cobra X. The uploader says he fixed grounding to get "finally clean FPV video". Snow scene within about 560 m. | Raw goggle DVR, 574x480 upload, **25 fps, so PAL**. |
| flosfpv | https://www.youtube.com/watch?v=MFdXdDKfh7Y "Rapidfire vs SkyzoneSky02s, Long range 3,5km" (2021-03-30) | FlosFPV | The same flight received on an ImmersionRC RapidFire module (left PiP) and a Skyzone Sky02S (right PiP). Fixed wing out to about 3.6 km. | Two DVR PiPs (about 335x250 each) over an HD onboard video, 1280x720. |
| mattcintosh-cband-vcII | https://www.youtube.com/watch?v=I0y_BjqE26A "VideoCipher II being mistuned and the sparklies and crackling appearing" (2015-02-23) | mattcintosh | C-band analog FM satellite TV (Galaxy G5, ch. 17, VideoCipher II). The polarity (skew) is swept from -60 to -6 degrees and back; the receiver OSD shows polarity and signal. | 320x240 upload. It appears to be a direct capture of the receiver's output with its OSD; I saw no bezel or moiré. NTSC. |

## Per-file notes

Trust ratings: **A** = raw DVR, good resolution, conditions known. **B** = genuine but downscaled,
PiP, or with unclear capture. **C** = useful but heavily compromised.

### Clean baseline (camera and decode, strong signal)

- **base_clean-closeup-ratel2_pekka-ratel2-cobrax_t0002.png** (t=0:02). Shows the Ratel 2 on the
  ground at 0 m: saturated blue sky, snow, OSD text. Visible: soft luma (around 300 to 350 TVL
  effective), a slight bloom on the white OSD glyphs, and a dark/bright outline on the OSD (the
  OSD chip's black border). PAL. **A** for camera softness.
- **base_clean-353m-ratel2_pekka-ratel2-cobrax_t0028.png** (t=0:28). Strong signal at 353 m and
  40 m altitude. Shows snowy town and trees with fine detail. Noise is not visible. Use it as the
  sharpness and saturation target. **A**.
- **base_cross-colour-rainbow-ratel2-563m_pekka-ratel2-cobrax_t0064.5.png** (t=1:04.5). At 563 m,
  fine diagonal tree shadows on snow carry **rainbow cross-colour** (luma detail near the colour
  subcarrier decoded as chroma), mid-frame. The sun bloom has a halo. This is the composite
  decode artifact to reproduce at full signal. **A**.
- **s0_clean_25mW-598m_ichsan-3km_t0010.png** (t=0:10). Caddx Ratel 2 at 25 mW and 598 m, clean.
  Soft colour, slight chroma smear on the red roofs, and a faint halo on OSD glyphs. **A**.
- **s0_clean_25mW-home_rizalyusan-11km_t0030.png** (t=0:30). At 25 mW near home (0 m), clean. Shows
  mild ringing on the OSD and grass detail softened by the DVR. **A**.
- **s0_clean_500mW-4.0km_rizalyusan-11km_t0250.png** (t=4:10). At 500 mW and 4.0 km, still
  essentially clean with no visible grain. Shows how much margin 500 mW plus a helical gives. **A**.
- **s0_clean-grey_25mW-1.83km_jani-25mW-pip_t0120.png** (t=2:00). At 25 mW and 1.83 km over a
  grey, overcast frozen lake, nearly clean. The scene is low in colour. **B** (PiP).

### Stage 1: grain and chroma noise, picture intact

- **s1_grain-speckle_100mW-3.19km_ichsan-3km_t0050.1.png** (t=0:50). At 100 mW and 3.19 km there is
  fine luma grain plus coloured speckle over the whole frame. Detail is still readable and the
  OSD is clean, because it is generated after the receiver. **A**. Ideal "slight grain" target.
- **s1_grain-colournoise_100mW-3.08km_ichsan-3km_t0053.0.png** (t=0:53). The same as the above at
  3.08 km, with somewhat more chroma (purple and green) blotch noise in flat areas. **A**.
- **s1_grain-sparkle-sky_25mW-~850m_splitshorts-unify25mW_t0202.png** (t=3:22). At 25 mW, on the way
  out (about 850 m by the map, approximate), coloured sparkle and speckle appear mainly in the
  **bright sky**. **B**.
- **s1_grain-chroma_25mW-~950m_splitshorts-unify25mW_t0214.png** (t=3:34). At 25 mW and about 950 m,
  saturated grass with moderate chroma grain. **B**.
- **s1_chroma-noise_25mW-5.54km_jani-25mW-pip_t0168.png** (t=2:48). At 25 mW and 5.54 km the
  **whole frame is covered in fine magenta and green chroma noise**, while the luma image (horizon,
  islands) stays readable. Clear evidence that, below the FM knee, noise lands at chroma
  frequencies first. This fits the parabolic (triangular amplitude) noise spectrum of an FM
  discriminator. **B** (PiP).
- **s1_chroma-noise_25mW-3.74km-return_jani-25mW-pip_t0291.png** (t=4:51). The same on the return
  leg at 3.74 km (OSD "RTH EN ROUTE TO HOME"). Heavy chroma noise, luma intact. **B**.
- **s1_night-fog-lowlight_250mW_vampie-night-fog-250mW_t0001.png** (t=0:01). At night in fog,
  250 mW. A dark, mostly monochrome picture with a light speckle layer. The street light blooms.
  **B** (no colour info).

### Stage 2: sparkles (FM clicks) and heavy chroma noise

- **s2_sparkles_500mW-9.4km_rizalyusan-11km_t0565.8.png** (t=9:25.8). At 500 mW and 9.4 km. Many
  short **dark horizontal dashes** (about 3 to 8 px long) over bright cloud, with light grain,
  while the colour of the trees and sky survives. The classic edge-of-range "sparkle" look. **A**.
- **s2_sparkles-dense_500mW-10.9km_rizalyusan-11km_t0677.1.png** (t=11:17.1). At 500 mW and 10.9 km,
  a dense burst. Hundreds of black and coloured dashes, worst in the **top half and in bright
  areas**. The OSD stays clean. Bursts last a few frames between clean frames. **A**. The best
  click reference.
- **s2_sparkle-band_500mW-11.0km_rizalyusan-11km_t0685.0.png** (t=11:25). At 500 mW and 11.0 km,
  clicks concentrated in **two horizontal bands** (about rows 310 to 330 and 360 to 380). A short
  burst lasting a fraction of a field, typical of multipath or antenna-null fades. **A**.
- **s2_sparkles-dense-night_250mW_vampie-night-fog-250mW_t0015.png** (t=0:15). At night with
  250 mW. Dense black and white click speckle over a fogged scene; the OSD is partly broken up.
  This means the OSD here is camera-side (inserted before the VTX), so it degrades with the
  link. **B**.
- **s2_chroma-noise-heavy_25mW-~970m_splitshorts-unify25mW_t0216.png** (t=3:36). At 25 mW, about
  1 km. Strong saturated chroma noise (red, yellow, purple) over the whole frame, with the picture
  still there. **B**.
- **s2_chroma-noise-heavy-hline_25mW-5.7km_jani-25mW-pip_t0177.png** (t=2:57). At 25 mW and 5.7 km,
  very heavy full-frame chroma noise. A **single white horizontal line** near row 270 is a
  momentary sync or noise burst on one line. **B**.

### Stage 3: colour killed, click streaks, horizontal shifts

- **s3_colour-killed-bw_25mW-~950m_splitshorts-unify25mW_t0215.png** (t=3:35). The frame
  right after s1_grain-chroma. The **picture turns grey (black and white)**; the colour killer
  has dropped chroma because burst lock was lost, while luma is still clean. One frame later
  (t0216) the colour returns with heavy chroma noise. **B**. The best colour-killer reference.
- **s3_desaturated-noise_100mW-3.31km_ichsan-3km_t0044.5.png** (t=0:44.5). At 100 mW and 3.31 km,
  strongly desaturated (nearly black and white) with luma grain and some clicks on the bright
  cloud. The colour is partly killed. **A**.
- **s3_bw-click-streaks_25mW-~1000m_splitshorts-unify25mW_t0217.png** (t=3:37). At 25 mW and about
  1000 m. **Black and white** (colour killed) with long **white horizontal click streaks** that
  form ragged bands, mostly in the bright sky and the top third. The dark ground has fewer,
  sparser white flecks, and the luma looks posterised. **B**. The key "almost lost" frame.
- **s3_bw-click-streaks-2_25mW-~1000m_splitshorts-unify25mW_t0219.5.png** (t=3:39.5). The same
  stage. White streak clusters in the sky, a faint scene underneath, and a darker lower half. **B**.
- **s3_rainbow-chroma-streaks_25mW-~1000m_splitshorts-unify25mW_t0218.png** (t=3:38). Between
  the black-and-white frames the colour flickers back on. The **click streaks decode as saturated
  rainbow (red, green, blue, magenta) horizontal streaks**, because the chroma decoder still
  locks briefly and demodulates noise. **B**.
- **s3_bw-faint-streaks_25mW-~1000m_splitshorts-unify25mW_t0223.png** (t=3:43). Black and white,
  lower contrast, with streaks along the horizon. On its way back to a usable picture. **B**.
- **s3_heavy-noise-hblank-bar_250mW_vampie-night-fog-250mW_t0010.png** (t=0:10). A noisy night
  picture with the **horizontal blanking (black vertical bar) drifting into view at the right**:
  horizontal sync has slipped, so the line start is shifted. **B**.

### Stage 4: snow and sync loss

- **s4_snow-dark-hshift_25mW-~5.9km_jani-25mW-pip_t0192.png** (t=3:12). At 25 mW, beyond about
  5.9 km. A **dark** frame of sparse white and coloured snow; the picture is gone. There is a black
  bar at the right edge from H-sync displacement. **B**.
- **s4_snow-bw-streaks_25mW-~5.9km_jani-25mW-pip_t0195.png** (t=3:15). Full **black and white
  snow** with strong horizontal streak texture (short white dashes, not round dots) and a faint
  ghost of the scene. This is what the "snow" stage really looks like on an FM link: streaky,
  colourless and contrasty, not TV-style AM grain. **B**.
- **s4_snow-white-band-syncloss_25mW_jani-25mW-pip_t0246.72.png** (t=4:06.72). During total loss
  the frame splits into a **near-white band** (top two thirds) over dark snow, with a hard
  horizontal boundary. This is vertical sync loss or rolling: the receiver, DVR and display
  free-run and show partial fields or clipped levels. Over a few seconds these bands move and
  alternate. **B**.
- **s4_snow-black-band-syncloss_25mW_jani-25mW-pip_t0249.56.png** (t=4:09.56). As above but
  inverted: a **near-black band** with sparse white streaks over the top, a white strip, and grey
  snow below. **B**.
- **s4_snow-full_250mW_vampie-night-fog-250mW_t0014.png** (t=0:14). Pure grey **snow**
  (horizontally elongated grains) with no picture. **B**.
- **s4_snow-hsync-shift-bar_250mW_vampie-night-fog-250mW_t0020.png** (t=0:20). Snow with a ghost of
  the scene (a light trail) and a **dark vertical blanking bar about 85% across**; the line timing
  is displaced. **B**.

### Receiver comparison

- **cmp_rapidfire-chroma-vs-sky02s-bw-snow_flosfpv_t0210.png** (t=3:30). At the same moment
  (about 2.8 to 3.6 km), the **RapidFire** shows a full-colour picture with chroma noise, while
  the **Sky02S** shows a **black and white, snowy** picture of the same scene. The colour killer
  and the noise threshold depend strongly on the receiver: a few dB of sensitivity, or diversity
  and processing, moves the whole sequence. **B**.
- **cmp_rapidfire-vs-sky02s-both-chroma-noise_flosfpv_t0230.png** (t=3:50). Here both receivers
  show colour with heavy chroma noise and grain; the Sky02S is noisier. **B**.

### Analog FM satellite TV control case (not FPV)

- **sat0_clean-same-scene_mattcintosh-cband-vcII_t0005.png** (t=0:05). A clean C-band FM picture
  (night scene), to compare with the next two.
- **sat2_sparklies-moderate_pol-12deg_mattcintosh-cband-vcII_t0021.5.png** (t=0:21.5). With the
  polarity mistuned (-12 degrees), FM threshold **sparklies** appear: short **white horizontal
  dashes** over dark content (and some dark ones over bright), evenly spread over the frame.
  **B** (320x240).
- **sat2_sparklies-heavy_pol-06deg_mattcintosh-cband-vcII_t0031.7.png** (t=0:31.7). At -6 degrees,
  dense sparklies, while colour stays mostly intact. **B**. Satellite FM uses wider deviation and
  deemphasis than FPV, but the click shape is the same as in the FPV frames: a short horizontal
  streak, brighter on dark areas and darker on bright areas.

## Technical observations

**Breakup sequence as seen in these recordings.** In order of decreasing signal:

1. The picture is clean, but soft, with OSD halos and cross-colour on fine detail.
2. Fine luma grain plus **chroma noise** (magenta and green blotches), most visible in flat
   areas. Luma detail is unaffected. At 25 mW this shows up at about 0.9 km (TBS Unify, quad)
   up to 3 to 5.5 km (wing over a frozen lake with a 12-turn helical).
3. **Sparkles**: short black or white horizontal dashes (FM clicks). They appear in bursts and
   are strongest in the brightest and darkest areas. A click pushes the level towards the
   opposite extreme, so bright clouds get black dashes and a dark night scene gets white ones.
   Bursts are often limited to horizontal bands, which matches fast fading.
4. **The colour killer turns the picture black and white** for a frame or a few frames. It then
   flickers back with rainbow-coloured streaks (noise decoded as chroma), then black and white
   again. The black-and-white stage keeps more luma detail than the colour frames beside it.
5. **Black and white streaky snow** with a faint ghost. The horizontal blanking bar becomes
   visible at the side as H-sync slips.
6. **Total loss**: grey, black-and-white snow made of horizontally elongated dashes. During
   vertical sync loss, large near-white and near-black bands with hard horizontal edges roll
   through the frame.

Recovery runs the same steps in reverse, and often in under a second.

**What the receiver shows on total loss.** Most analog receivers and box goggles (EV800D,
FR632, Sky02S here) show **snow**. Many receivers (RapidFire, Fatshark modules, monitors) have a
"blue screen" or "no blue" option. With blue screen on, the display blanks to blue or black once
sync is lost. With "no blue" (the default for most FPV pilots), it shows snow and whatever
picture survives. Forum reports say DJI goggles on analog AV-in go to a black screen with PAL
cameras but snow with NTSC ones, and Caddx Goggles X draw synthetic "fake snow" that is not
recorded on the DVR. Sources: intofpv threads
[27928](https://intofpv.com/printthread.php?tid=27928),
[13146](https://intofpv.com/printthread.php?tid=13146) and
[25098](https://intofpv.com/printthread.php?tid=25098). These are anecdotal.

**OSD placement matters.** In Betaflight or iNav setups the OSD is overlaid by the flight
controller (AT7456E/MAX7456) *before* the VTX. It therefore degrades with the link, as in the
vampie night frames. In the Rizal and Ichsan EV800D DVRs the OSD glyphs stay crisp even during
sparkles; partly that is because they are bright, saturated white that survives clicks better.
The OSD text has a black outline, a recognisable baseline detail.

**Colour depends on the receiver.** The FlosFPV comparison shows the same signal coming out as
colour from a RapidFire and black-and-white snow from a Sky02S. Colour-killer threshold and
noise floor differ by receiver by several dB.

**DVR formats seen.** These YouTube uploads came at 640x480 (EV800DM), 600x480 (EV800D, cropped),
574x480 (Cobra X, cropped) and 30 or 25 fps. Spec sheets list the EV800D DVR as 720x576 (PAL
frame size). The Skyzone Sky02S records MJPEG AVI at about 6 Mb/s
([getfpv EV800D](https://www.getfpv.com/eachine-ev800d-5-8g-40ch-diversity-fpv-goggles-with-dvr.html),
[getfpv Sky02S](https://www.getfpv.com/skyzone-sky02s-v-3d-5-8g-40ch-fpv-goggles-w-vtx.html)).
Goggle DVRs deinterlace or drop a field, so clicks appear as short dashes on single rows rather
than as interlaced pairs.

**Receiver figures.** The RX5808 spec quotes sensitivity of -88 dBm minimum and -90 dBm typical,
wideband FM, video bandwidth 0 to 8 MHz, and a 6.5 MHz audio subcarrier
([RX5808 Spec V1](https://mikrocontroller.net/attachment/172723/RX5808-Spec-V1.pdf)).

**FM threshold theory.** The sat-TV patents describe it this way: a plain discriminator reaches
threshold at roughly 10 to 11 dB C/N, where noise peaks reach the carrier amplitude and "take
over the detector" for the length of the noise pulse, producing sparklies. Threshold-extension
PLL or tracking-filter demodulators gain a few dB but can produce "large black or white specks"
when they lose lock. Sources:
[US4918532](https://patents.google.com/patent/US4918532) and
[US4746873](https://patents.justia.com/patent/4746873). These match the dash-shaped clicks in the
FPV and satellite frames.

**Power and range in these sources.** One forum report has 25 mW breaking up at about 100 m
with a poor setup and 250 m on 25 mW versus 1.2 km on 800 mW. In these videos: the Unify at
25 mW broke up at about 1 km on a quad; a wing at 25 mW with a 12-turn helical went beyond
5.5 km; 100 mW (Ratel 2, helical) gave chroma noise at about 3.1 km; 500 mW to 1 W with a
12-turn helical gave clicks at 9 to 11 km. Antennas and receiver matter at least as much as
power. Sources: [intofpv 5006](https://intofpv.com/printthread.php?tid=5006),
[intofpv 29841](https://intofpv.com/printthread.php?tid=29841).

## Gaps

- **No controlled test** of a test pattern or colour bars over a 5.8 GHz link with calibrated
  attenuation turned up on YouTube or the web. A bench test with a VTX, attenuators and a DVR
  would fill this best.
- **No clean vertical roll of an intact picture.** Sync loss here only appears during snow (the
  white and black bands). There is also no clear frame of "picture shifted sideways with the
  colour intact".
- **No NTSC/PAL certainty for most FPV sources.** Pekka (25 fps) is PAL, and Rizal and Ichsan
  (30 fps) are probably NTSC.
- **No lab images of FM click noise** other than the satellite clip.
