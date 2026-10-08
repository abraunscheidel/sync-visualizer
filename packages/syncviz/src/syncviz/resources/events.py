"""Events: things that occur at a time or over an interval (design doc §16).

Times are in the *native* clock of whatever produced the series. Converting to
shared time is the job of a TimeMapping, never of the event series itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class EventSeries:
    times: np.ndarray                      # seconds, native clock, sorted
    durations: np.ndarray | None = None    # seconds, same length as times, or None for instants
    name: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        times = np.asarray(self.times, dtype=float)
        if times.ndim != 1:
            raise ValueError("times must be 1-D")
        if np.any(np.diff(times) < 0):
            raise ValueError("times must be sorted")
        object.__setattr__(self, "times", times)
        if self.durations is not None:
            durations = np.asarray(self.durations, dtype=float)
            if durations.shape != times.shape:
                raise ValueError("durations must have the same shape as times")
            object.__setattr__(self, "durations", durations)

    def __len__(self) -> int:
        return len(self.times)
