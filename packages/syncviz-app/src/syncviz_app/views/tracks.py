"""Rows of events (ticks) and intervals (bars) over a scrolling window of time."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg

from syncviz_app.views.base import Candidate
from syncviz_app.views.timewindow import TimeWindowView

TICK_HALF_HEIGHT = 0.35
BAR_WIDTH_PX = 9


class TracksView(TimeWindowView):
    type_name = "tracks"
    display_name = "Events and intervals"

    @classmethod
    def candidates(cls, catalog):
        out = []
        for source, entries in catalog.items():
            for entry in entries:
                ref = f"{source}:{entry.path}"
                name = entry.path.rsplit("/", 1)[-1]
                if entry.kind == "events":
                    rows = [{"name": m, "kind": "events", "from": ref, "member": m} for m in entry.members]
                elif entry.kind == "intervals":
                    rows = [{"name": name, "kind": "intervals", "from": ref}]
                else:
                    continue
                out.append(Candidate(f"{name}   ({source}: {entry.path})",
                                     {"type": cls.type_name, "title": name, "rows": rows}))
        return out

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        self.rows = []
        n = len(spec["rows"])
        for i, row in enumerate(spec["rows"]):
            y = n - 1 - i                                      # first row at the top
            colour = pg.intColor(i, hues=max(n, 6), values=1, maxValue=220)
            kind = row["kind"]
            if kind == "events":
                data = context.resources.events(row["from"], row.get("member")).times
                item = self.plot.plot(pen=pg.mkPen(colour, width=2), connect="pairs")
            elif kind == "intervals":
                iv = context.resources.intervals(row["from"])
                data = (iv.starts, iv.stops)
                item = self.plot.plot(pen=pg.mkPen(colour, width=BAR_WIDTH_PX, cap=pg.QtCore.Qt.PenCapStyle.FlatCap),
                                      connect="pairs")
            else:
                raise ValueError(f"row {row.get('name')!r}: kind must be 'events' or 'intervals', got {kind!r}")
            self.rows.append({"name": row.get("name", ""), "kind": kind, "y": y, "data": data, "item": item})
        self.plot.setYRange(-0.7, n - 0.3, padding=0)
        self.plot.getAxis("left").setTicks([[(r["y"], r["name"]) for r in self.rows]])
        self.plot.getAxis("left").setWidth(110)

    def extent(self):
        lows, highs = [], []
        for row in self.rows:
            if row["kind"] == "events":
                times = row["data"]
                if len(times):
                    lows.append(times[0]); highs.append(times[-1])
            else:
                starts, stops = row["data"]
                if len(starts):
                    lows.append(starts.min()); highs.append(stops.max())
        return (float(min(lows)), float(max(highs))) if lows else None

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
