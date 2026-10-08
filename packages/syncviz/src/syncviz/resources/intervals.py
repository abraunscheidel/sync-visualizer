"""Intervals: labeled stretches of time, with attributes (design doc §10, §16).

A trial table, a set of behavioral epochs, detected contacts and stimulus
periods are all interval series. The core attaches no meaning to them; whether
a set of intervals is called "trials" is a display choice made in configuration.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(frozen=True)
class IntervalSeries:
    starts: np.ndarray                                      # seconds, native clock, non-decreasing
    stops: np.ndarray                                       # seconds, >= starts
    attributes: dict[str, np.ndarray] = field(default_factory=dict)   # one value per interval
    name: str = ""
    descriptions: dict[str, str] = field(default_factory=dict)        # what each attribute means, as the source states it

    def __post_init__(self) -> None:
        starts = np.asarray(self.starts, dtype=float)
        stops = np.asarray(self.stops, dtype=float)
        if starts.ndim != 1 or starts.shape != stops.shape:
            raise ValueError("starts and stops must be 1-D arrays of equal length")
        if np.any(stops < starts):
            raise ValueError("every stop must be at or after its start")
        if np.any(np.diff(starts) < 0):
            raise ValueError("intervals must be sorted by start time")
        attributes = {}
        for key, values in self.attributes.items():
            values = np.asarray(values)
            if values.shape != starts.shape:
                raise ValueError(f"attribute {key!r} must have one value per interval")
            attributes[key] = values
        object.__setattr__(self, "starts", starts)
        object.__setattr__(self, "stops", stops)
        object.__setattr__(self, "attributes", attributes)

    def __len__(self) -> int:
        return len(self.starts)

    def unique(self, attribute: str) -> list[Any]:
        """Distinct values of an attribute, in sorted order."""
        return np.unique(self.attributes[attribute]).tolist()

    def select(self, **criteria: Any) -> np.ndarray:
        """Indices of intervals matching every criterion.

        A criterion is a value, or a list/tuple/set of acceptable values.
        """
        mask = np.ones(len(self), dtype=bool)
        for key, wanted in criteria.items():
            if key not in self.attributes:
                raise KeyError(f"no attribute {key!r} (available: {sorted(self.attributes)})")
            column = self.attributes[key]
            if isinstance(wanted, (list, tuple, set, frozenset)):
                mask &= np.isin(column, list(wanted))
            else:
                mask &= column == wanted
        return np.flatnonzero(mask)

    def overlapping(self, start: float, stop: float) -> np.ndarray:
        """Indices of intervals that overlap the half-open window [start, stop)."""
        return np.flatnonzero((self.starts < stop) & (self.stops > start))

    def index_at(self, time: float) -> int | None:
        """Index of the interval containing `time`, or None.

        Assumes intervals do not overlap each other. Use `overlapping` for sets that do.
        """
        i = int(np.searchsorted(self.starts, time, side="right")) - 1
        if i >= 0 and time < self.stops[i]:
            return i
        return None
