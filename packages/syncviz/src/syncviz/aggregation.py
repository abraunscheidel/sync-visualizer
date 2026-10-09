"""Aggregation: what the data does around the moments that matter (design doc 28.17).

Pure functions. Given the times of an item's events (a unit's spikes) and the moments to align to (every contact, every trial start),
they work out the profile: the item's rate at each delay from the moment, averaged over the moments. Nothing here knows what the
item or the moment is. The profile keeps the moments it was made from, so a point of it can be traced back to the times it came from.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

EDGES = ("start", "stop")


def anchors_from(data, edge: str = "start") -> np.ndarray:
    """The moments to align to: an event series' own times, or the start (or stop) of each interval."""
    if edge not in EDGES:
        raise ValueError(f"edge must be one of {EDGES}")
    if hasattr(data, "starts"):
        return np.asarray(data.starts if edge == "start" else data.stops, dtype=float)
    return np.asarray(data.times, dtype=float)


def within_segments(times: np.ndarray, starts: np.ndarray, stops: np.ndarray) -> np.ndarray:
    """Only the moments that fall inside one of the (sorted, non-overlapping) segments."""
    times = np.asarray(times, dtype=float)
    if len(starts) == 0:
        return times[:0]
    i = np.searchsorted(starts, times, side="right") - 1
    inside = (i >= 0) & (times <= np.asarray(stops)[np.clip(i, 0, None)])
    return times[inside]


@dataclass(frozen=True)
class Profile:
    """An item's rate (events per second per member) at each delay from the moments it was aligned to."""

    edges: np.ndarray                  # bin edges in seconds from the moment (negative is before it)
    mean: np.ndarray                   # mean rate per bin over the moments
    sem: np.ndarray                    # standard error of that mean (zero with a single moment)
    moments: np.ndarray                # the times (shared time) the profile was aligned to, so a point resolves back to them
    members: int = 1                   # how many items were pooled (a group's units); the rate is per member
    per_moment: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))   # rate per moment and bin

    @property
    def centres(self) -> np.ndarray:
        return (self.edges[:-1] + self.edges[1:]) / 2

    @property
    def count(self) -> int:
        return len(self.moments)

    def window(self, low: float, high: float) -> np.ndarray:
        """The bins whose centre lies in [low, high) seconds from the moment."""
        return (self.centres >= low) & (self.centres < high)

    def mean_rate(self, low: float, high: float) -> float:
        picked = self.window(low, high)
        return float(self.mean[picked].mean()) if picked.any() else float("nan")

    def peak(self, low: float | None = None, high: float | None = None) -> tuple[float, float]:
        """(rate, delay in seconds) of the highest bin in [low, high), or the whole profile."""
        picked = self.window(-np.inf if low is None else low, np.inf if high is None else high)
        if not picked.any() or self.count == 0:
            return float("nan"), float("nan")
        at = int(np.flatnonzero(picked)[np.argmax(self.mean[picked])])
        return float(self.mean[at]), float(self.centres[at])

    def moments_in(self, delay_low: float, delay_high: float, rate_low: float | None = None) -> np.ndarray:
        """The moments whose rate over the delays [delay_low, delay_high) is at least `rate_low` (all of them if None): which
        moments make a feature of the profile, to take the viewer to them."""
        picked = self.window(delay_low, delay_high)
        if self.count == 0 or not picked.any():
            return self.moments[:0]
        rates = self.per_moment[:, picked].mean(axis=1)
        return self.moments if rate_low is None else self.moments[rates >= rate_low]


def aligned_rate(streams, moments, before: float, after: float, bin_size: float) -> Profile:
    """The rate of `streams` (one array of event times per item) around each of `moments`, from `before` seconds ahead of the
    moment to `after` seconds past it, in bins of `bin_size`. The rate is per item, so a group of three units reads as the average
    unit, not three times a unit."""
    if bin_size <= 0:
        raise ValueError("the bin size must be positive")
    if before < 0 or after < 0 or before + after <= 0:
        raise ValueError("the window must reach before or after the moment")
    moments = np.sort(np.asarray(moments, dtype=float))
    bins = max(int(round((before + after) / bin_size)), 1)
    edges = np.linspace(-before, after, bins + 1)
    streams = [np.sort(np.asarray(s, dtype=float)) for s in streams]
    members = max(len(streams), 1)
    counts = np.zeros((len(moments), bins))
    if len(moments):
        grid = moments[:, None] + edges[None, :]                          # every bin edge of every moment, in shared time
        for times in streams:
            counts += np.diff(np.searchsorted(times, grid, side="left"), axis=1)
    rate = counts / (np.diff(edges)[0] * members)          # (the window need not be a whole number of bins)
    if len(moments) == 0:
        return Profile(edges, np.zeros(bins), np.zeros(bins), moments, members, rate)
    mean = rate.mean(axis=0)
    sem = rate.std(axis=0, ddof=1) / np.sqrt(len(moments)) if len(moments) > 1 else np.zeros(bins)
    return Profile(edges, mean, sem, moments, members, rate)


@dataclass(frozen=True)
class ItemRow:
    """One line of the per-item table: how an item's rate after the moment compares with its rate before."""

    name: str
    moments: int
    before: float          # mean rate over the span before the moment
    after: float           # mean rate over the span after it
    peak: float
    peak_delay: float

    @property
    def change(self) -> float:
        return self.after - self.before


def item_row(name: str, profile: Profile, span: float) -> ItemRow:
    """Summarise a profile: the mean rate over the `span` seconds before the moment against the `span` seconds after it."""
    peak, delay = profile.peak(0.0, span)
    return ItemRow(name, profile.count, profile.mean_rate(-span, 0.0), profile.mean_rate(0.0, span), peak, delay)
