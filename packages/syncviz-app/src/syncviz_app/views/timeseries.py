"""A scrolling line plot of one time series."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pyqtgraph as pg

from syncviz import processors
from syncviz.inspection import Target
from syncviz_app.project import split_ref
from syncviz_app.views.base import Candidate
from syncviz_app.views.timewindow import TimeWindowView, break_at_gaps


MIN_POINTS = 2000


class TimeSeriesView(TimeWindowView):
    type_name = "timeseries"
    display_name = "Time series plot"

    @classmethod
    def candidates(cls, catalog):
        out = []
        for source, entries in catalog.items():
            for entry in entries:
                if entry.kind == "timeseries":
                    for member in entry.members:
                        spec = {"type": cls.type_name, "title": member,
                                "series": {"from": f"{source}:{entry.path}", "member": member}}
                        out.append(Candidate(f"{member}   ({source}: {entry.path})", spec,
                                             entry.member_descriptions.get(member) or entry.description))
        for processor in processors.all_processors():                   # series computed from the data
            for label, title, series in processor.candidates(catalog):
                out.append(Candidate(label, {"type": cls.type_name, "title": title, "series": series}))
        return out

    @classmethod
    def spec_for(cls, target):
        if target.kind == "group":                 # the average rate of the group's items
            return {"type": cls.type_name, "title": f"{target.label} rate",
                    "series": {"process": "population_rate", "inputs": [{"group": target.path}],
                               "bin_ms": 10, "smooth_ms": 20, "smoothing": "trailing"}}
        if target.kind != "timeseries":
            return None
        name = target.label or target.member or target.path.rsplit("/", 1)[-1]
        return {"type": cls.type_name, "title": name, "series": {"from": target.ref, "member": target.member}}

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        self.curve = self.plot.plot(pen=pg.mkPen("#4fa3e0", width=1.5), connect="finite")
        self.enable_hover(self.plot.viewport())
        self._set_series(spec["series"], self.title)

    def _set_series(self, series_spec: dict, label: str) -> None:
        """Show this series (and, if it comes from a source, make it the item the view points at)."""
        context = self.context
        if "process" in series_spec:                      # computed by a processor, not read from a source
            self.series = context.resources.derived(series_spec)
        else:
            self.series = context.resources.timeseries(series_spec["from"], series_spec.get("member"))
        self.target = None
        if "from" in series_spec:
            source, path = split_ref(series_spec["from"])
            self.target = Target(source, path, "timeseries", series_spec.get("member"), label)
        self.plot.setLabel("left", self.series.unit or "")
        # Fixed vertical range from the whole series, so the plot doesn't rescale as it scrolls.
        finite = self.series.sample_values()
        finite = finite[np.isfinite(finite)]
        if finite.size:
            lo, hi = np.percentile(finite, [0.5, 99.5])
            pad = (hi - lo) * 0.1 or 1.0
            self.plot.setYRange(lo - pad, hi + pad, padding=0)

    def show_target(self, target) -> bool:
        spec = self.spec_for(target)
        if spec is None:
            return False
        self._set_series(spec["series"], spec["title"])
        return True

    def restore_subject(self) -> None:
        self._set_series(self.spec["series"], self.title)
        self.mark_selected()
        if self._last_time is not None:
            self.refresh(self._last_time)

    def target_at(self, pos):
        return None if self.target is None else replace(self.target, at=self.time_at(pos))

    def mark_selected(self) -> None:
        self.curve.setPen(pg.mkPen("#4fa3e0", width=3 if self.is_selected(self.target) else 1.5))

    def extent(self):
        if len(self.series) == 0:
            return None
        return self.series.first_time, self.series.last_time

    def coverage(self):
        return [(float(a), float(b)) for a, b in self.series.coverage()]

    def time_base(self):
        return self.series.time_base()

    def refresh(self, time: float) -> None:
        lo, hi = self.set_window(time)
        budget = max(2 * self.plot.width(), MIN_POINTS)       # more points than pixels cannot be seen
        window = self.series.window(lo, hi, max_points=budget)
        times, values = window.times, window.values
        if self.series.count_between(lo, hi) <= budget:       # a thinned window has no true spacing to find gaps in
            times, values = break_at_gaps(times, values)
        self.curve.setData(times, values)
