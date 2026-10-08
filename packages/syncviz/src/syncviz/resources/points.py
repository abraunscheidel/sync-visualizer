"""Tracked points over time: the positions of several named points (a pose, or a whisker's markers), with the links between them.

Typical of pose estimation: for every time sample, an x and y for each point. Positions are in the numbers the source stored
(for tracking on a video, picture pixels); `metadata` says anything needed to interpret them.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class PointTracks:
    times: np.ndarray                     # (n,) seconds, native clock, non-decreasing
    xy: np.ndarray                        # (n, k, 2): x and y of each of k points at each time
    names: tuple[str, ...]                # the k point names, in the same order
    edges: tuple[tuple[int, int], ...] = ()     # pairs of point indices that are joined (a skeleton)
    unit: str = ""
    name: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        times = np.asarray(self.times, dtype=float)
        xy = np.asarray(self.xy)
        if times.ndim != 1:
            raise ValueError("times must be 1-D")
        if xy.ndim != 3 or xy.shape[0] != len(times) or xy.shape[2] != 2 or xy.shape[1] != len(self.names):
            raise ValueError("xy must have shape (samples, points, 2) with one entry per name")
        if np.any(np.diff(times) < 0):
            raise ValueError("times must be sorted")
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "xy", xy)

    def __len__(self) -> int:
        return len(self.times)

    @property
    def first_time(self) -> float:
        return float(self.times[0])

    @property
    def last_time(self) -> float:
        return float(self.times[-1])

    @property
    def typical_interval(self) -> float:
        return float(np.median(np.diff(self.times))) if len(self.times) > 2 else 0.0

    def at(self, time: float, max_gap: float | None = None) -> np.ndarray | None:
        """The (k, 2) positions at the sample nearest `time`, or None if there is no sample within `max_gap` seconds (by default
        one and a half of the usual interval): a moment without tracking shows nothing rather than the last known place."""
        if len(self.times) == 0:
            return None
        if max_gap is None:
            max_gap = 1.5 * self.typical_interval or 0.01
        j = int(np.searchsorted(self.times, time))
        nearest = min((k for k in (j - 1, j) if 0 <= k < len(self.times)), key=lambda k: abs(self.times[k] - time))
        return None if abs(self.times[nearest] - time) > max_gap else np.asarray(self.xy[nearest], dtype=float)

    def chain(self) -> list[int]:
        """The points in order along the skeleton, from one end to the other, when the edges form a single chain (a whisker,
        a limb); otherwise their natural order."""
        k = len(self.names)
        neighbours: dict[int, list[int]] = {i: [] for i in range(k)}
        for a, b in self.edges:
            neighbours[a].append(b)
            neighbours[b].append(a)
        ends = [i for i, n in neighbours.items() if len(n) == 1]
        if len(self.edges) != k - 1 or len(ends) != 2 or any(len(n) > 2 for n in neighbours.values()):
            return list(range(k))
        order, previous, current = [], None, min(ends)
        while current is not None:
            order.append(current)
            following = [n for n in neighbours[current] if n != previous]
            previous, current = current, (following[0] if following else None)
        return order if len(order) == k else list(range(k))
