"""Semantic application actions and the bus that carries them (design doc §23-24).

Views translate gestures into actions and publish them; they never call each
other. Anything that cares about an action subscribes to its type.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class Seek:
    time: float                         # shared time, seconds


@dataclass(frozen=True)
class SetPlaying:
    playing: bool


@dataclass(frozen=True)
class SelectTimeRange:
    start: float                        # shared time, seconds
    stop: float


@dataclass(frozen=True)
class SelectSegment:
    index: int                          # position in the active segmentation


@dataclass(frozen=True)
class StepSegment:
    step: int                           # +1 next, -1 previous


@dataclass(frozen=True)
class StepTime:
    direction: int                      # +1 forward, -1 back, by the chosen time base's tick


class ActionBus:
    """Synchronous publish/subscribe keyed by action type."""

    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable[[Any], None]]] = defaultdict(list)

    def subscribe(self, action_type: type, handler: Callable[[Any], None]) -> None:
        self._handlers[action_type].append(handler)

    def publish(self, action: Any) -> None:
        for handler in list(self._handlers[type(action)]):
            handler(action)
