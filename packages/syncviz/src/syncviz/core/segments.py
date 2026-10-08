"""Navigating a set of intervals ("segments") one at a time.

The core only knows "segments". Whether they are shown as trials, epochs or
bouts is the `label`, which comes from the project configuration.
"""

from __future__ import annotations

from typing import Any, Callable

from syncviz.core.actions import ActionBus, SelectSegment, SelectTimeRange, Seek, StepSegment
from syncviz.resources import IntervalSeries


class SegmentNavigator:
    """A current position within an interval series, optionally filtered by attributes."""

    def __init__(
        self,
        bus: ActionBus,
        intervals: IntervalSeries,
        label: str = "Segment",
        index_attribute: str | None = None,
    ) -> None:
        if len(intervals) == 0:
            raise ValueError("cannot navigate an empty interval series")
        self.bus = bus
        self.intervals = intervals
        self.label = label                         # display text only
        self.index_attribute = index_attribute     # attribute shown as the segment's number
        self._visible = list(range(len(intervals)))
        self._position = 0                         # position within the visible list
        self._observers: list[Callable[[SegmentNavigator], None]] = []
        bus.subscribe(SelectSegment, lambda a: self.select(a.index))
        bus.subscribe(StepSegment, lambda a: self.step(a.step))

    def subscribe(self, observer: Callable[[SegmentNavigator], None]) -> None:
        self._observers.append(observer)

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

    def _announce(self) -> None:
        start, stop = self.bounds
        self.bus.publish(SelectTimeRange(start, stop))
        self.bus.publish(Seek(start))
        for observer in list(self._observers):
            observer(self)

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

    def filter(self, **criteria: Any) -> None:
        """Show only matching segments. Keeps the current segment if it still matches."""
        visible = self.intervals.select(**criteria).tolist()
        if not visible:
            raise ValueError(f"no segments match {criteria}")
        current = self.index
        self._visible = visible
        if current in visible:
            self._position = visible.index(current)
            for observer in list(self._observers):
                observer(self)
        else:
            self._position = 0
            self._announce()

    def clear_filter(self) -> None:
        current = self.index
        self._visible = list(range(len(self.intervals)))
        self._position = current
        for observer in list(self._observers):
            observer(self)
