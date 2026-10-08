"""Rows of events (ticks) and intervals (bars) over a scrolling window of time."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from syncviz_app.views.rows import extent_of, load_row_data, row_candidates
from syncviz_app.views.timewindow import TimeWindowView

TICK_HALF_HEIGHT = 0.35
BAR_WIDTH_PX = 9


class TracksView(TimeWindowView):
    type_name = "tracks"
    display_name = "Events and intervals"

    @classmethod
    def candidates(cls, catalog):
        return row_candidates(catalog, cls.type_name)

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        self.rows = []
        n = len(spec["rows"])
        for i, row in enumerate(spec["rows"]):
            y = n - 1 - i                                      # first row at the top
            colour = pg.intColor(i, hues=max(n, 6), values=1, maxValue=220)
            kind = row["kind"]
            data = load_row_data(context, row)
            if kind == "events":
                item = self.plot.plot(pen=pg.mkPen(colour, width=2), connect="pairs")
            else:
                item = self.plot.plot(pen=pg.mkPen(colour, width=BAR_WIDTH_PX, cap=pg.QtCore.Qt.PenCapStyle.FlatCap),
                                      connect="pairs")
            self.rows.append({"name": row.get("name", ""), "kind": kind, "y": y, "data": data, "item": item})
        self.plot.setYRange(-0.7, n - 0.3, padding=0)
        self.plot.getAxis("left").setTicks([[(r["y"], r["name"]) for r in self.rows]])
        self.plot.getAxis("left").setWidth(110)

    def extent(self):
        return extent_of((row["kind"], row["data"]) for row in self.rows)

    def refresh(self, time: float) -> None:
        lo, hi = self.set_window(time)
        for row in self.rows:
            y = row["y"]
            if row["kind"] == "events":
                times = row["data"]
                a, b = np.searchsorted(times, [lo, hi])
                t = times[a:b]
                x = np.repeat(t, 2)
                ys = np.tile([y - TICK_HALF_HEIGHT, y + TICK_HALF_HEIGHT], len(t))
            else:
                starts, stops = row["data"]
                keep = np.flatnonzero((starts < hi) & (stops > lo))
                s = np.maximum(starts[keep], lo)
                e = np.minimum(stops[keep], hi)
                x = np.column_stack([s, e]).ravel()
                ys = np.full(x.shape, float(y))
            row["item"].setData(x, ys)
