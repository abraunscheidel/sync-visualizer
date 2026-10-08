"""The shared timeline: one playhead in shared time that every view follows.

Pure state with no UI. A view's clock calls `advance`; user gestures arrive as
actions on the bus. Observers are told when anything changed.

Every way of moving the playhead (seeking, stepping, dragging, playback) passes through
this class, so a rule about *where the playhead may be* is enforced in one place by setting
a `constraint`, and no navigation method can bypass it.
"""

from __future__ import annotations

from typing import Callable, Protocol

from syncviz.core.actions import ActionBus, SelectTimeRange, Seek, SetPlaying


class Constraint(Protocol):
    def allows(self, time: float) -> bool:
        """Whether the playhead may be at `time`."""

    def resolve(self, time: float, previous: float) -> float:
        """Where the playhead should actually go when asked to move from `previous` to `time`.

        Return `time` if it is allowed. Otherwise return the nearest allowed time in the
        direction of travel: later than `time` if moving forward (a jump ahead), earlier if no
        allowed time lies ahead or if moving backward.
        """


class Timeline:
    def __init__(self, bus: ActionBus, start: float, stop: float, rate: float = 1.0) -> None:
        if stop <= start:
            raise ValueError("timeline must have positive length")
        self.start = start
        self.stop = stop
        self.rate = rate                       # playback speed; 1.0 is real time
        self.time = start
        self.playing = False
        self.holding: str | None = None        # why the clock is waiting (e.g. a view is loading); playing stays on
        self.selection: tuple[float, float] | None = None
        self.constraint: Constraint | None = None
        self._observers: list[Callable[[Timeline], None]] = []
        bus.subscribe(Seek, lambda a: self.seek(a.time))
        bus.subscribe(SetPlaying, lambda a: self.set_playing(a.playing))
        bus.subscribe(SelectTimeRange, lambda a: self.select(a.start, a.stop))

    def subscribe(self, observer: Callable[[Timeline], None]) -> None:
        self._observers.append(observer)

    def unsubscribe(self, observer: Callable[[Timeline], None]) -> None:
        if observer in self._observers:
            self._observers.remove(observer)

    def _changed(self) -> None:
        for observer in list(self._observers):
            observer(self)

    def _clamp(self, t: float) -> float:
        return min(max(t, self.start), self.stop)

    def allows(self, time: float) -> bool:
        """Whether the playhead may be at `time`. Pointer gestures check this and ignore a target
        that is not allowed, which is how disabled regions behave; relative moves (stepping,
        playback) instead go through the constraint's `resolve` and jump to the nearest allowed time."""
        return self.constraint is None or self.constraint.allows(time)

    def _allowed(self, time: float) -> float:
        time = self._clamp(time)
        if self.constraint is not None:
            time = self._clamp(self.constraint.resolve(time, self.time))
        return time

    def set_range(self, start: float, stop: float) -> None:
        """Change the extent of the timeline, e.g. once all sources' extents are known."""
        if stop <= start:
            raise ValueError("timeline must have positive length")
        self.start, self.stop = start, stop
        self.time = self._clamp(self.time)
        if self.selection is not None:
            self.selection = (self._clamp(self.selection[0]), self._clamp(self.selection[1]))
        self._changed()

    def seek(self, time: float) -> None:
        time = self._allowed(time)
        if time != self.time:
            self.time = time
            self._changed()

    def set_playing(self, playing: bool) -> None:
        if playing and self.time >= self.stop:
            self.time = self.start             # restart from the beginning at the end
        if not playing:
            self.holding = None                # a pause is a pause, not a wait
        if playing != self.playing:
            self.playing = playing
            self._changed()

    def hold(self, reason: str | None) -> None:
        """Make the playhead wait (`reason` says why) or, with None, carry on.

        Unlike pausing, this does not change `playing`: the user still wants playback, so it
        resumes by itself when the hold is released, and pausing during a hold really pauses.
        """
        if reason != self.holding:
            self.holding = reason
            self._changed()

    def select(self, start: float, stop: float) -> None:
        if stop < start:
            start, stop = stop, start
        selection = (self._clamp(start), self._clamp(stop))
        if selection != self.selection:
            self.selection = selection
            self._changed()

    def advance(self, dt: float) -> None:
        """Move the playhead by `dt` seconds of wall time. No-op unless playing."""
        if not self.playing or self.holding:
            return
        proposed = self.time + dt * self.rate
        if proposed >= self.stop:
            self.time = self.stop
            self.playing = False
        else:
            time = proposed
            if self.constraint is not None:
                time = self._clamp(self.constraint.resolve(proposed, self.time))
                if time < proposed:            # nothing allowed lies ahead: stop at the end of what is
                    self.playing = False
            self.time = time
        self._changed()
