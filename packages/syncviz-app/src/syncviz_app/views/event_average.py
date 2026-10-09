"""The event-triggered average: what items do around the moments that matter (design doc 28.17).

For each item (a unit, or a group of units), the plot shows its rate against the delay from every moment of an event (every contact,
every trial start), averaged over the moments, with the spread as a band. A table beside it gives the same per item. Only the moments
inside the segments that are shown count, so the filters and clips decide what is averaged. The view says nothing about what the
items or the event are: the event is any of the project's, the items are whatever event streams are selected or given.

It shows a result, not the playhead's moment, so it does not move as playback runs; it recomputes when the choices, the conditions or
the shown segments change.
"""

from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QAbstractItemView, QLabel, QTableWidget, QTableWidgetItem, QVBoxLayout

from syncviz.peri_event import peri_event_rate, anchors_from, item_row, within_segments
from syncviz.inspection import Target
from syncviz_app.project import split_ref
from syncviz_app.views.base import Candidate, View, ViewSetting

BEFORE_MS = (0, 100, 250, 500, 1000, 2000)
AFTER_MS = (100, 250, 500, 1000, 2000, 5000)
BIN_MS = (5, 10, 20, 50, 100, 250)
COLUMNS = ["Item", "Moments", "Before (Hz)", "After (Hz)", "Change (Hz)", "Peak (Hz)", "Peak at (ms)"]
NONE = "(none)"


class EventAverageView(View):
    type_name = "event_average"
    display_name = "Event-triggered average"
    default_refresh_hz = 5.0

    @classmethod
    def candidates(cls, catalog):
        return [Candidate("Event-triggered average", {"type": cls.type_name, "title": "Event-triggered average", "follow_selection": True},
                          "The rate of the selected units or groups around every moment of an event, averaged. Choose the event, "
                          "the window and the bin size in the view's settings.")]

    @classmethod
    def spec_for(cls, target: Target) -> dict | None:
        item = cls.item_of(target)
        if item is None:
            return None
        return {"type": cls.type_name, "title": f"{target.label or target.member or target.path} average", "items": [item]}

    @staticmethod
    def item_of(target: Target) -> dict | None:
        if target.kind == "group":
            return {"group": target.path, "name": target.label or target.path}
        if target.kind == "events" and target.member is not None:
            return {"from": target.ref, "member": target.member, "name": target.label or target.member}
        return None

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        if context.events is None:
            raise ValueError("the event-triggered average needs the project's events")
        self.events = context.events
        self.defaults = {"align": spec.get("align"), "before_ms": float(spec.get("before_ms", 500)),
                         "after_ms": float(spec.get("after_ms", 1000)), "bin_ms": float(spec.get("bin_ms", 20)),
                         "edge": spec.get("edge", "start"), "inside": bool(spec.get("inside", True)),
                         "follow": bool(spec.get("follow_selection", False))}
        self._items: list[dict] = list(spec.get("items") or [])
        self.align: str | None = None
        self.before_ms = self.after_ms = self.bin_ms = 0.0
        self.edge = "start"
        self.inside = True
        self.follow = False
        self._cache: tuple | None = None                  # (signature, profiles, moment count)
        self.profiles: list[tuple[dict, object]] = []     # (item, its EventAverage) for what is drawn
        self.message = ""

        self.plot = pg.PlotWidget()
        self.plot.setMouseEnabled(False, False)
        self.plot.hideButtons()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        self.plot.setLabel("left", "rate per item (Hz)")
        self.zero = pg.InfiniteLine(pos=0, angle=90, movable=False, pen=pg.mkPen("#e0a030", width=2))
        self.plot.addItem(self.zero)
        self.legend = self.plot.addLegend(offset=(-10, 10))
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.table = QTableWidget(0, len(COLUMNS))
        self.table.setHorizontalHeaderLabels(COLUMNS)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.verticalHeader().hide()
        self.table.setMaximumHeight(160)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.status)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.table)
        self.enable_hover(self.table.viewport())
        self.table.cellClicked.connect(self._row_clicked)
        self.events.subscribe(self._invalidate)
        self.reset_settings()

    # -- the settings -----------------------------------------------------------------------------------------------
    def _event_names(self) -> list[str]:
        return self.events.names()

    def settings(self):
        names = self._event_names()
        return [
            ViewSetting("align", "Align to", "choice", self.align or NONE, [(n, n) for n in names] or [(NONE, NONE)],
                        "The event whose every moment is lined up at zero."),
            ViewSetting("edge", "For an interval, align to its", "choice", self.edge, [("start", "start"), ("end", "stop")],
                        "Which end of an interval event (a touch with a start and an end) is the moment."),
            ViewSetting("before_ms", "Before the moment", "choice", self.before_ms, [(f"{v} ms", float(v)) for v in BEFORE_MS]),
            ViewSetting("after_ms", "After the moment", "choice", self.after_ms, [(f"{v} ms", float(v)) for v in AFTER_MS]),
            ViewSetting("bin_ms", "Bin size", "choice", self.bin_ms, [(f"{v} ms", float(v)) for v in BIN_MS],
                        "The width of the bins the rate is counted in."),
            ViewSetting("inside", "Only moments in the shown segments", "toggle", self.inside,
                        description="Count only the moments that fall inside the segments the filters and clips leave."),
            ViewSetting("follow_selection", "Follow the selected items", "toggle", self.follow,
                        description="Show the units or groups that are selected, replacing what this view shows."),
        ]

    def apply_setting(self, key: str, value) -> None:
        if key == "align":
            self.align = value if value in self._event_names() else None
        elif key == "edge":
            self.edge = value if value in ("start", "stop") else "start"
        elif key in ("before_ms", "after_ms", "bin_ms"):
            setattr(self, key, float(value))
        elif key == "inside":
            self.inside = bool(value)
        elif key == "follow_selection":
            self.follow = bool(value)
            if self.follow:
                self.selection_changed()
        self._invalidate()

    def reset_settings(self) -> None:
        d = self.defaults
        names = self._event_names()
        self.align = d["align"] if d["align"] in names else (self.events.tracked[0] if self.events.tracked else (names[0] if names else None))
        self.before_ms, self.after_ms, self.bin_ms = d["before_ms"], d["after_ms"], d["bin_ms"]
        self.edge, self.inside, self.follow = d["edge"], d["inside"], d["follow"]
        self._items = list(self.spec.get("items") or [])
        if self.follow:
            self.selection_changed()
        self._invalidate()

    # -- what is drawn ------------------------------------------------------------------------------------------------
    def selectable_targets(self):
        return [self._target(item) for item in self._items]

    def _target(self, item: dict) -> Target:
        if "group" in item:
            return Target("", item["group"], "group", None, item.get("name", item["group"]))
        source, path = split_ref(item["from"])
        return Target(source, path, "events", item.get("member"), item.get("name", ""))

    def selection_changed(self) -> None:
        if self.follow:
            items = [i for i in (self.item_of(t) for t in self.context.selection.targets) if i is not None]
            if items and items != self._items:
                self._items = items
                self._invalidate()
        self.table.blockSignals(True)
        chosen = [self.is_selected(self._target(i)) for i, _ in self.profiles]
        for row, on in enumerate(chosen):
            self.table.selectRow(row) if on else None
        self.table.blockSignals(False)

    def _invalidate(self) -> None:
        self._cache = None
        if self.isVisible():
            self.refresh(0.0)

    def _streams(self, item: dict) -> list[np.ndarray]:
        resources = self.context.resources
        if "group" in item:
            return [s.times for s in self.context.groups.series(resources, item["group"])]
        return [resources.events(item["from"], item.get("member")).times]

    def _moments(self) -> np.ndarray:
        data = self.events.find(self.align)
        moments = anchors_from(data, self.edge)
        nav = self.context.navigator
        if self.inside and nav is not None:
            starts, stops = nav.visible_bounds()
            moments = within_segments(moments, starts, stops)
        return moments

    def _signature(self):
        nav = self.context.navigator
        shown = () if nav is None or not self.inside else (id(nav.intervals), nav.match_count,
                                                           float(nav.visible_bounds()[0].sum()), float(nav.visible_bounds()[1].sum()))
        return (self.align, self.edge, self.before_ms, self.after_ms, self.bin_ms, self.inside, shown,
                tuple(repr(sorted(i.items())) for i in self._items))

    def compute(self) -> None:
        """Work out the profiles for the current choices (kept until a choice, the conditions or the shown segments change)."""
        signature = self._signature()
        if self._cache is not None and self._cache[0] == signature:
            return
        self.profiles, self.message = [], ""
        if not self._items:
            self.message = "Select units or a group, or open one with Open as view."
        elif self.align is None:
            self.message = "The project names no event to align to."
        else:
            try:
                moments = self._moments()
            except Exception as exc:                      # this recording lacks the event
                moments, self.message = None, f"'{self.align}' is not in this recording ({exc})."
            if moments is not None and len(moments) == 0:
                self.message = f"No moment of '{self.align}' falls in the shown segments."
            elif moments is not None:
                for item in self._items:
                    try:
                        self.profiles.append((item, peri_event_rate(self._streams(item), moments, self.before_ms / 1000,
                                                                  self.after_ms / 1000, self.bin_ms / 1000)))
                    except Exception as exc:              # this recording lacks the item
                        self.message = f"{item.get('name', '?')}: {exc}"
        self._cache = (signature,)

    def refresh(self, time: float) -> None:
        self.compute()
        self._draw()

    def _draw(self) -> None:
        self.plot.clear()
        self.plot.addItem(self.zero)
        if self.legend is not None:
            self.legend.clear()
        n = len(self.profiles)
        span = max(min(self.before_ms, self.after_ms), self.bin_ms) / 1000
        rows = []
        for i, (item, profile) in enumerate(self.profiles):
            colour = pg.intColor(i, hues=max(n, 6), values=1, maxValue=220)
            x = profile.centres * 1000
            top = self.plot.plot(x, profile.mean + profile.sem, pen=None)
            bottom = self.plot.plot(x, np.maximum(profile.mean - profile.sem, 0), pen=None)
            band = pg.mkColor(colour)
            band.setAlpha(60)
            self.plot.addItem(pg.FillBetweenItem(top, bottom, brush=pg.mkBrush(band)))
            selected = self.is_selected(self._target(item))
            self.plot.plot(x, profile.mean, pen=pg.mkPen(colour, width=3 if selected else 1.5), name=item.get("name", ""))
            rows.append(item_row(item.get("name", ""), profile, span))
        self.plot.setLabel("bottom", f"ms from {self.align or 'the event'}")
        moments = self.profiles[0][1].count if self.profiles else 0
        self.status.setText(self.message or (f"{moments} moments of {self.align}" if self.profiles else ""))
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            cells = [row.name, str(row.moments), f"{row.before:.2f}", f"{row.after:.2f}", f"{row.change:+.2f}", f"{row.peak:.2f}",
                     f"{row.peak_delay * 1000:.0f}"]
            for c, text in enumerate(cells):
                cell = QTableWidgetItem(text)
                if c:
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, c, cell)
        self.table.resizeColumnsToContents()

    # -- pointing ---------------------------------------------------------------------------------------------
    def target_at(self, pos):
        row = self.table.rowAt(self.table.viewport().mapFrom(self, pos).y())
        return self._target(self.profiles[row][0]) if 0 <= row < len(self.profiles) else None

    def _row_clicked(self, row: int, _column: int) -> None:
        if 0 <= row < len(self.profiles):
            from PySide6.QtWidgets import QApplication

            self.click_at(self._target(self.profiles[row][0]), QApplication.keyboardModifiers())

    def show_target(self, target) -> bool:
        item = self.item_of(target)
        if item is None:
            return False
        self._items = [item]
        self._invalidate()
        return True
