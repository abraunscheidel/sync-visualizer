"""Inspecting data: what a point on screen refers to (a `Target`) and what is known about it (`Details`).

Design doc section 28.7. A view only says what is under a point. The facts about it come from here, from the
resource's type and the metadata the source attached, so every view and every source gets the same behaviour
and the core never learns what a "unit" or a "whisker" is. Nothing here draws anything.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from datetime import date, datetime

import numpy as np

from syncviz.formatting import DEFAULT as DEFAULT_DATES, DateFormat

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
    at: float | None = field(default=None, compare=False)    # the time under the pointer, for a view with a time axis

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


def same_item(a: "Target | None", b: "Target | None") -> bool:
    """Whether two targets are the same data item, ignoring which moment of it was pointed at."""
    return a is not None and b is not None and (a.source, a.path, a.kind, a.member) == (b.source, b.path, b.kind, b.member)


class Selection:
    """What the user has selected, shared by every view and panel like the playhead is (design doc 28.7, 28.11): any number of
    items, in the order they were chosen. Selecting never moves time or playback.

    A plain click replaces the selection with one item (`set`), Ctrl-click adds or removes one (`toggle`), Shift-click selects the
    run from the item last clicked to this one in the order the view lists its items (`extend`). `target` is the item chosen last,
    for views that can show only one."""

    def __init__(self) -> None:
        self.targets: list["Target"] = []
        self.anchor: "Target | None" = None           # where a Shift-click range starts: the item last clicked
        self.last_kind = "set"                        # how it last changed: set (started again), set_all, toggle or extend
        self._observers: list = []

    @property
    def target(self) -> "Target | None":
        return self.targets[-1] if self.targets else None

    def subscribe(self, observer) -> None:
        self._observers.append(observer)

    def _replace(self, targets: list["Target"]) -> None:
        if targets == self.targets:
            return
        self.targets = targets
        for observer in list(self._observers):
            try:
                observer(list(targets))
            except RuntimeError:                       # an observer whose widget has been deleted
                self._observers.remove(observer)

    def set(self, target: "Target | None") -> None:
        """Select just this item (or nothing)."""
        self.anchor = target
        self.last_kind = "set"
        self._replace([] if target is None else [target])

    def set_all(self, targets) -> None:
        """Select exactly these items."""
        unique: list["Target"] = []
        for t in targets:
            if not any(same_item(t, u) for u in unique):
                unique.append(t)
        self.anchor = unique[-1] if unique else None
        self.last_kind = "set_all"
        self._replace(unique)

    def toggle(self, target: "Target") -> None:
        """Add the item to the selection, or take it out if it is in."""
        self.anchor = target
        self.last_kind = "toggle"
        if self.is_selected(target):
            self._replace([t for t in self.targets if not same_item(t, target)])
        else:
            self._replace(self.targets + [target])

    def extend(self, target: "Target", ordered: list["Target"]) -> None:
        """Select the run of `ordered` (the view's items, in its order) from the item last clicked to this one. Without a usable
        starting point it selects just this item."""
        position = next((i for i, t in enumerate(ordered) if same_item(t, target)), None)
        start = next((i for i, t in enumerate(ordered) if same_item(t, self.anchor)), None)
        if position is None or start is None:
            self.set(target)
            return
        lo, hi = sorted((start, position))
        self.last_kind = "extend"
        self._replace(list(ordered[lo:hi + 1]))        # the anchor stays, so a longer or shorter run can follow

    def clear(self) -> None:
        self.set(None)

    def is_selected(self, target: "Target | None") -> bool:
        return any(same_item(t, target) for t in self.targets)


@dataclass
class Field:
    name: str
    value: str
    group: str = ""
    brief: bool = False           # worth showing in a hover by default, not only in the full panel
    key: str = ""                 # stable name for choosing which figures a hover shows (the label changes with the scope)

    def __post_init__(self) -> None:
        if not self.key:
            self.key = self.name


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


def event_fields(series: EventSeries, scope: Scope = WHOLE, dates: DateFormat = DEFAULT_DATES) -> list[Field]:
    """Counts and rates of an event series, in `scope`, and the metadata the source attached."""
    out: list[Field] = []
    times = series.times
    if len(times):
        a, b = _scoped_range(scope, float(times[0]), float(times[-1]))
        inside = times[np.searchsorted(times, a, side="left"):np.searchsorted(times, b, side="right")]
        out.append(Field(f"Events ({scope.label})", str(len(inside)), "Statistics", brief=True, key="events"))
        if b > a:
            out.append(Field(f"Rate ({scope.label})", f"{len(inside) / (b - a):.3g} per second", "Statistics", brief=True, key="rate"))
        if len(inside) > 1:
            out.append(Field(f"Typical gap ({scope.label})", f"{np.median(np.diff(inside)) * 1000:.3g} ms", "Statistics", key="gap"))
        if scope is not WHOLE:
            out.append(Field("Events (whole recording)", str(len(times)), "Statistics", key="events_all"))
    else:
        out.append(Field("Events", "0", "Statistics", brief=True, key="events"))
    out += metadata_fields(series.metadata, dates)
    return out


def interval_fields(series: IntervalSeries, scope: Scope = WHOLE) -> list[Field]:
    out: list[Field] = []
    if len(series):
        a, b = _scoped_range(scope, float(series.starts.min()), float(series.stops.max()))
        keep = (series.starts < b) & (series.stops > a)
        out.append(Field(f"Intervals ({scope.label})", str(int(keep.sum())), "Statistics", brief=True, key="intervals"))
        if keep.any():
            typical = np.median((series.stops - series.starts)[keep]) * 1000
            out.append(Field("Typical duration", f"{typical:.3g} ms", "Statistics", brief=True, key="duration"))
        if scope is not WHOLE:
            out.append(Field("Intervals (whole recording)", str(len(series)), "Statistics", key="intervals_all"))
    else:
        out.append(Field("Intervals", "0", "Statistics", brief=True, key="intervals"))
    return out


def timeseries_fields(series, scope: Scope = WHOLE) -> list[Field]:
    """Range of a time series in `scope` (read thinned, so a long recording is not loaded to answer a hover)."""
    if len(series) == 0:
        return [Field("Samples", "0", "Statistics", brief=True, key="samples")]
    a, b = _scoped_range(scope, float(series.first_time), float(series.last_time))
    window = series.window(a, b, max_points=20000)
    values = np.asarray(window.values, dtype=float)
    values = values[np.isfinite(values)] if values.ndim == 1 else np.array([])
    unit = f" {series.unit}" if getattr(series, "unit", "") else ""
    out: list[Field] = []
    if values.size:
        out.append(Field(f"Lowest ({scope.label})", _number(float(values.min())) + unit, "Statistics", brief=True, key="lowest"))
        out.append(Field(f"Highest ({scope.label})", _number(float(values.max())) + unit, "Statistics", brief=True, key="highest"))
    out.append(Field(f"Samples ({scope.label})", str(series.count_between(a, b)), "Statistics", key="samples"))
    return out


def metadata_fields(metadata: dict, dates: DateFormat = DEFAULT_DATES) -> list[Field]:
    """What the source attached to an item (a unit's depth and layer), shown as given."""
    return [Field(str(k), _plain(v, dates), "From the file", key=f"file:{k}") for k, v in metadata.items()]


def _plain(value, dates: DateFormat = DEFAULT_DATES) -> str:
    if isinstance(value, (datetime, date)):
        return dates.show(value)
    if isinstance(value, (float, np.floating)):
        return _number(float(value))
    return str(value)
