"""Analog NTSC video over an FM radio link, simulated from the signal up.

A picture is encoded as composite video, sent over FM with the receiver's noise, and decoded
as goggles decode it; what the noise does to the picture comes out of that chain.
"""

from analog_vision.decode import Decoder, Field, VideoDecoder, hdzero_monitor
from analog_vision.encode import encode
from analog_vision.fm import Echo, FmLink, Link, indoor_echoes, link_cnr_db
from analog_vision.pipeline import AnalogVideo, Dvr, Shown, degrade

__all__ = [
    "AnalogVideo",
    "Decoder",
    "Dvr",
    "Echo",
    "Field",
    "FmLink",
    "Link",
    "Shown",
    "VideoDecoder",
    "degrade",
    "encode",
    "hdzero_monitor",
    "indoor_echoes",
    "link_cnr_db",
]
