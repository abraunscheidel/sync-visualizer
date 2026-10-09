"""Epochs: stretches of time cut out around things that happen, and what happens inside segments (design doc 28.9, 28.11).

Pure operations on the generic resources, with no knowledge of what the events are:

* `measure` counts the events (or intervals) that fall in each segment, so "trials where whisker C0 touched" becomes an
  attribute of the trials like any other, and the ordinary filters work on it.
* `epochs_from_sources` makes a new set of segments, a window around each event, that carries the attributes of the segment
  each one falls in. Each source of events has its own window (time before, time after) and, for an event that lasts, an
  anchor: the whole interval, or just its start or its end. Windows that overlap are merged, so what any source asked for is
  never left out and segments never overlap, which keeps navigating them simple.

Both return values the navigator and filters already understand: an `IntervalSeries` with attributes.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries

EDGES = ("overlap", "start", "stop")
UNBOUNDED = 1.0e9                          # seconds: the edges of a segment that is the whole recording, whatever its length
ANCHORS = ("span", "start", "stop")        # what an event that lasts is cut around: all of it, its start, or its end


def count_in_segments(segments: IntervalSeries, events, edge: str = "overlap") -> np.ndarray:
    """How many of `events` fall in each segment: an `EventSeries` counts its instants in [start, stop); an
    `IntervalSeries` counts those whose `edge` is in the segment, or for "overlap" those that overlap it at all."""
    if edge not in EDGES:
        raise ValueError(f"edge must be one of {EDGES}, got {edge!r}")
    starts, stops = segments.starts, segments.stops
    if isinstance(events, EventSeries):
        times = events.times
        return np.searchsorted(times, stops, side="left") - np.searchsorted(times, starts, side="left")
    if edge == "overlap":
        # An interval overlaps [a, b) when it starts before b and stops after a. Sorting both edges makes this a pair
        # of counts: those that start before b, minus those that already stopped by a.
        began = np.searchsorted(np.sort(events.starts), stops, side="left")
        ended = np.searchsorted(np.sort(events.stops), starts, side="right")
        return began - ended
    edge_times = np.sort(events.starts if edge == "start" else events.stops)
    return np.searchsorted(edge_times, stops, side="left") - np.searchsorted(edge_times, starts, side="left")


def measure(segments: IntervalSeries, name: str, events, edge: str = "overlap", as_: str = "count",
            labels: tuple[str, str] = ("no", "yes"), description: str = "") -> IntervalSeries:
    """`segments` with one more attribute, `name`: the number of events in each segment (`as_="count"`), or whether there
    were any (`as_="presence"`, written as `labels` = (without, with))."""
    counts = count_in_segments(segments, events, edge)
    if as_ == "presence":
        values = np.where(counts > 0, labels[1], labels[0])
    elif as_ == "count":
        values = counts
    else:
        raise ValueError(f"as must be 'count' or 'presence', got {as_!r}")
    descriptions = {**segments.descriptions, **({name: description} if description else {})}
    return replace(segments, attributes={**segments.attributes, name: values}, descriptions=descriptions)


@dataclass(frozen=True)
class EpochSource:
    """Events to cut windows around: instants (`stops` is None) or intervals, with their own window in seconds."""

    starts: np.ndarray
    stops: np.ndarray | None = None
    before: float = 0.0
    after: float = 0.0
    anchor: str = "span"

    def windows(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """(window start, window stop, the moment that decides which parent segment it belongs to)."""
        if self.before < 0 or self.after < 0:
            raise ValueError("before and after must not be negative")
        if self.anchor not in ANCHORS:
            raise ValueError(f"anchor must be one of {ANCHORS}, got {self.anchor!r}")
        starts = np.asarray(self.starts, dtype=float)
        if self.stops is None:
            return starts - self.before, starts + self.after, starts
        stops = np.asarray(self.stops, dtype=float)
        if self.anchor == "span":
            return starts - self.before, stops + self.after, starts
        if self.anchor == "start":
            return starts - self.before, starts + self.after, starts
        return stops - self.before, stops + self.after, stops


def epochs_from_sources(sources, parent: IntervalSeries | None = None, merge: bool = True, count_name: str = "Events",
                        parent_name: str = "Segment", name: str = "") -> IntervalSeries:
    """A window around every event of every source, each source with its own window.

    With a `parent`, a window is clipped to the parent segment the event falls in and takes that segment's attributes; an
    event outside every parent segment gets no window. Overlapping windows (within one parent) are merged into one when
    `merge` is on, so nothing any source asked for is left out; `count_name` says how many events each window holds, and
    `parent_name` names the attribute saying which parent segment (1-based) a window is in."""
    parts = [source.windows() for source in sources]
    if parts:
        starts, stops, when = (np.concatenate([p[i] for p in parts]) for i in range(3))
    else:
        starts = stops = when = np.zeros(0)
    order = np.argsort(starts, kind="stable")
    starts, stops, when = starts[order], stops[order], when[order]
    owner = np.full(len(starts), -1, dtype=int)
    if parent is not None and len(starts):
        index = np.searchsorted(parent.starts, when, side="right") - 1
        inside = (index >= 0) & (when < parent.stops[np.clip(index, 0, None)])
        keep = inside
        starts, stops, when = starts[keep], stops[keep], when[keep]
        owner = index[keep]
        starts = np.maximum(starts, parent.starts[owner])
        stops = np.minimum(stops, parent.stops[owner])
    counts = np.ones(len(starts), dtype=int)
    if merge and len(starts):
        begin, finish, who, holds = [starts[0]], [stops[0]], [owner[0]], [1]
        for s, e, o in zip(starts[1:], stops[1:], owner[1:]):
            if s <= finish[-1] and o == who[-1]:                  # touches the previous window of the same parent
                finish[-1] = max(finish[-1], e)
                holds[-1] += 1
            else:
                begin.append(s); finish.append(e); who.append(o); holds.append(1)
        starts, stops, owner, counts = np.array(begin), np.array(finish), np.array(who, dtype=int), np.array(holds)
    attributes: dict[str, np.ndarray] = {}
    descriptions: dict[str, str] = {}
    if parent is not None:
        attributes = {k: np.asarray(v)[owner] for k, v in parent.attributes.items()}
        descriptions = dict(parent.descriptions)
        attributes[parent_name] = owner + 1                       # which parent segment, for navigating back
    attributes[count_name] = counts
    return IntervalSeries(starts, stops, attributes, name=name, descriptions=descriptions)


def derive_epochs(times, before: float, after: float, parent: IntervalSeries | None = None, merge: bool = True,
                  count_name: str = "Events", parent_name: str = "Segment", name: str = "") -> IntervalSeries:
    """A window from `before` seconds earlier to `after` seconds later around each of one list of instants."""
    return epochs_from_sources([EpochSource(np.asarray(times, dtype=float), None, before, after)], parent, merge,
                               count_name, parent_name, name)
