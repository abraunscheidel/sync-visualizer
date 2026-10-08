"""Rows of events and intervals, shared by the views that show them (tracks and indicators).

A row is `{name, kind: events|intervals, from: "source:path", member?}`. This module loads a row's
data, offers the rows a catalog entry could give, and says how bright an indicator should be.
"""

from __future__ import annotations

from typing import Iterable

import numpy as np

from syncviz.inspection import Target
from syncviz.sources import DataEntry
from syncviz_app.project import split_ref
from syncviz_app.views.base import Candidate


def load_row_data(context, row: dict):
    """Event times, or `(starts, stops)` for an interval row."""
    kind = row["kind"]
    if kind == "events":
        return context.resources.events(row["from"], row.get("member")).times
    if kind == "intervals":
        iv = context.resources.intervals(row["from"])
        return iv.starts, iv.stops
    raise ValueError(f"row {row.get('name')!r}: kind must be 'events' or 'intervals', got {kind!r}")


def row_target(row: dict) -> Target:
    """What a row points at: its data item, named by where it lives."""
    source, path = split_ref(row["from"])
    return Target(source, path, row["kind"], row.get("member"), row.get("name", ""))


def row_spec_for(type_name: str, target: Target) -> dict | None:
    """A view of `type_name` showing one row for `target`, if it is events or intervals."""
    if target.kind not in ("events", "intervals"):
        return None
    name = target.label or target.member or target.path.rsplit("/", 1)[-1]
    row = {"name": name, "kind": target.kind, "from": target.ref}
    if target.member:
        row["member"] = target.member
    return {"type": type_name, "title": name, "rows": [row]}


def extent_of(rows: Iterable[tuple[str, object]]) -> tuple[float, float] | None:
    """The span of time the rows' data covers, given `(kind, data)` pairs, or None if all are empty."""
    lows, highs = [], []
    for kind, data in rows:
        if kind == "events":
            if len(data):
                lows.append(data[0]); highs.append(data[-1])
        else:
            starts, stops = data
            if len(starts):
                lows.append(starts.min()); highs.append(stops.max())
    return (float(min(lows)), float(max(highs))) if lows else None


def rows_for_entry(source: str, entry: DataEntry) -> list[dict]:
    """The rows a catalog entry offers: one per member of an event container (named by the source's
    labels when it has them, in the order it gives them), or a single row for an interval table."""
    ref = f"{source}:{entry.path}"
    if entry.kind == "events":
        return [{"name": entry.labels.get(m, m), "kind": "events", "from": ref, "member": m} for m in entry.members]
    if entry.kind == "intervals":
        return [{"name": entry.path.rsplit("/", 1)[-1], "kind": "intervals", "from": ref}]
    return []


def row_candidates(catalog: dict[str, list[DataEntry]], type_name: str) -> list[Candidate]:
    out = []
    for source, entries in catalog.items():
        for entry in entries:
            rows = rows_for_entry(source, entry)
            if rows:
                name = entry.path.rsplit("/", 1)[-1]
                out.append(Candidate(f"{name}   ({source}: {entry.path})",
                                     {"type": type_name, "title": name.capitalize(), "rows": rows}, entry.description))
    return out


# -- how bright an indicator is, as a function of the playhead alone ---------------------------
def glow_after_events(times: np.ndarray, t: float, decay: float) -> float:
    """1 at an event, fading linearly to 0 over `decay` seconds after it. Nothing is shown for an
    event that has not happened yet, so scrubbing backwards un-lights things correctly."""
    i = int(np.searchsorted(times, t, side="right")) - 1
    if i < 0:
        return 0.0
    return max(0.0, 1.0 - (t - float(times[i])) / decay)


def glow_during_intervals(starts: np.ndarray, stops: np.ndarray, t: float, decay: float) -> float:
    """1 while inside an interval, then fading over `decay` seconds after it ends."""
    i = int(np.searchsorted(starts, t, side="right")) - 1
    if i < 0:
        return 0.0
    stop = float(stops[i])
    if t < stop:
        return 1.0
    return max(0.0, 1.0 - (t - stop) / decay)
