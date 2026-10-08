"""Detect blackout frames in a video and report them as sync pulses."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from syncviz.cache import DiskCache
from syncviz.resources import EventSeries
from syncviz_video.scan import scan_brightness

AUTO_THRESHOLD_FRACTION = 0.5


@dataclass(frozen=True)
class DarkRuns:
    start_frames: np.ndarray    # index of the first dark frame of each run
    lengths: np.ndarray         # run length in frames
    threshold: float            # brightness below which a frame counts as dark


def find_dark_runs(brightness: np.ndarray, threshold: float | str = "auto") -> DarkRuns:
    """Find runs of consecutive frames darker than `threshold`.

    "auto" uses half the median brightness. That suits recordings where blackouts
    are brief relative to the session; a video that is mostly dark needs an
    explicit threshold.
    """
    b = np.asarray(brightness, dtype=float)
    if b.ndim != 1 or b.size == 0:
        raise ValueError("brightness must be a non-empty 1-D array")
    if isinstance(threshold, str):
        if threshold != "auto":
            raise ValueError(f"threshold must be a number or 'auto', got {threshold!r}")
        thr = AUTO_THRESHOLD_FRACTION * float(np.median(b))
    else:
        thr = float(threshold)
    dark = b < thr
    edges = np.diff(np.r_[0, dark.astype(np.int8), 0])
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    return DarkRuns(start_frames=starts, lengths=ends - starts, threshold=thr)


class DarkFrameDetector:
    """Sync-signal detector: blackout frames -> EventSeries in the video's native clock."""

    def __init__(self, threshold: float | str = "auto", stride: int = 8) -> None:
        self.threshold = threshold
        self.stride = stride

    def detect(
        self,
        video_path: str | Path,
        fps: float,
        cache: DiskCache | None = None,
        progress: Callable[[int], None] | None = None,
    ) -> EventSeries:
        def compute() -> np.ndarray:
            return scan_brightness(video_path, stride=self.stride, progress=progress)

        if cache is not None:
            brightness = cache.get_or_compute(
                video_path, "brightness", compute, params={"stride": self.stride}
            )
        else:
            brightness = compute()

        runs = find_dark_runs(brightness, self.threshold)
        return EventSeries(
            times=runs.start_frames / fps,
            durations=runs.lengths / fps,
            name="dark_frames",
            metadata={
                "n_frames": int(len(brightness)),
                "fps": fps,
                "threshold": runs.threshold,
                "detector": "dark_frames",
            },
        )
