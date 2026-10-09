"""Event conditions: which parts of the recording to keep because of what happens in them (design doc 28.10, 28.12).

One condition is one question about a list of events, any one of which counts, with two ways to use it:

* **segments** (the default): keep the segments (trials) where one of them happened (answer yes) or none did (answer no);
* **clips**: keep just the moments around each of them. The navigated segments then become windows cut around the events (see
  `syncviz.epochs`), and the other conditions are asked of those windows.

A condition can be switched off without losing it. All the conditions that are on have to hold. This is deliberately not a query
builder: "(C0 or C1 touched) and (licked)" is two conditions, and anything deeper can be built from saved groups. Nothing here
knows what an event is called or means; the events are looked up by the names the project gives them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from syncviz.epochs import count_in_segments
from syncviz.resources.intervals import IntervalSeries

MODES = ("segment", "clip")


@dataclass(frozen=True)
class Condition:
    events: tuple[str, ...]                                   # names of the events; any one of them counts
    answer: bool = True                                       # True: at least one happened; False: none did
    edge: str = "overlap"                                     # for an interval event: overlap, start or stop
    enabled: bool = True                                      # off: kept, but not applied
    mode: str = "segment"                                     # segment: keep the segments; clip: keep the moments around them

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {self.mode!r}")
        if self.mode == "clip" and not self.answer:
            raise ValueError("clips are cut around events that happened, so a clip condition cannot say 'did not happen'")

    def label(self) -> str:
        names = " or ".join(self.events)
        suffix = " · clips" if self.mode == "clip" else ""
        return f"{names}: {'yes' if self.answer else 'no'}{suffix}"

    def to_dict(self) -> dict:
        return {"events": list(self.events), "answer": self.answer, "edge": self.edge, "enabled": self.enabled,
                "mode": self.mode}

    @classmethod
    def from_dict(cls, data: dict) -> "Condition":
        answer = bool(data.get("answer", True))
        mode = str(data.get("mode", "segment"))
        return cls(tuple(str(e) for e in data["events"]), answer, str(data.get("edge", "overlap")),
                   bool(data.get("enabled", True)), mode if answer else "segment")


def condition_mask(segments: IntervalSeries, condition: Condition, find: Callable[[str], object]) -> np.ndarray:
    """Which segments satisfy `condition`. `find(name)` returns the events (an `EventSeries` or an `IntervalSeries`) called
    `name`, or raises `KeyError` / `MissingDataError` when the recording has none."""
    counts = np.zeros(len(segments), dtype=int)
    for name in condition.events:
        counts += count_in_segments(segments, find(name), condition.edge)
    return counts > 0 if condition.answer else counts == 0


def conditions_mask(segments: IntervalSeries, conditions, find: Callable[[str], object]) -> tuple[np.ndarray | None, list[str]]:
    """The segments that satisfy every condition that is on and is about segments (clip conditions decide what the segments
    are, not which are kept), and notes on conditions that could not be applied (an event this recording does not have makes its
    condition be skipped, so the other filters still work). The mask is None when nothing applies."""
    mask: np.ndarray | None = None
    notes: list[str] = []
    for condition in conditions:
        if not condition.enabled or condition.mode != "segment":
            continue
        try:
            one = condition_mask(segments, condition, find)
        except Exception as exc:                              # missing data in this recording
            notes.append(f"event condition '{condition.label()}' skipped: {exc}")
            continue
        mask = one if mask is None else mask & one
    return mask, notes
