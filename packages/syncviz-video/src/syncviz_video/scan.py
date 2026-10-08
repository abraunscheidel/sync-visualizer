"""One full decode of a video, recording per-frame statistics.

Container timestamps are deliberately ignored: some scientific videos carry
meaningless ones (DANDI 000231 reports 30 fps and a 13,040 s duration for a
200 fps recording), so frames are identified by their index in decode order.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import av
import numpy as np


def scan_brightness(
    path: str | Path,
    stride: int = 8,
    progress: Callable[[int], None] | None = None,
) -> np.ndarray:
    """Mean grayscale brightness of every frame, from a spatially subsampled image.

    `stride` subsamples rows and columns (stride=8 reads 1/64 of the pixels),
    which is plenty for detecting blackouts and much cheaper than full frames.
    """
    out: list[float] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        stream.thread_type = "AUTO"
        for i, frame in enumerate(container.decode(stream)):
            gray = frame.to_ndarray(format="gray")
            out.append(float(gray[::stride, ::stride].mean()))
            if progress is not None and i % 10000 == 0:
                progress(i)
    return np.asarray(out, dtype=np.float32)
