"""Frame index: which frame is which, and where decoding can start.

Built from packet headers only (no decoding), so it is cheap even for
multi-GB files. Frames are identified by their number in presentation
(display) order, never by container time, which can be meaningless (DANDI
000231 stores 200 fps video with 30 fps-style timestamps).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import av
import numpy as np

from syncviz.cache import DiskCache


@dataclass(frozen=True)
class FrameIndex:
    pts: np.ndarray          # int64, presentation timestamp of each frame, ascending; frame number = position
    keyframes: np.ndarray    # int64, frame numbers (presentation order) where decoding can start

    @property
    def n_frames(self) -> int:
        return len(self.pts)

    def frame_number(self, pts: int) -> int:
        """Frame number for a decoded frame's presentation timestamp."""
        n = int(np.searchsorted(self.pts, pts))
        if n >= len(self.pts) or self.pts[n] != pts:
            raise KeyError(f"pts {pts} is not in the frame index")
        return n

    def keyframe_at_or_before(self, frame: int) -> int:
        """Frame number of the latest keyframe at or before `frame`."""
        i = int(np.searchsorted(self.keyframes, frame, side="right")) - 1
        if i < 0:
            raise ValueError(f"no keyframe at or before frame {frame}")
        return int(self.keyframes[i])

    @classmethod
    def from_packet_table(cls, table: np.ndarray) -> FrameIndex:
        """`table` is (n, 2) int64: [pts, is_keyframe] per packet, in file order."""
        pts, is_key = table[:, 0], table[:, 1].astype(bool)
        order = np.argsort(pts, kind="stable")
        pts, is_key = pts[order], is_key[order]
        if np.any(np.diff(pts) <= 0):
            raise ValueError(
                "video has duplicate or non-increasing timestamps; "
                "frame numbers cannot be recovered from them"
            )
        return cls(pts=pts, keyframes=np.flatnonzero(is_key).astype(np.int64))

    @classmethod
    def build(cls, path: str | Path, cache: DiskCache | None = None) -> FrameIndex:
        if cache is not None:
            table = cache.get_or_compute(path, "frame_index", lambda: _read_packet_table(path))
        else:
            table = _read_packet_table(path)
        return cls.from_packet_table(table)


def _read_packet_table(path: str | Path) -> np.ndarray:
    rows: list[tuple[int, int]] = []
    with av.open(str(path)) as container:
        stream = container.streams.video[0]
        for packet in container.demux(stream):
            if packet.size == 0:      # end-of-stream flush packet
                continue
            if packet.pts is None:
                raise ValueError("video has packets without timestamps")
            rows.append((packet.pts, int(packet.is_keyframe)))
    return np.asarray(rows, dtype=np.int64).reshape(-1, 2)
