"""Stepping the playhead by one "tick" of a chosen time base.

What a tick is depends on the data: a video's frame, a signal's next sample, or a fixed
interval. The user chooses which view defines it; this module knows nothing about views,
only about time bases that can say where the neighbouring tick is.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping, Protocol

import numpy as np

from syncviz.core.actions import ActionBus, Seek, SetPlaying, StepTime
from syncviz.core.timeline import Timeline
from syncviz.resources.timeseries import bisect_array

EPS = 1e-9
FIXED_INTERVAL = "Fixed interval"       # the name under which a fixed step is offered alongside views


class TimeBase(Protocol):
    def neighbor(self, time: float, direction: int) -> float | None:
        """The nearest tick strictly after (direction > 0) or before (direction < 0) `time`,
        or None if there is none."""


@dataclass(frozen=True)
class RegularGrid:
    """Ticks at origin + n / rate for n = 0 .. count-1 (for example the frames of a video).

    Stepping from between ticks lands on the next tick, not a fixed distance away.
    """

    rate: float
    count: int | None = None
    origin: float = 0.0

    def neighbor(self, time: float, direction: int) -> float | None:
        position = (time - self.origin) * self.rate
        if direction > 0:
            n = max(math.floor(position + EPS) + 1, 0)
            if self.count is not None and n >= self.count:
                return None
        else:
            n = math.ceil(position - EPS) - 1
            if self.count is not None:
                n = min(n, self.count - 1)
            if n < 0:
                return None
        return self.origin + n / self.rate


@dataclass(frozen=True)
class SampleTimes:
    """Ticks at the given, possibly irregular, sample times (sorted)."""

    times: np.ndarray

    def neighbor(self, time: float, direction: int) -> float | None:
        if direction > 0:
            i = int(np.searchsorted(self.times, time + EPS, side="right"))
            return float(self.times[i]) if i < len(self.times) else None
        i = int(np.searchsorted(self.times, time - EPS, side="left")) - 1
        return float(self.times[i]) if i >= 0 else None


@dataclass(frozen=True)
class LazySampleTimes:
    """Like `SampleTimes`, for a sorted time axis too large to load (an array-like on disk): the
    neighbour is found by a handful of single-sample reads."""

    times: object

    def neighbor(self, time: float, direction: int) -> float | None:
        if direction > 0:
            i = bisect_array(self.times, time + EPS, "right")
            return float(self.times[i]) if i < len(self.times) else None
        i = bisect_array(self.times, time - EPS, "left") - 1
        return float(self.times[i]) if i >= 0 else None


@dataclass(frozen=True)
class FixedStep:
    """Moves by exactly `interval` seconds from wherever the playhead is."""

    interval: float

    def neighbor(self, time: float, direction: int) -> float | None:
        return time + self.interval if direction > 0 else time - self.interval


class Stepper:
    """Turns StepTime actions into a Seek by `count` ticks of the chosen time base."""

    def __init__(
        self,
        bus: ActionBus,
        timeline: Timeline,
        bases: Mapping[str, TimeBase],
        reference: str | None = None,
    ) -> None:
        self.bus = bus
        self.timeline = timeline
        self.bases: dict[str, TimeBase] = dict(bases)
        # The user can change this; the first available base is only the starting choice.
        self.reference = reference if reference in self.bases else next(iter(self.bases), None)
        self.count = 1
        bus.subscribe(StepTime, lambda a: self.step(a.direction))

    @property
    def base(self) -> TimeBase | None:
        return self.bases.get(self.reference) if self.reference is not None else None

    def step(self, direction: int) -> None:
        base = self.base
        if base is None:
            return
        if self.timeline.playing:
            self.bus.publish(SetPlaying(False))            # stepping means "stop and look"
        time = self.timeline.time
        for _ in range(max(self.count, 1)):
            nxt = base.neighbor(time, direction)
            if nxt is None:
                break
            time = nxt
        if time != self.timeline.time:
            self.bus.publish(Seek(time))
