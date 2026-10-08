"""Epochs: stretches of time cut out around things that happen, and what happens inside segments (design doc 28.9).

Two pure operations on the generic resources, with no knowledge of what the events are:

* `measure` counts the events (or intervals) that fall in each segment, so "trials where whisker C0 touched" becomes an
  attribute of the trials like any other, and the ordinary filters work on it.
* `derive_epochs` makes a new set of segments, a window around each event, that carries the attributes of the segment each
  one falls in. Windows that overlap are merged, so segments never overlap and navigating them works unchanged.

Both return values the navigator and filters already understand: an `IntervalSeries` with attributes.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np

from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries

EDGES = ("overlap", "start", "stop")


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


def derive_epochs(times, before: float, after: float, parent: IntervalSeries | None = None, merge: bool = True,
                  count_name: str = "Events", parent_name: str = "Segment", name: str = "") -> IntervalSeries:
    """A window from `before` seconds earlier to `after` seconds later around each time.

    With a `parent`, a window is clipped to the parent segment its time falls in and takes that segment's attributes;
    a time outside every parent segment gets no window. Overlapping windows (within one parent) are merged into one when
    `merge` is on, and `count_name` says how many times each window holds. `parent_name` names the attribute that says which
    parent segment a window is in (1-based)."""
    if before < 0 or after < 0:
        raise ValueError("before and after must not be negative")
    times = np.sort(np.asarray(times, dtype=float))
    starts, stops = times - before, times + after
    owner = np.full(len(times), -1, dtype=int)
    if parent is not None and len(times):
        index = np.searchsorted(parent.starts, times, side="right") - 1
        inside = (index >= 0) & (times < parent.stops[np.clip(index, 0, None)])
        owner = np.where(inside, index, -1)
        keep = owner >= 0
        times, starts, stops, owner = times[keep], starts[keep], stops[keep], owner[keep]
        starts = np.maximum(starts, parent.starts[owner])
        stops = np.minimum(stops, parent.stops[owner])
    counts = np.ones(len(times), dtype=int)
    if merge and len(times):
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
        attributes[parent_name] = owner + 1                         # which parent segment (1-based), for navigating back
    attributes[count_name] = counts
    return IntervalSeries(starts, stops, attributes, name=name, descriptions=descriptions)
