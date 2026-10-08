"""The shared timeline: one playhead in shared time that every view follows.

Pure state with no UI. A view's clock calls `advance`; user gestures arrive as
actions on the bus. Observers are told when anything changed.
"""

from __future__ import annotations

from typing import Callable

from syncviz.core.actions import ActionBus, SelectTimeRange, Seek, SetPlaying


class Timeline:
    def __init__(self, bus: ActionBus, start: float, stop: float, rate: float = 1.0) -> None:
        if stop <= start:
            raise ValueError("timeline must have positive length")
        self.start = start
        self.stop = stop
        self.rate = rate                       # playback speed; 1.0 is real time
        self.time = start
        self.playing = False
        self.selection: tuple[float, float] | None = None
        self._observers: list[Callable[[Timeline], None]] = []
        bus.subscribe(Seek, lambda a: self.seek(a.time))
        bus.subscribe(SetPlaying, lambda a: self.set_playing(a.playing))
        bus.subscribe(SelectTimeRange, lambda a: self.select(a.start, a.stop))

    def subscribe(self, observer: Callable[[Timeline], None]) -> None:
        self._observers.append(observer)

    def _changed(self) -> None:
        for observer in list(self._observers):
            observer(self)

    def _clamp(self, t: float) -> float:
        return min(max(t, self.start), self.stop)

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
        time = self._clamp(time)
        if time != self.time:
            self.time = time
            self._changed()

    def set_playing(self, playing: bool) -> None:
        if playing and self.time >= self.stop:
            self.time = self.start             # restart from the beginning at the end
        if playing != self.playing:
            self.playing = playing
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
        if not self.playing:
            return
        time = self.time + dt * self.rate
        if time >= self.stop:
            self.time = self.stop
            self.playing = False
        else:
            self.time = time
        self._changed()
