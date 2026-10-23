"""NTSC-M as a composite signal sampled at four times the colour subcarrier (4fsc).

525 lines a frame in two interlaced fields, 59.94 fields a second. At 4fsc a line is exactly
910 samples (227.5 subcarrier cycles), so the subcarrier's phase at any sample is that
sample's index times 90 degrees, and inverts from one line to the next.

Levels are in IRE: blanking 0, sync tip -40, white 100; 140 IRE is 1 V peak to peak.
Times within a line are samples from the 50 % point of the horizontal sync's leading edge.
Lines are numbered from 1, as in SMPTE 170M.
"""

from dataclasses import dataclass

FSC = 315e6 / 88
"""Colour subcarrier, Hz (3.579545 MHz)."""
FS = 4 * FSC
"""Sample rate, Hz (14.318 MHz)."""
LINE = 910
"""Samples a line (63.556 us)."""
HALF = LINE // 2
LINES = 525
FRAME = LINE * LINES
"""Samples a frame (two fields)."""
LINE_RATE = FS / LINE
"""Hz (15 734.26)."""
FIELD_RATE = 2 * LINE_RATE / LINES
"""Hz (59.94)."""

SYNC = -40.0
BLANK = 0.0
SETUP = 7.5
"""Black, 7.5 IRE above blanking in NTSC-M as used in North America (0 in Japan)."""
WHITE = 100.0
BURST = 20.0
"""Colour burst amplitude, IRE (40 IRE peak to peak)."""
MID = (SYNC + WHITE) / 2
"""Halfway from sync tip to white: the FM carrier's rest frequency."""

HSYNC = 67
"""Horizontal sync, 4.7 us."""
EQUALIZING = 33
"""Equalizing pulse, 2.3 us."""
BROAD = 388
"""Vertical sync's broad pulse, 27.1 us (a 4.7 us serration ends each half line)."""
BURST_START = 76
"""5.3 us: sync, then the 0.6 us breezeway."""
BURST_LEN = 36
"""Nine subcarrier cycles."""
ACTIVE_START = 135
"""9.4 us: where the picture starts."""
ACTIVE = 754
"""Samples of picture a line (52.66 us), 4:3."""
BACK_PORCH = (BURST_START + BURST_LEN + 4, ACTIVE_START - 4)
"""Blanking after the burst, where a decoder reads the black level."""
SYNC_TIP = (8, HSYNC - 8)

FIELD_LINES = 240
"""Picture lines a field."""
ACTIVE_LINES = 2 * FIELD_LINES
FIRST_LINE = {1: 23, 2: 286}
"""The first picture line of each field. Field 2 starts half a line in, so it is the upper
of the two on screen: frame row 2i is field 2's line 286 + i, row 2i + 1 field 1's 23 + i."""
VSYNC_LINE = {1: 4, 2: 266}
"""The line each field's broad pulses start in: at its start (field 1) or halfway (field 2)."""

# The vertical interval as half lines, numbered from 0 at the start of line 1: six
# equalizing pulses, six broad pulses, six equalizing pulses, for each field.
_PRE, _BROAD, _POST = range(0, 6), range(6, 12), range(12, 18)
FIELD2_HALF = 2 * (263 - 1) + 1
"""Field 2's vertical interval starts halfway through line 263."""


@dataclass(frozen=True)
class HalfLine:
    pulse: int
    """Sync pulse at its start, samples: HSYNC, EQUALIZING, BROAD or 0."""


def half_line(h: int) -> HalfLine:
    """Half line `h` of the frame (0 to 1049): which sync pulse starts it."""
    for start in (0, FIELD2_HALF):
        k = h - start
        if k in _PRE or k in _POST:
            return HalfLine(EQUALIZING)
        if k in _BROAD:
            return HalfLine(BROAD)
    return HalfLine(HSYNC if h % 2 == 0 else 0)


def has_burst(line: int) -> bool:
    """Whether line `line` (1 to 525) carries a colour burst: those that start with an
    ordinary horizontal sync."""
    return half_line(2 * (line - 1)).pulse == HSYNC


def picture_line(row: int) -> int:
    """The line carrying frame row `row` (0 to 479, top to bottom)."""
    field = 2 if row % 2 == 0 else 1
    return FIRST_LINE[field] + row // 2
