"""Regularly or irregularly sampled values over time (design doc §7).

Two kinds share one interface (what a view uses):

* `TimeSeries` holds all its samples in memory. Right for anything that fits comfortably.
* `LazyTimeSeries` holds only a handle to samples that stay in their file (anything array-like:
  an HDF5 dataset, a memory map) and reads just the window asked for. Right for continuous
  recordings of many gigabytes, where loading the whole thing is impossible.

Both offer `window`, `coverage`, `first_time`, `last_time`, `count_between`, `sample_values` and
`time_base`, so a view works with either without knowing which it has.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

MAX_BLOCK_READ = 20_000_000      # a window with more samples than this is read thinned, not in full
COVERAGE_CHUNK = 4_000_000       # samples of an explicit time axis examined at a time
SAMPLE_BLOCKS = 50               # how many small blocks `sample_values` reads from a large series
EPS = 1e-9


def bisect_array(array, x: float, side: str = "left") -> int:
    """`np.searchsorted` for a sorted array-like that must not be loaded whole: about log2(n)
    single-element reads. Works on anything with `len` and integer indexing."""
    lo, hi = 0, len(array)
    while lo < hi:
        mid = (lo + hi) // 2
        value = array[mid]
        if (value < x) if side == "left" else (value <= x):
            lo = mid + 1
        else:
            hi = mid
    return lo


def minmax_indices(values: np.ndarray, max_points: int) -> np.ndarray:
    """Indices of at most about `max_points` samples that keep the shape of a dense signal: the
    lowest and highest sample of each equal-sized bucket, in time order. Plotting these looks the
    same as plotting everything, so a million samples need only a couple of thousand points."""
    n = len(values)
    buckets = max(max_points // 2, 1)
    size = -(-n // buckets)
    full = n // size * size
    body = values[:full].reshape(-1, size)
    base = np.arange(body.shape[0]) * size
    picks = np.sort(np.stack([base + body.argmin(axis=1), base + body.argmax(axis=1)], axis=1), axis=1).ravel()
    if full < n:
        tail = values[full:]
        picks = np.concatenate([picks, np.sort([full + tail.argmin(), full + tail.argmax()])])
    return picks


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

    @property
    def first_time(self) -> float:
        return float(self.times[0])

    @property
    def last_time(self) -> float:
        return float(self.times[-1])

    def coverage(self, gap_factor: float = 3.0) -> np.ndarray:
        """Where samples exist: an (k, 2) array of [start, stop] runs.

        A run ends wherever the spacing between consecutive samples exceeds `gap_factor`
        times the typical spacing, so dropouts show up as gaps between runs.
        """
        times = self.times
        if len(times) == 0:
            return np.empty((0, 2))
        typical = float(np.median(np.diff(times))) if len(times) > 2 else 0.0
        if typical <= 0.0:
            return np.array([[times[0], times[-1]]])
        breaks = np.flatnonzero(np.diff(times) > gap_factor * typical)
        starts = np.concatenate([[times[0]], times[breaks + 1]])
        stops = np.concatenate([times[breaks], [times[-1]]])
        return np.column_stack([starts, stops])

    def count_between(self, start: float, stop: float) -> int:
        """How many samples have start <= time < stop."""
        return int(np.searchsorted(self.times, stop, side="left") - np.searchsorted(self.times, start, side="left"))

    def window(self, start: float, stop: float, max_points: int | None = None) -> TimeSeries:
        """Samples with start <= time < stop (a view; nothing is copied). With `max_points`, a
        window with more samples than that is reduced to its lowest and highest samples per bucket."""
        lo = int(np.searchsorted(self.times, start, side="left"))
        hi = int(np.searchsorted(self.times, stop, side="left"))
        times, values = self.times[lo:hi], self.values[lo:hi]
        if max_points is not None and len(values) > max_points and values.ndim == 1:
            picks = minmax_indices(values, max_points)
            times, values = times[picks], values[picks]
        return TimeSeries(times, values, self.unit, self.name, self.metadata)

    def sample_values(self, count: int = 100_000) -> np.ndarray:
        """About `count` values spread through the series, for choosing an axis range."""
        step = max(len(self.values) // count, 1)
        return np.asarray(self.values[::step])

    def time_base(self):
        """The ticks of this series, to step from sample to sample (None if it has no samples)."""
        from syncviz.core.stepping import SampleTimes

        return SampleTimes(self.times) if len(self) else None


class LazyTimeSeries:
    """A time series whose samples stay where they are and are read a window at a time.

    `data` is any array-like with `len` and slicing. The time axis is either regular (`start` and
    `rate`, nothing stored) or explicit (`times`, another array-like, searched without loading it).
    `scale` and `offset` turn stored numbers into `unit`s (for example raw integers into volts).
    """

    def __init__(self, data, *, times=None, start: float = 0.0, rate: float | None = None,
                 scale: float = 1.0, offset: float = 0.0, unit: str = "", name: str = "",
                 metadata: dict | None = None) -> None:
        if (times is None) == (rate is None):
            raise ValueError("give either explicit times or a start and rate")
        if times is not None and len(times) != len(data):
            raise ValueError("times must have one entry per sample")
        if rate is not None and rate <= 0:
            raise ValueError("rate must be positive")
        self.data, self._times = data, times
        self.start, self.rate = float(start), rate
        self.scale, self.offset = float(scale), float(offset)
        self.unit, self.name = unit, name
        self.metadata = metadata or {}

    def __len__(self) -> int:
        return len(self.data)

    # -- the time axis -------------------------------------------------------------------
    def _time_of(self, index: int) -> float:
        return float(self._times[index]) if self._times is not None else self.start + index / self.rate

    @property
    def first_time(self) -> float:
        return self._time_of(0)

    @property
    def last_time(self) -> float:
        return self._time_of(len(self) - 1)

    def _index(self, time: float) -> int:
        """Number of samples before `time` (what `np.searchsorted(times, time)` would give)."""
        if self._times is not None:
            return bisect_array(self._times, time, "left")
        return min(max(math.ceil((time - self.start) * self.rate - EPS), 0), len(self))

    def _times_of(self, lo: int, hi: int, step: int = 1) -> np.ndarray:
        if self._times is not None:
            return np.asarray(self._times[lo:hi:step], dtype=float)
        return self.start + np.arange(lo, hi, step) / self.rate

    def count_between(self, start: float, stop: float) -> int:
        return max(self._index(stop) - self._index(start), 0)

    # -- reading -------------------------------------------------------------------------
    def _scaled(self, raw) -> np.ndarray:
        values = np.asarray(raw)
        if self.scale != 1.0 or self.offset != 0.0:
            values = values.astype(float) * self.scale + self.offset
        return values

    def window(self, start: float, stop: float, max_points: int | None = None) -> TimeSeries:
        """The samples with start <= time < stop, read from the file now and nothing else. A window
        too large to read in full is read thinned; with `max_points`, a dense window is reduced to
        the lowest and highest samples per bucket."""
        lo, hi = self._index(start), self._index(stop)
        if hi <= lo:
            return TimeSeries(np.empty(0), np.empty(0), self.unit, self.name, self.metadata)
        step = -(-(hi - lo) // MAX_BLOCK_READ)
        values = self._scaled(self.data[lo:hi:step])
        times = self._times_of(lo, hi, step)
        if max_points is not None and len(values) > max_points and values.ndim == 1:
            picks = minmax_indices(values, max_points)
            times, values = times[picks], values[picks]
        return TimeSeries(times, values, self.unit, self.name, self.metadata)

    def sample_values(self, count: int = 100_000) -> np.ndarray:
        """About `count` values from small blocks spread through the series, for choosing an axis
        range. Blocks rather than every n-th sample: striding through stored data reads all of it."""
        n = len(self)
        if n <= count:
            return self._scaled(self.data[:])
        block = max(count // SAMPLE_BLOCKS, 1)
        starts = np.linspace(0, n - block, SAMPLE_BLOCKS).astype(int)
        return self._scaled(np.concatenate([np.asarray(self.data[s:s + block]) for s in starts]))

    def coverage(self, gap_factor: float = 3.0) -> np.ndarray:
        """Where samples exist, as `TimeSeries.coverage`. A regular series has no gaps. An explicit
        time axis is scanned once in chunks, so memory stays small however long it is."""
        n = len(self)
        if n == 0:
            return np.empty((0, 2))
        if self._times is None:
            return np.array([[self.first_time, self.last_time]])
        runs, typical, run_start, previous = [], None, self.first_time, self.first_time
        for lo in range(0, n, COVERAGE_CHUNK):
            chunk = np.asarray(self._times[lo:lo + COVERAGE_CHUNK], dtype=float)
            if typical is None:
                typical = float(np.median(np.diff(chunk))) if len(chunk) > 2 else 0.0
                if typical <= 0.0:
                    return np.array([[self.first_time, self.last_time]])
            seq = chunk if lo == 0 else np.concatenate([[previous], chunk])
            for b in np.flatnonzero(np.diff(seq) > gap_factor * typical):
                runs.append((run_start, float(seq[b])))
                run_start = float(seq[b + 1])
            previous = float(seq[-1])
        runs.append((run_start, previous))
        return np.array(runs)

    def time_base(self):
        from syncviz.core.stepping import LazySampleTimes, RegularGrid

        if len(self) == 0:
            return None
        if self._times is None:
            return RegularGrid(rate=self.rate, count=len(self), origin=self.start)
        return LazySampleTimes(self._times)
