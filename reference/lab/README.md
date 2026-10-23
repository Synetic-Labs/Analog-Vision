# Lab captures

35 frames from our lab, `lab_00.jpeg` to `lab_34.jpeg` (numbered as captured).

- **Camera and link:** BETAFPV Air75, its analog camera and VTX, NTSC, 5.8 GHz.
- **Where:** indoors, a large hall with steel roof trusses, glass walls and race gates, at
  short range.
- **Receiver:** an HDZero monitor in analog mode (adaptive comb decoder, deinterlaced,
  upscaled to 720p), its HDMI recorded by an Elgato capture card, exported at 854 x 480 with
  the 4:3 picture pillarboxed at x 106 to 745 (640 x 480).

At short range the damage is multipath, not noise (README, "Indoors: multipath"):

| What | Frames |
|---|---|
| Near clean: good inputs | 01, 02, 03, 23 |
| Hue bands and rainbows along smooth shading | 15, 16, 20, 30 |
| Colour that depends on brightness, false-colour gates | 04, 06, 13, 14, 26, 28 |
| Click bands and dropouts on particular levels | 00, 09, 22, 24, 25, 29 |
| Colour killer (black and white) | 07, 17, 32, 33 |
| Horizontal timing warps | 07, 08, 12 |
| Vertical slips | 10, 18 |

No line structure shows (the monitor deinterlaces and scales), and colour noise runs in
short vertical streaks, as a comb decoder leaves it.
