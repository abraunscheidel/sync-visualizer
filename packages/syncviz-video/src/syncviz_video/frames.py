"""Pixel access for decoded frames."""

from __future__ import annotations

import av
import numpy as np

# Pixel formats whose first plane is 8-bit luma, so it can be read without conversion.
# Anything else (RGB or planar RGB such as gbrp, 10/12/16-bit YUV, palettes, Bayer, ...)
# has a first plane that is not 8-bit brightness and must go through a conversion.
LUMA_FIRST_PLANE = frozenset(
    {
        "yuv420p", "yuvj420p", "yuva420p",
        "yuv422p", "yuvj422p",
        "yuv444p", "yuvj444p",
        "yuv440p", "yuvj440p",
        "nv12", "nv21",
        "gray",
    }
)


def has_native_luma(frame: av.VideoFrame) -> bool:
    return frame.format.name in LUMA_FIRST_PLANE


def luma(frame: av.VideoFrame) -> np.ndarray:
    """Brightness image of a decoded frame, as a (height, width) uint8 array.

    For the usual 8-bit YUV video the first plane already is the grayscale image,
    so it is returned as a view with no conversion. Converting with
    `to_ndarray(format="gray")` is about 9x slower (172 vs 1,579 frames/s measured
    on DANDI 000231) because it runs a single-threaded format conversion on every
    frame. Formats without a native luma plane fall back to that conversion.

    The two paths use different value conventions: the native plane keeps the
    encoded values (video range: black near 16, white near 235), while the
    conversion returns full range (0-255). Brightness numbers are therefore only
    comparable within one path. Check `has_native_luma` when that matters.

    A native-plane view is only valid until the frame is released; copy it to keep it.
    """
    if not has_native_luma(frame):
        return frame.to_ndarray(format="gray")
    plane = frame.planes[0]
    rows = np.frombuffer(plane, dtype=np.uint8).reshape(frame.height, plane.line_size)
    return rows[:, : frame.width]
