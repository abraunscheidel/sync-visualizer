"""Event conditions: which segments to keep because of what happens in them (design doc 28.10).

One condition is one question with an answer: did any of these events happen in the segment (yes), or did none of them
(no)? Several conditions all have to hold. This is deliberately not a query builder: "(C0 or C1 touched) and (licked)" is two
conditions, and anything deeper can be built from saved groups. Nothing here knows what an event is called or means; the
events are looked up by the names the project gives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from syncviz.epochs import count_in_segments
from syncviz.resources.intervals import IntervalSeries


@dataclass(frozen=True)
class Condition:
    events: tuple[str, ...]                                   # names of the events; any one of them counts
    answer: bool = True                                       # True: at least one happened; False: none did
    edge: str = "overlap"                                     # for an interval event: overlap, start or stop

    def label(self) -> str:
        names = " or ".join(self.events)
        return f"{names}: {'yes' if self.answer else 'no'}"

    def to_dict(self) -> dict:
        return {"events": list(self.events), "answer": self.answer, "edge": self.edge}

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        return cls(tuple(str(e) for e in data["events"]), bool(data.get("answer", True)), str(data.get("edge", "overlap")))


def condition_mask(segments: IntervalSeries, condition: Condition, find: Callable[[str], object]) -> np.ndarray:
    """Which segments satisfy `condition`. `find(name)` returns the events (an `EventSeries` or an `IntervalSeries`) called
    `name`, or raises `KeyError` / `MissingDataError` when the recording has none."""
    counts = np.zeros(len(segments), dtype=int)
    for name in condition.events:
        counts += count_in_segments(segments, find(name), condition.edge)
    return counts > 0 if condition.answer else counts == 0


def conditions_mask(segments: IntervalSeries, conditions, find: Callable[[str], object]) -> tuple[np.ndarray | None, list[str]]:
    """The segments that satisfy every condition, and notes on conditions that could not be applied (an event this recording
    does not have makes its condition be skipped, so the other filters still work). The mask is None when nothing applies."""
    mask: np.ndarray | None = None
    notes: list[str] = []
    for condition in conditions:
        try:
            one = condition_mask(segments, condition, find)
        except Exception as exc:                              # missing data in this recording
            notes.append(f"event condition '{condition.label()}' skipped: {exc}")
            continue
        mask = one if mask is None else mask & one
    return mask, notes
