"""A scrolling line plot of one time series."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from syncviz_app.views.timewindow import TimeWindowView, break_at_gaps


class TimeSeriesView(TimeWindowView):
    type_name = "timeseries"

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        series_spec = spec["series"]
        self.series = context.resources.timeseries(series_spec["from"], series_spec.get("member"))
        self.curve = self.plot.plot(pen=pg.mkPen("#4fa3e0", width=1.5), connect="finite")
        if self.series.unit:
            self.plot.setLabel("left", self.series.unit)
        # Fixed vertical range from the whole series, so the plot doesn't rescale as it scrolls.
        finite = self.series.values[np.isfinite(self.series.values)]
        if finite.size:
            lo, hi = np.percentile(finite, [0.5, 99.5])
            pad = (hi - lo) * 0.1 or 1.0
            self.plot.setYRange(lo - pad, hi + pad, padding=0)

    def extent(self):
        if len(self.series) == 0:
            return None
        return float(self.series.times[0]), float(self.series.times[-1])

    def coverage(self):
        return [(float(a), float(b)) for a, b in self.series.coverage()]

    def refresh(self, time: float) -> None:
        lo, hi = self.set_window(time)
        window = self.series.window(lo, hi)
        times, values = break_at_gaps(window.times, window.values)
        self.curve.setData(times, values)
