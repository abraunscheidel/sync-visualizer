"""Video file access."""

from __future__ import annotations

from pathlib import Path

from syncviz import plugins
from syncviz.resources import EventSeries
from syncviz.sources import DataEntry, MissingDataError, Source


class VideoSource(Source):
    """A video file, addressed by frame index at a declared frame rate.

    `fps` comes from configuration (or the dataset's metadata), not from the
    container, which can be wrong.
    """

    def __init__(self, path: str | Path, fps: float, sync_signal: dict | None = None) -> None:
        self.path = Path(path)
        self.fps = fps
        self.sync_signal = dict(sync_signal) if sync_signal else None        # e.g. {kind: dark_frames}

    def describe(self) -> list[str]:
        return ["video"] + (["sync_signal"] if self.sync_signal else [])

    def read_events(self, path: str) -> dict[str, EventSeries]:
        """The video's own sync signal (for example blackout frames) as events in the video's native clock,
        found by the detector the project names. The brightness scan behind it is cached."""
        if path != "sync_signal" or not self.sync_signal:
            raise MissingDataError(f"this video has no {path!r}" if path != "sync_signal" else "no sync_signal is configured for this video")
        params = {k: v for k, v in self.sync_signal.items() if k != "kind"}
        detector = plugins.load("sync_detectors", self.sync_signal["kind"])(**params)
        return {"sync_signal": detector.detect(self.path, self.fps, cache=self.cache)}
    def diagnostics(self) -> list:
        """Are the video's frames evenly spaced in time? Frames are identified by their number and placed at
        number / fps, which is right only if none were dropped or repeated; an uneven gap means later frames are
        later than that says."""
        import numpy as np

        from syncviz.diagnostics import CheckResult, Status
        from syncviz_video.frame_index import FrameIndex

        name = "Frames are evenly spaced"
        try:
            index = FrameIndex.build(self.path, cache=self.cache)
        except ValueError as exc:
            return [CheckResult(name, "video_frame_spacing", Status.FAIL, f"frame timestamps are unusable: {exc}")]
        gaps = np.diff(index.pts)
        if len(gaps) == 0:
            return []
        typical = float(np.median(gaps))
        # Containers round timestamps (a 30 fps clip stored in milliseconds has gaps of 33 and 34), so only a gap
        # that differs by half the usual one or more counts: a dropped frame leaves a gap about twice as long.
        odd = np.flatnonzero(np.abs(gaps - typical) > 0.5 * typical)
        share = len(odd) / len(gaps)
        status = Status.PASS if len(odd) == 0 else Status.WARN if share < 0.01 else Status.FAIL
        details = [f"{index.n_frames} frames; the usual gap between them is {typical:g} timestamp units",
                   f"{len(odd)} gaps are much longer or shorter than that ({share:.3%})"]
        if len(odd):
            details.append("if frames were dropped, every later frame is later than frame number / rate says")
            details.append("first uneven gaps at frames " + ", ".join(str(int(i)) for i in odd[:8]))
        summary = "all frame gaps are equal" if not len(odd) else f"{len(odd)} of {len(gaps)} gaps are uneven"
        return [CheckResult(name, "video_frame_spacing", status, summary, details)]

    def catalog(self) -> list[DataEntry]:
        entries = [DataEntry("video", "video")]
        if self.sync_signal:
            entries.append(DataEntry("sync_signal", "events", ("sync_signal",), {"sync_signal": "Video sync signal"}))
        return entries
