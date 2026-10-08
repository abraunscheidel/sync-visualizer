"""Deciding when views redraw, so the interface stays responsive while playing.

Redrawing everything on every playhead change can use nearly all of the main thread
during playback, leaving no time to react to clicks. Two mechanisms prevent that:

* each view has its own redraw rate (a scrolling plot looks the same at 30 per second as
  at 60, and the video is the thing that needs the full rate);
* a governor measures how late the app's own timer fires. When it is falling behind, every
  rate is lowered until it keeps up, and raised again when there is headroom. That adapts to
  the machine and the screen instead of assuming either.

A view that has not drawn the latest playhead position is always brought up to date, so the
final state after a seek or when playback stops is never skipped.
"""

from __future__ import annotations

from typing import Protocol, Sequence

PUMP_INTERVAL_S = 0.008          # how often the scheduler looks at the views
GOVERNOR_WINDOW_S = 0.25         # how long to observe before adjusting
LATE_S = 0.006                   # the timer firing this late on typical ticks means we are saturated
RELAXED_S = 0.003                # ...and this early means there is headroom
BACK_OFF = 1.3
RECOVER = 1.15
MAX_SCALE = 6.0


class Governor:
    """Scale factor applied to every view's redraw interval (1.0 = no limiting)."""

    def __init__(self, pump_interval: float = PUMP_INTERVAL_S, window: float = GOVERNOR_WINDOW_S) -> None:
        self.pump_interval = pump_interval
        self.window = window
        self.scale = 1.0
        self._last: float | None = None
        self._window_start: float | None = None
        self._lateness: list[float] = []

    def tick(self, now: float) -> None:
        """Call once per scheduler pump with the current time in seconds."""
        if self._last is not None:
            self._lateness.append(max(0.0, (now - self._last) - self.pump_interval))
        self._last = now
        if self._window_start is None:
            self._window_start = now
        if now - self._window_start >= self.window and self._lateness:
            ordered = sorted(self._lateness)
            typical = ordered[int(len(ordered) * 0.75)]          # 75th percentile: ignore one-off hiccups
            if typical > LATE_S:
                self.scale = min(self.scale * BACK_OFF, MAX_SCALE)
            elif typical < RELAXED_S:
                self.scale = max(self.scale / RECOVER, 1.0)
            self._lateness.clear()
            self._window_start = now


class Refreshable(Protocol):
    refresh_hz: float

    def isVisible(self) -> bool: ...
    def refresh(self, time: float) -> None: ...


class RefreshScheduler:
    def __init__(self, views: Sequence[Refreshable], governor: Governor | None = None) -> None:
        self.views = views if isinstance(views, list) else list(views)     # shared: views come and go
        self.governor = governor or Governor()
        self._version = 0                                    # bumped whenever the playhead changes
        self._drawn = {id(v): -1 for v in self.views}        # version each view last drew
        self._due = {id(v): 0.0 for v in self.views}         # earliest time each may draw again

    def changed(self) -> None:
        self._version += 1

    def interval_for(self, view: Refreshable) -> float:
        return self.governor.scale / max(view.refresh_hz, 1.0)

    def pump(self, now: float, time_value: float, force: bool = False) -> None:
        self.governor.tick(now)
        for view in self.views:
            key = id(view)
            if self._drawn.get(key, -1) == self._version or not view.isVisible():
                continue                                     # up to date, or not on screen
            if not force and now < self._due.get(key, 0.0):
                continue
            view.refresh(time_value - getattr(view, "lag", 0.0))      # each view draws its own time (see View.lag)
            self._drawn[key] = self._version
            # Advance from the previous due time, not from now: the pump only looks every few
            # milliseconds, so scheduling from "now" would round every rate down to a multiple
            # of the pump interval (a 60 Hz view would get ~41 Hz). If we are already behind,
            # restart from now rather than drawing a burst to catch up.
            self._due[key] = max(self._due.get(key, now) + self.interval_for(view), now)
