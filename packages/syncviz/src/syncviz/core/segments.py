"""Navigating a set of intervals ("segments") one at a time.

The core only knows "segments". Whether they are shown as trials, epochs or
bouts is the `label`, which comes from the project configuration.
"""

from __future__ import annotations

from typing import Any, Callable

import numpy as np

from syncviz.core.actions import ActionBus, SelectSegment, SelectTimeRange, Seek, SetPlaying, StepSegment
from syncviz.resources import IntervalSeries


class SegmentNavigator:
    """A current position within an interval series, optionally filtered by attributes.

    Once attached to a timeline with `follow`, the current segment tracks the playhead, and
    while a filter is active, playback skips over segments that do not match it.
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
        self.skip_hidden = True                    # while playing with a filter active, skip non-matching segments
        self._timeline = None                      # set by follow()
        self._observers: list[Callable[[SegmentNavigator], None]] = []
        self._set_visible(list(range(len(intervals))))
        self._position = 0                         # position within the visible list
        bus.subscribe(SelectSegment, lambda a: self.select(a.index))
        bus.subscribe(StepSegment, lambda a: self.step(a.step))

    def subscribe(self, observer: Callable[[SegmentNavigator], None]) -> None:
        self._observers.append(observer)

    def _set_visible(self, visible: list[int]) -> None:
        self._visible = visible
        self._visible_set = set(visible)
        self._visible_starts = self.intervals.starts[visible]

    def _notify(self) -> None:
        for observer in list(self._observers):
            observer(self)

    @property
    def filtered(self) -> bool:
        return len(self._visible) != len(self.intervals)

    @property
    def index(self) -> int:
        """Index into the full interval series of the current segment."""
        return self._visible[self._position]

    @property
    def count(self) -> int:
        return len(self._visible)

    @property
    def position(self) -> int:
        """Zero-based position among the visible segments."""
        return self._position

    @property
    def number(self) -> Any:
        """The segment's own number if `index_attribute` is set, else its 1-based position."""
        if self.index_attribute is not None:
            return self.intervals.attributes[self.index_attribute][self.index].item()
        return self._position + 1

    @property
    def bounds(self) -> tuple[float, float]:
        return float(self.intervals.starts[self.index]), float(self.intervals.stops[self.index])

    # -- following the timeline ----------------------------------------------------------
    def follow(self, timeline) -> None:
        """Track the playhead: keep the current segment in step with it, and skip while playing."""
        self._timeline = timeline
        timeline.subscribe(self._on_timeline)

    def _on_timeline(self, timeline) -> None:
        i = self.intervals.index_at(timeline.time)
        if i is not None and i in self._visible_set:
            if i != self.index:                    # the playhead has entered another matching segment
                self._position = self._visible.index(i)
                self.bus.publish(SelectTimeRange(*self.bounds))
                self._notify()
            return
        # The playhead is in a gap, or in a segment the filter hides. Seeking there by hand is
        # allowed; only playback is steered away from it.
        if not (timeline.playing and self.skip_hidden and self.filtered):
            return
        ahead = int(np.searchsorted(self._visible_starts, timeline.time, side="right"))
        if ahead < len(self._visible):
            self.select(self._visible[ahead])      # playback carries on from the next match
        else:                                      # nothing matching is left
            last_stop = float(self.intervals.stops[self._visible[-1]])
            self.bus.publish(SetPlaying(False))
            self.bus.publish(Seek(float(np.nextafter(last_stop, -np.inf))))

    # -- explicit navigation -------------------------------------------------------------
    def _announce(self) -> None:
        start, stop = self.bounds
        self.bus.publish(SelectTimeRange(start, stop))
        self.bus.publish(Seek(start))
        self._notify()

    def select(self, index: int) -> None:
        """Go to the segment with this index in the full series (must be visible)."""
        try:
            self._position = self._visible.index(index)
        except ValueError:
            raise IndexError(f"segment {index} is not visible under the current filter") from None
        self._announce()

    def step(self, step: int) -> None:
        position = min(max(self._position + step, 0), self.count - 1)
        if position != self._position:
            self._position = position
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

    def filter(self, **criteria: Any) -> None:
        """Show only matching segments. Keeps the current segment if it still matches.

        If the current segment is hidden, move to the first match after the playhead (or the
        last match before it when none is left ahead), so changing a filter moves you as
        little as possible.
        """
        visible = self.intervals.select(**criteria).tolist()
        if not visible:
            raise ValueError(f"no segments match {criteria}")
        current = self.index
        reference = self._timeline.time if self._timeline is not None else float(self.intervals.starts[current])
        self._set_visible(visible)
        if current in self._visible_set:
            self._position = visible.index(current)
            self._notify()
        else:
            ahead = int(np.searchsorted(self._visible_starts, reference, side="right"))
            self._position = ahead if ahead < len(visible) else len(visible) - 1
            self._announce()

    def clear_filter(self) -> None:
        current = self.index
        self._set_visible(list(range(len(self.intervals))))
        self._position = current
        self._notify()
