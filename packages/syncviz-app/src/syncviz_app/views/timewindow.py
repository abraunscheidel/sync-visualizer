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
        self.follow = bool(spec.get("follow_selection", False))     # show whatever is selected (only views that can)
        self._last_time: float | None = None
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

    # -- following the selection (design doc 28.7) --------------------------------------------------
    def show_target(self, target) -> bool:
        """Show `target` in place of what this view shows, keeping its place and settings. Returns whether it could.
        Views that can follow the selection override this."""
        return False

    @property
    def can_follow(self) -> bool:
        return type(self).show_target is not TimeWindowView.show_target

    def settings(self):
        from syncviz_app.views.base import ViewSetting

        if not self.can_follow:
            return []
        return [ViewSetting("follow_selection", "Follow the selected item", "toggle", self.follow,
                            description="Show whatever is selected in this view, replacing what it shows. Untick to keep "
                                        "what it shows now.")]

    def apply_setting(self, key: str, value) -> None:
        if key == "follow_selection":
            self.follow = bool(value)
            self.selection_changed()

    def reset_settings(self) -> None:
        self.follow = bool(self.spec.get("follow_selection", False))
        self.restore_subject()

    def restore_subject(self) -> None:
        """Go back to what the project (or the user's spec) gave this view to show."""

    def selection_changed(self) -> None:
        target = self.context.selection.target
        if self.follow and target is not None:
            if self.show_target(target) and self._last_time is not None:
                self.refresh(self._last_time)
        self.mark_selected()

    def mark_selected(self) -> None:
        """Show which item this view draws is the selected one."""

    def _clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        viewbox = self.plot.getPlotItem().vb
        if not viewbox.sceneBoundingRect().contains(event.scenePos()):
            return
        # What the project binds to a click (select) or double click (seek) happens to what is under the pointer; where
        # there is nothing to act on, a click seeks. The click is in this view's time; the playhead is `lag` later.
        pos = self.plot.mapTo(self, self.plot.mapFromScene(event.scenePos()))
        target = self.target_at(pos)
        if target is not None and self.context.actions.trigger("double_click" if event.double() else "click", target, self):
            return
        self.seek_from_time(float(viewbox.mapSceneToView(event.scenePos()).x()) + self.lag)

    def time_at(self, pos) -> float | None:
        """The time on this view's axis under `pos` (this view's coordinates), or None outside the plot."""
        scene = self.plot.mapToScene(self.plot.mapFrom(self, pos))
        viewbox = self.plot.getPlotItem().vb
        return float(viewbox.mapSceneToView(scene).x()) if viewbox.sceneBoundingRect().contains(scene) else None

    def seek_from_time(self, time: float) -> bool:
        """Move the playhead to a clicked time, unless it is not allowed (see Timeline.allows)."""
        if not self.context.timeline.allows(time):
            return False
        self.context.bus.publish(Seek(time))
        return True

    def set_window(self, time: float) -> tuple[float, float]:
        self._last_time = time
        lo, hi = time - self.window_seconds / 2, time + self.window_seconds / 2
        self.plot.setXRange(lo, hi, padding=0)
        self.playhead.setPos(time)
        return lo, hi
