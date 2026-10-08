"""Regularly or irregularly sampled values over time (design doc §7)."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass(frozen=True)
class TimeSeries:
    times: np.ndarray        # seconds, native clock, non-decreasing
    values: np.ndarray       # first axis matches times
    unit: str = ""
    name: str = ""
    metadata: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        times = np.asarray(self.times, dtype=float)
        values = np.asarray(self.values)
        if times.ndim != 1:
            raise ValueError("times must be 1-D")
        if values.shape[:1] != times.shape:
            raise ValueError("values must have one row per timestamp")
        if np.any(np.diff(times) < 0):
            raise ValueError("times must be sorted")
        object.__setattr__(self, "times", times)
        object.__setattr__(self, "values", values)

    def __len__(self) -> int:
        return len(self.times)

    def window(self, start: float, stop: float) -> TimeSeries:
        """Samples with start <= time < stop (a view; nothing is copied)."""
        lo = int(np.searchsorted(self.times, start, side="left"))
        hi = int(np.searchsorted(self.times, stop, side="left"))
        return TimeSeries(
            self.times[lo:hi], self.values[lo:hi], self.unit, self.name, self.metadata
        )
