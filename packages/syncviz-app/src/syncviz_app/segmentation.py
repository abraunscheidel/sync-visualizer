"""Building the segments the project describes: a table from a source, or windows cut around events, plus the measures
that turn "what happens inside" each one into attributes you can filter by (design doc 28.9).

    segmentations:
      trials:
        label: Trial
        from: "session:intervals/trials"
        filters: [stimulus, "Whisker C0"]
        measures:                                   # attributes worked out from events in each segment
          "Whisker C0": {from: "session:processing/behavior/contacts_C0", as: presence,
                         labels: [no touch, touch], description: "Whether whisker C0 touched the object."}
      touches:
        label: Touch
        derive:                                     # a window around each event, inside the segment it falls in
          from: "session:processing/behavior/contacts_C0"
          edge: start
          before_ms: 500
          after_ms: 500
          within: trials                            # windows are clipped to a trial and take its attributes
        filters: [stimulus, outcome]
"""

from __future__ import annotations

import numpy as np

from syncviz.epochs import derive_epochs, measure
from syncviz.resources import EventSeries, IntervalSeries
from syncviz.sources import MissingDataError


def segments(specs: dict[str, dict], name: str, resources, notes: list[str] | None = None) -> IntervalSeries:
    """The segments called `name` in `specs`, for the recording in `resources`. Kept, so every caller shares one."""
    return resources.cached(("segments", name), lambda: _build(specs, name, resources, notes, ()))


def _build(specs, name, resources, notes, building) -> IntervalSeries:
    if name in building:
        raise ValueError(f"segmentations {' -> '.join(building + (name,))} refer to each other in a circle")
    spec = specs[name]
    if "derive" in spec:
        base = _derive(specs, name, spec["derive"], resources, notes, building + (name,))
    else:
        base = resources.intervals(spec["from"])
    for attribute, how in (spec.get("measures") or {}).items():
        try:
            events = resources.events_or_intervals(how["from"], how.get("member"))
        except MissingDataError as exc:
            if notes is not None:
                notes.append(f"measure {attribute!r} of {spec.get('label', name)} skipped: {exc}")
            continue
        labels = tuple(how.get("labels", ("no", "yes")))
        if len(labels) != 2 or not all(isinstance(label, str) for label in labels):
            raise ValueError(f"measure {attribute!r}: labels must be two pieces of text (without, with); in YAML put quotes "
                             f"around yes and no, which are read as true and false")
        base = measure(base, attribute, events, how.get("edge", "overlap"), how.get("as", "count"), labels,
                       resources_description(how))
    return base


def resources_description(how: dict) -> str:
    return str(how.get("description", ""))


def _derive(specs, name, how, resources, notes, building) -> IntervalSeries:
    source = resources.events_or_intervals(how["from"], how.get("member"))
    if isinstance(source, EventSeries):
        times = source.times
    else:
        edge = how.get("edge", "start")
        if edge not in ("start", "stop"):
            raise ValueError(f"derive.edge must be 'start' or 'stop' for an interval table, got {edge!r}")
        times = source.starts if edge == "start" else source.stops
    parent_name = how.get("within")
    parent = _build(specs, parent_name, resources, notes, building) if parent_name else None
    label = specs[parent_name].get("label", parent_name) if parent_name else "Segment"
    epochs = derive_epochs(np.asarray(times), float(how.get("before_ms", 0)) / 1000.0, float(how.get("after_ms", 0)) / 1000.0,
                           parent, bool(how.get("merge", True)), how.get("count_name", "Events"), label, name)
    if len(epochs) == 0:
        raise MissingDataError(f"no {specs[name].get('label', name).lower()} windows: the events never fall in the segments")
    return epochs
