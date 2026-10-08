"""Base class for views: the panels a user can arrange in the window.

A view reads generic resources and draws them. It never talks to another view:
user gestures become actions on the bus, and the view redraws when told the
playhead has moved.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from syncviz_app.context import AppContext


class View(QWidget):
    type_name = ""
    default_refresh_hz = 30.0      # redraws per second while the playhead moves; see refresh.py

    def __init__(self, context: AppContext, spec: dict) -> None:
        super().__init__()
        self.context = context
        self.spec = spec
        self.title: str = spec.get("title") or self.type_name
        # Upper limit on how often this view redraws. A project can override it per view.
        self.refresh_hz: float = float(spec.get("refresh_hz", self.default_refresh_hz))

    def extent(self) -> tuple[float, float] | None:
        """Range of shared time this view has data for, or None if it has no time extent."""
        return None

    def time_base(self):
        """The grid of ticks this view's data naturally has (video frames, signal samples), as
        a `syncviz.core.TimeBase`, or None if it has no such grid. Offered to the user as a
        choice of what one "step" means."""
        return None

    def coverage(self) -> list[tuple[float, float]]:
        """Runs of shared time in which this view has data. Defaults to its whole extent;
        views whose data has real dropouts report them so the timeline can show the gaps."""
        extent = self.extent()
        return [] if extent is None else [extent]

    def stalled_for(self, now: float) -> float:
        """Seconds this view has been waiting, with no progress, for what it needs to show the
        current playhead position (0 if it is up to date or can answer immediately). Slow views
        such as a video decoding a distant frame override this; see `stall.py`."""
        return 0.0

    def refresh(self, time: float) -> None:
        """Redraw for the playhead at `time` (shared time). Only called while visible."""
        raise NotImplementedError

    def close_view(self) -> None:
        """Release resources (threads, files). Called when the window closes."""
