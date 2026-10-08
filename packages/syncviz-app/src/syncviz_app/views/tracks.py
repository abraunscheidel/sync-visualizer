"""Rows of events (ticks) and intervals (bars) over a scrolling window of time."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pyqtgraph as pg


from syncviz_app.views.rows import extent_of, load_row_data, row_candidates, row_spec_for, row_target
from syncviz_app.views.timewindow import TimeWindowView

TICK_HALF_HEIGHT = 0.35
HOVER_PIXELS = 5            # how near the pointer must be to a tick to mean that event
BAR_WIDTH_PX = 9


class TracksView(TimeWindowView):
    type_name = "tracks"
    display_name = "Events and intervals"

    @classmethod
    def candidates(cls, catalog):
        return row_candidates(catalog, cls.type_name)

    @classmethod
    def spec_for(cls, target):
        return row_spec_for(cls.type_name, target)

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        self.rows = []
        self.band = pg.LinearRegionItem(values=(0, 0), orientation="horizontal", movable=False,
                                        brush=pg.mkBrush(224, 160, 48, 50), pen=pg.mkPen(None))
        self.band.setZValue(-10)
        self.band.hide()
        self.plot.addItem(self.band, ignoreBounds=True)
        self._build(spec["rows"])
        self.plot.getAxis("left").setWidth(110)
        self.enable_hover(self.plot.viewport())

    def _build(self, row_specs) -> None:
        """(Re)draw with these rows."""
        for row in self.rows:
            self.plot.removeItem(row["item"])
        self.rows = []
        n = len(row_specs)
        for i, row in enumerate(row_specs):
            y = n - 1 - i                                      # first row at the top
            colour = pg.intColor(i, hues=max(n, 6), values=1, maxValue=220)
            kind = row["kind"]
            data = load_row_data(self.context, row)
            if kind == "events":
                item = self.plot.plot(pen=pg.mkPen(colour, width=2), connect="pairs")
            else:
                item = self.plot.plot(pen=pg.mkPen(colour, width=BAR_WIDTH_PX, cap=pg.QtCore.Qt.PenCapStyle.FlatCap),
                                      connect="pairs")
            self.rows.append({"name": row.get("name", ""), "kind": kind, "y": y, "data": data, "item": item, "spec": row})
        self.plot.setYRange(-0.7, n - 0.3, padding=0)
        self.plot.getAxis("left").setTicks([[(r["y"], r["name"]) for r in self.rows]])

    def show_target(self, target) -> bool:
        spec = self.spec_for(target)
        if spec is None:
            return False
        self._build(spec["rows"])
        return True

    def restore_subject(self) -> None:
        self._build(self.spec["rows"])
        self.mark_selected()
        if self._last_time is not None:
            self.refresh(self._last_time)

    def mark_selected(self) -> None:
        row = next((r for r in self.rows if self.is_selected(row_target(r["spec"]))), None)
        if row is None:
            self.band.hide()
        else:
            self.band.setRegion((row["y"] - 0.5, row["y"] + 0.5))
            self.band.show()

    def target_at(self, pos):
        """The row under the pointer; for an events row, the event itself when the pointer is within a few pixels of it."""
        local = self.plot.viewport().mapFrom(self, pos)
        viewbox = self.plot.getPlotItem().vb
        scene = self.plot.mapToScene(local)
        if not viewbox.sceneBoundingRect().contains(scene):
            return None
        at = viewbox.mapSceneToView(scene)
        row = next((r for r in self.rows if abs(r["y"] - at.y()) <= 0.5), None)
        if row is None:
            return None
        target = replace(row_target(row["spec"]), at=float(at.x()))
        if row["kind"] == "events" and len(row["data"]):
            per_pixel = self.window_seconds / max(viewbox.sceneBoundingRect().width(), 1.0)
            times = row["data"]
            i = int(np.searchsorted(times, at.x()))
            near = [times[j] for j in (i - 1, i) if 0 <= j < len(times)]
            best = min(near, key=lambda t: abs(t - at.x()), default=None)
            if best is not None and abs(best - at.x()) <= HOVER_PIXELS * per_pixel:
                target = replace(target, time=float(best))
        return target

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
