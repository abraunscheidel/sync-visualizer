"""Processors: turn resources into new resources (design doc §20).

A processor takes input resources and parameters and returns a resource; here, event series in and a regularly
sampled time series out. Nothing is stored in the data file: the result is computed when a view asks for it, and the
processor's name and parameters are written in the project (or the workspace), so the result can always be reproduced.

Built-in processors are listed in `BUILTIN`; more can be added as plugins in the entry-point group
`syncviz.processors`. A processor class has:

* `run(inputs, **params)`: the computation;
* `candidates(catalog)`: what it could offer from the data a project has, as `(label, title, series_spec)` triples, so
  that the "Add view" dialog can list it without knowing it by name.
"""

from __future__ import annotations

import math
from typing import Sequence

import numpy as np

from syncviz import plugins
from syncviz.resources import EventSeries, TimeSeries
from syncviz.sources import DataEntry

MIN_GROUP = 2            # a rate of a single event row is just that row; offer a combined rate for two or more


class PopulationRate:
    """How often events happen, across a group of event series, over time.

    Events from all inputs are counted in bins of `bin_ms`, smoothed, and divided by the bin length and, with
    `per_member` (the default), by the number of inputs. For spike units this is the average firing rate of a unit at
    each moment, in spikes per second. The total number of events is preserved by the smoothing.

    `smoothing` decides which events a moment's rate may use:

    * `trailing` (the default): only events up to that moment, weighted by an exponential with time constant
      `smooth_ms`. The rate can never rise before the event that caused it, so the picture cannot suggest an effect that
      precedes its cause. It lags the true rate by about `smooth_ms`, which the view's display delay can offset.
    * `centered`: a Gaussian of width `smooth_ms` on both sides. Smoother and unbiased in time, but it spreads each
      event backwards as well, so a response appears to begin before its cause; it blurs latencies of a few tens of ms.
    """

    name = "population_rate"

    @staticmethod
    def candidates(catalog: dict[str, list[DataEntry]]) -> list[tuple[str, str, dict]]:
        out = []
        for source, entries in catalog.items():
            for entry in entries:
                if entry.kind == "events" and len(entry.members) >= MIN_GROUP:
                    leaf = entry.path.rsplit("/", 1)[-1]
                    out.append((f"Combined event rate of {leaf}   ({source}: {entry.path})", f"{leaf.capitalize()} rate",
                                {"process": "population_rate", "inputs": [f"{source}:{entry.path}"],
                                 "bin_ms": 10, "smooth_ms": 20, "smoothing": "trailing"}))
        return out

    def run(self, inputs: Sequence[EventSeries], bin_ms: float = 10.0, smooth_ms: float = 20.0,
            smoothing: str = "trailing", per_member: bool = True) -> TimeSeries:
        bin_ms, smooth_ms = float(bin_ms), float(smooth_ms)
        if bin_ms <= 0 or smooth_ms < 0:
            raise ValueError("bin_ms must be positive and smooth_ms cannot be negative")
        if smoothing not in ("trailing", "centered"):
            raise ValueError(f"smoothing must be 'trailing' or 'centered', not {smoothing!r}")
        times = [np.asarray(e.times, dtype=float) for e in inputs if len(e)]
        if not times:
            raise ValueError("there are no events to take a rate of")
        times_all = np.concatenate(times)
        bin_s = bin_ms / 1000.0
        scale = smooth_ms / bin_ms                                          # in bins
        reach = int(math.ceil((6 if smoothing == "trailing" else 4) * scale))
        before = reach if smoothing == "centered" else 0                    # trailing smoothing only looks back, so it needs room only after
        first = math.floor(times_all.min() / bin_s) - before
        last = math.floor(times_all.max() / bin_s) + reach
        edges = np.arange(first, last + 2) * bin_s
        counts = np.histogram(times_all, bins=edges)[0].astype(float)
        if scale > 0:
            if smoothing == "trailing":
                kernel = np.exp(-np.arange(reach + 1) / scale)
                counts = np.convolve(counts, kernel / kernel.sum(), mode="full")[: len(counts)]
            else:
                x = np.arange(-reach, reach + 1)
                kernel = np.exp(-0.5 * (x / scale) ** 2)
                counts = np.convolve(counts, kernel / kernel.sum(), mode="same")
        rate = counts / bin_s / (len(inputs) if per_member else 1)
        unit = "events/s per member" if per_member else "events/s"
        centers = (edges[:-1] + edges[1:]) / 2
        return TimeSeries(centers, rate, unit=unit, name=f"{self.name}({len(inputs)} inputs)")


BUILTIN: dict[str, type] = {PopulationRate.name: PopulationRate}


def available() -> list[str]:
    return sorted({*BUILTIN, *plugins.available("processors")})


def get(name: str) -> type:
    """The processor class called `name`: built in, else from a plugin."""
    if name in BUILTIN:
        return BUILTIN[name]
    try:
        return plugins.load("processors", name)
    except KeyError:
        raise KeyError(f"no processor named {name!r} (available: {', '.join(available())})") from None


def all_processors() -> list[type]:
    out = [BUILTIN[n] for n in sorted(BUILTIN)]
    for name in plugins.available("processors"):
        if name not in BUILTIN:
            out.append(plugins.load("processors", name))
    return out
