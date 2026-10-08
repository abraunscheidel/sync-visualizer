"""Video file access."""

from __future__ import annotations

from pathlib import Path

from syncviz.sources import Source


class VideoSource(Source):
    """A video file, addressed by frame index at a declared frame rate.

    `fps` comes from configuration (or the dataset's metadata), not from the
    container, which can be wrong.
    """

    def __init__(self, path: str | Path, fps: float) -> None:
        self.path = Path(path)
        self.fps = fps

    def describe(self) -> list[str]:
        return ["video"]
