"""Shared behavior of views that show a scrolling window of time around the playhead."""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QVBoxLayout

from syncviz.core import Seek
from syncviz_app.context import AppContext
from syncviz_app.views.base import View

DEFAULT_WINDOW_SECONDS = 10.0
GAP_FACTOR = 3.0        # a spacing this many times the typical one is drawn as a break


def break_at_gaps(times: np.ndarray, values: np.ndarray, factor: float = GAP_FACTOR):
    """Insert NaN where samples are missing so a line is drawn as a break, not across the gap."""
    if len(times) < 3:
        return times, values
    dt = np.diff(times)
    typical = np.median(dt)
    gaps = np.flatnonzero(dt > factor * typical)
    if gaps.size == 0:
        return times, values
    mid = (times[gaps] + times[gaps + 1]) / 2
    values = values.astype(float, copy=False)
    return np.insert(times, gaps + 1, mid), np.insert(values, gaps + 1, np.nan)


class TimeWindowView(View):
    """A plot whose x axis is a window of time centred on the playhead."""

    def __init__(self, context: AppContext, spec: dict) -> None:
        super().__init__(context, spec)
        self.window_seconds = float(spec.get("window", DEFAULT_WINDOW_SECONDS))
        self.plot = pg.PlotWidget()
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=False, alpha=0.2)
        self.playhead = pg.InfiniteLine(angle=90, movable=False, pen=pg.mkPen("#e0a030", width=2))
        self.plot.addItem(self.playhead)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.plot)
        self.plot.scene().sigMouseClicked.connect(self._clicked)

    def _clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        viewbox = self.plot.getPlotItem().vb
        if not viewbox.sceneBoundingRect().contains(event.scenePos()):
            return
        # A click selects what is under it; where there is nothing to select, or on a double click, it seeks.
        # The click is in this view's time; the playhead is `lag` later.
        if not event.double() and self.select_at(self.plot.mapTo(self, self.plot.mapFromScene(event.scenePos()))):
            return
        self.seek_from_time(float(viewbox.mapSceneToView(event.scenePos()).x()) + self.lag)

    def seek_from_time(self, time: float) -> bool:
        """Move the playhead to a clicked time, unless it is not allowed (see Timeline.allows)."""
        if not self.context.timeline.allows(time):
            return False
        self.context.bus.publish(Seek(time))
        return True

    def set_window(self, time: float) -> tuple[float, float]:
        lo, hi = time - self.window_seconds / 2, time + self.window_seconds / 2
        self.plot.setXRange(lo, hi, padding=0)
        self.playhead.setPos(time)
        return lo, hi
