"""Random access to video frames by index, without loading the whole file.

To reach frame N the decoder seeks to the latest keyframe at or before N and
decodes forward. Only the bytes of that group of pictures are read; memory use
is bounded by what the caller asks for.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator

import av
import numpy as np

from syncviz_video.frame_index import FrameIndex
from syncviz_video.frames import luma


class FrameReader:
    """Reads luma (brightness) frames by frame number. Not thread-safe: one reader per thread.

    Returned arrays are copies, so they stay valid after the reader moves on. See
    frames.luma for the value convention.
    """

    def __init__(self, path: str | Path, index: FrameIndex) -> None:
        self.path = Path(path)
        self.index = index
        self._container = av.open(str(self.path))
        self._stream = self._container.streams.video[0]
        self._stream.thread_type = "AUTO"

    def close(self) -> None:
        self._container.close()

    def __enter__(self) -> FrameReader:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def n_frames(self) -> int:
        return self.index.n_frames

    def _seek_to_keyframe_for(self, frame: int) -> None:
        keyframe = self.index.keyframe_at_or_before(frame)
        self._container.seek(
            int(self.index.pts[keyframe]), stream=self._stream, backward=True, any_frame=False
        )

    def iter_frames(self, start: int = 0, stop: int | None = None) -> Iterator[tuple[int, np.ndarray]]:
        """Yield (frame_number, gray image) in order. Seeks once, then decodes forward.

        Use this for playback and for any scan over a range; it never re-seeks.
        """
        stop = self.n_frames if stop is None else min(stop, self.n_frames)
        if not 0 <= start <= stop:
            raise IndexError(f"frame range [{start}, {stop}) is outside 0..{self.n_frames}")
        if start == stop:
            return
        self._seek_to_keyframe_for(start)
        expected = start
        for frame in self._container.decode(self._stream):
            n = self.index.frame_number(frame.pts)
            if n < start:       # leading frames before the requested start
                continue
            if n >= stop:
                break
            if n != expected:
                raise RuntimeError(f"decoder skipped from frame {expected} to {n}")
            yield n, luma(frame).copy()
            expected += 1
        if expected != stop:
            raise RuntimeError(f"stream ended at frame {expected}, expected {stop}")

    def read_frames(self, start: int, stop: int) -> np.ndarray:
        """Frames [start, stop) as an array of shape (stop - start, height, width)."""
        frames = [img for _, img in self.iter_frames(start, stop)]
        if not frames:
            raise IndexError("empty frame range")
        return np.stack(frames)

    def read_frame(self, n: int) -> np.ndarray:
        if not 0 <= n < self.n_frames:
            raise IndexError(f"frame {n} is outside 0..{self.n_frames - 1}")
        return self.read_frames(n, n + 1)[0]
