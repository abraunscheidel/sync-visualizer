"""Inspecting data: what a point on screen refers to (a `Target`) and what is known about it (`Details`).

Design doc section 28.7. A view only says what is under a point. The facts about it come from here, from the
resource's type and the metadata the source attached, so every view and every source gets the same behaviour
and the core never learns what a "unit" or a "whisker" is. Nothing here draws anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries


@dataclass(frozen=True)
class Target:
    """Something a view can point at: a data item, named by where it lives, never by what it means."""

    source: str
    path: str
    kind: str                     # events | intervals | timeseries | points
    member: str | None = None     # which part of a container
    label: str = ""               # the name the interface shows
    time: float | None = None     # a specific moment, when the target is one (a single event, a point on a trace)

    @property
    def ref(self) -> str:
        return f"{self.source}:{self.path}"


@dataclass(frozen=True)
class Scope:
    """The stretch of time a statistic is worked out over. `None` bounds mean the whole recording."""

    label: str
    start: float | None = None
    stop: float | None = None

    def clip(self, lo: float, hi: float) -> tuple[float, float]:
        return (lo if self.start is None else self.start), (hi if self.stop is None else self.stop)


WHOLE = Scope("whole recording")


@dataclass
class Field:
    name: str
    value: str
    group: str = ""
    brief: bool = False           # worth showing in a hover, not only in the full panel


@dataclass
class Details:
    title: str
    description: str = ""
    fields: list[Field] = field(default_factory=list)
    scope: Scope = WHOLE

    def brief(self) -> list[Field]:
        return [f for f in self.fields if f.brief]


def _number(value: float) -> str:
    return f"{value:.3g}" if abs(value) < 1000 else f"{value:,.0f}"


def _scoped_range(scope: Scope, lo: float, hi: float) -> tuple[float, float]:
    a, b = scope.clip(lo, hi)
    return a, max(b, a)


def event_fields(series: EventSeries, scope: Scope = WHOLE) -> list[Field]:
    """Counts and rates of an event series, in `scope`, and the metadata the source attached."""
    out: list[Field] = []
    times = series.times
    if len(times):
        a, b = _scoped_range(scope, float(times[0]), float(times[-1]))
        inside = times[np.searchsorted(times, a, side="left"):np.searchsorted(times, b, side="right")]
        out.append(Field(f"Events ({scope.label})", str(len(inside)), "Statistics", brief=True))
        if b > a:
            out.append(Field(f"Rate ({scope.label})", f"{len(inside) / (b - a):.3g} per second", "Statistics", brief=True))
        if len(inside) > 1:
            out.append(Field(f"Typical gap ({scope.label})", f"{np.median(np.diff(inside)) * 1000:.3g} ms", "Statistics"))
        if scope is not WHOLE:
            out.append(Field("Events (whole recording)", str(len(times)), "Statistics"))
    else:
        out.append(Field("Events", "0", "Statistics", brief=True))
    out += metadata_fields(series.metadata)
    return out


def interval_fields(series: IntervalSeries, scope: Scope = WHOLE) -> list[Field]:
    out: list[Field] = []
    if len(series):
        a, b = _scoped_range(scope, float(series.starts.min()), float(series.stops.max()))
        keep = (series.starts < b) & (series.stops > a)
        out.append(Field(f"Intervals ({scope.label})", str(int(keep.sum())), "Statistics", brief=True))
        if keep.any():
            typical = np.median((series.stops - series.starts)[keep]) * 1000
            out.append(Field("Typical duration", f"{typical:.3g} ms", "Statistics", brief=True))
        if scope is not WHOLE:
            out.append(Field("Intervals (whole recording)", str(len(series)), "Statistics"))
    else:
        out.append(Field("Intervals", "0", "Statistics", brief=True))
    return out


def timeseries_fields(series, scope: Scope = WHOLE) -> list[Field]:
    """Range of a time series in `scope` (read thinned, so a long recording is not loaded to answer a hover)."""
    if len(series) == 0:
        return [Field("Samples", "0", "Statistics", brief=True)]
    a, b = _scoped_range(scope, float(series.first_time), float(series.last_time))
    window = series.window(a, b, max_points=20000)
    values = np.asarray(window.values, dtype=float)
    values = values[np.isfinite(values)] if values.ndim == 1 else np.array([])
    unit = f" {series.unit}" if getattr(series, "unit", "") else ""
    out: list[Field] = []
    if values.size:
        out.append(Field(f"Lowest ({scope.label})", _number(float(values.min())) + unit, "Statistics", brief=True))
        out.append(Field(f"Highest ({scope.label})", _number(float(values.max())) + unit, "Statistics", brief=True))
    out.append(Field(f"Samples ({scope.label})", str(series.count_between(a, b)), "Statistics"))
    return out


def metadata_fields(metadata: dict) -> list[Field]:
    """What the source attached to an item (a unit's depth and layer), shown as given."""
    return [Field(str(k), _plain(v), "From the file") for k, v in metadata.items()]


def _plain(value) -> str:
    if isinstance(value, (float, np.floating)):
        return _number(float(value))
    return str(value)
