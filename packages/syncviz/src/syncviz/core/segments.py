"""Navigating a set of intervals ("segments") one at a time.

The core only knows "segments". Whether they are shown as trials, epochs or
bouts is the `label`, which comes from the project configuration.
"""

from __future__ import annotations

from bisect import bisect_left
from typing import Any, Callable

import numpy as np

from syncviz.core.actions import ActionBus, SelectSegment, SelectTimeRange, Seek, StepSegment
from syncviz.resources import IntervalSeries


class SegmentNavigator:
    """The current segment of an interval series, and a filter saying which ones match.

    The filter and the movement are separate things:

    * the filter decides which segments *match* (`is_match`, `match_count`);
    * `skip_hidden` decides whether movement is *restricted* to those. On, every way of
      moving the playhead is kept inside the matching segments: stepping between segments,
      playback, stepping by frame, clicking or dragging. Off, none of them is, and the filter
      only marks which segments match, so the current segment may be one that does not.

    Once attached to a timeline with `follow`, the current segment tracks the playhead and the
    navigator becomes the timeline's constraint, so no method of navigating can bypass the filter.
    """

    def __init__(
        self,
        bus: ActionBus,
        intervals: IntervalSeries,
        label: str = "Segment",
        index_attribute: str | None = None,
        label_plural: str | None = None,
    ) -> None:
        if len(intervals) == 0:
            raise ValueError("cannot navigate an empty interval series")
        self.bus = bus
        self.intervals = intervals
        self.label = label                         # display text only, from the project configuration
        self.plural = label_plural or f"{label}s"  # for irregular plurals ("Stimulus" -> "Stimuli") set it in the config
        self.index_attribute = index_attribute     # attribute shown as the segment's number
        self._skip_hidden = True
        self._all = range(len(intervals))
        self._observers: list[Callable[[SegmentNavigator], None]] = []
        self._timeline = None                      # set by follow()
        self._set_visible(list(self._all))
        self._current = 0                          # index into the full series
        bus.subscribe(SelectSegment, lambda a: self.select(a.index))
        bus.subscribe(StepSegment, lambda a: self.step(a.step))

    def subscribe(self, observer: Callable[[SegmentNavigator], None]) -> None:
        self._observers.append(observer)

    def _set_visible(self, visible: list[int]) -> None:
        self._visible = visible                    # the segments matching the filter, ascending
        self._visible_set = set(visible)
        self._visible_starts = self.intervals.starts[visible]
        self._visible_stops = self.intervals.stops[visible]

    def _notify(self) -> None:
        for observer in list(self._observers):
            observer(self)

    # -- what is shown and where we are --------------------------------------------------
    @property
    def skip_hidden(self) -> bool:
        return self._skip_hidden

    @skip_hidden.setter
    def skip_hidden(self, value: bool) -> None:
        value = bool(value)
        if value == self._skip_hidden:
            return
        self._skip_hidden = value
        if value and self.filtered and self._current not in self._visible_set:
            self._move_to_next_match(self._reference_time())     # restricting: leave the hidden segment
        else:
            self._notify()

    @property
    def filtered(self) -> bool:
        return len(self._visible) != len(self.intervals)

    def is_match(self, index: int) -> bool:
        return index in self._visible_set

    @property
    def match_count(self) -> int:
        return len(self._visible)

    def _navigable(self) -> Any:
        """The segments movement may visit: the matching ones if restricted, else all of them."""
        return self._visible if self._skip_hidden else self._all

    @property
    def index(self) -> int:
        """Index into the full interval series of the current segment."""
        return self._current

    @property
    def matches(self) -> bool:
        """Whether the current segment matches the filter (always true when it is restricted)."""
        return self._current in self._visible_set

    @property
    def count(self) -> int:
        """How many segments movement may visit."""
        return len(self._navigable())

    @property
    def position(self) -> int:
        """Zero-based position of the current segment among those movement may visit."""
        return min(bisect_left(self._navigable(), self._current), self.count - 1)

    @property
    def number(self) -> Any:
        """The segment's own number if `index_attribute` is set, else its 1-based index."""
        if self.index_attribute is not None:
            return self.intervals.attributes[self.index_attribute][self._current].item()
        return self._current + 1

    @property
    def bounds(self) -> tuple[float, float]:
        return float(self.intervals.starts[self._current]), float(self.intervals.stops[self._current])

    def _reference_time(self) -> float:
        return self._timeline.time if self._timeline is not None else float(self.intervals.starts[self._current])

    # -- following the timeline ----------------------------------------------------------
    def follow(self, timeline) -> None:
        """Keep the current segment in step with the playhead, and let the filter govern where
        the playhead may go (see `resolve`)."""
        self._timeline = timeline
        timeline.constraint = self
        timeline.subscribe(self._on_timeline)

    @property
    def restricting(self) -> bool:
        """Whether the playhead is currently kept inside the matching segments."""
        return self._skip_hidden and self.filtered

    def allows(self, time: float) -> bool:
        """Whether the playhead may be at `time`: anywhere when not restricting, otherwise only
        inside a matching segment."""
        if not self.restricting:
            return True
        i = int(np.searchsorted(self._visible_starts, time, side="right")) - 1
        return i >= 0 and time < self._visible_stops[i]

    def resolve(self, time: float, previous: float) -> float:
        """The timeline's constraint: while restricting, nothing may move the playhead outside the
        segments that match the filter, whether it is playback, stepping, clicking or dragging.

        A time outside them goes to the start of the next matching segment when moving forward, to
        the end of the previous one when moving backward, and to the end of the last match when
        nothing matching lies ahead.
        """
        if self.allows(time):
            return time
        i = int(np.searchsorted(self._visible_starts, time, side="right")) - 1     # last match starting at or before time
        if time >= previous:                                                         # moving forward (or staying put)
            if i + 1 < len(self._visible):
                return float(self._visible_starts[i + 1])
            return float(np.nextafter(self._visible_stops[-1], -np.inf))
        if i >= 0:
            return float(np.nextafter(self._visible_stops[i], -np.inf))
        return float(self._visible_starts[0])

    def _on_timeline(self, timeline) -> None:
        i = self.intervals.index_at(timeline.time)
        if i is not None and i != self._current:   # the playhead has entered another segment
            self._current = i
            self.bus.publish(SelectTimeRange(*self.bounds))
            self._notify()

    def replace_intervals(self, intervals: IntervalSeries) -> None:
        """Navigate a different set of segments (another collection's), starting at its first one.
        The filter is cleared, since its choices belonged to the old segments; whether movement is
        restricted to matches is kept."""
        if len(intervals) == 0:
            raise ValueError("cannot navigate an empty interval series")
        self.intervals = intervals
        self._all = range(len(intervals))
        self._set_visible(list(self._all))
        self._current = 0
        self._announce()

    # -- explicit navigation -------------------------------------------------------------
    def _announce(self) -> None:
        start, stop = self.bounds
        self.bus.publish(SelectTimeRange(start, stop))
        self.bus.publish(Seek(start))
        self._notify()

    def select(self, index: int) -> None:
        """Go to the segment with this index in the full series."""
        if not 0 <= index < len(self.intervals):
            raise IndexError(f"segment {index} does not exist")
        if self._skip_hidden and index not in self._visible_set:
            raise IndexError(f"segment {index} is not visible under the current filter")
        self._current = index
        self._announce()

    def step(self, step: int) -> None:
        navigable = self._navigable()
        position = bisect_left(navigable, self._current)
        if position < len(navigable) and navigable[position] == self._current:
            target = position + step
        else:                                      # the current segment is not one movement may visit
            target = position if step > 0 else position - 1
        target = min(max(target, 0), len(navigable) - 1)
        if navigable[target] != self._current:
            self._current = navigable[target]
            self._announce()

    def facet_counts(self, attribute: str, **criteria: Any) -> dict[Any, int]:
        """How many segments have each value of `attribute`, among those matching `criteria`.

        Used to show what each option of one filter would leave given the other filters, and
        to disable options that would leave nothing. Pass the *other* filters as criteria.
        """
        if attribute not in self.intervals.attributes:
            raise KeyError(f"no attribute {attribute!r} (available: {sorted(self.intervals.attributes)})")
        rows = self.intervals.select(**criteria) if criteria else np.arange(len(self.intervals))
        values, counts = np.unique(self.intervals.attributes[attribute][rows], return_counts=True)
        return dict(zip(values.tolist(), counts.tolist()))

    def _move_to_next_match(self, reference: float) -> None:
        """Go to the first matching segment after `reference`, else the last one before it."""
        ahead = int(np.searchsorted(self._visible_starts, reference, side="right"))
        self._current = self._visible[ahead if ahead < len(self._visible) else len(self._visible) - 1]
        self._announce()

    def filter(self, **criteria: Any) -> None:
        """Set which segments match. If movement is restricted to matches and the current
        segment no longer matches, move to the first match after the playhead (or the last one
        before it when none is left ahead), so changing a filter moves you as little as possible."""
        visible = self.intervals.select(**criteria).tolist()
        if not visible:
            raise ValueError(f"no segments match {criteria}")
        reference = self._reference_time()
        self._set_visible(visible)
        if not self._skip_hidden or self._current in self._visible_set:
            self._notify()                         # the playhead stays where it is
        else:
            self._move_to_next_match(reference)

    def clear_filter(self) -> None:
        self._set_visible(list(self._all))
        self._notify()
