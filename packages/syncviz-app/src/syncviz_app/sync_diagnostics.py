"""The synchronization diagnostics window and the always-visible status that goes with it.

This belongs with the application's own components, not among the views: it is not drawn at the playhead, is not part of a
workspace's arrangement, and is about how the sources relate to each other. The checks themselves come from
`syncviz.diagnostics` (generic) and from each source (`Source.diagnostics`); this module only runs and shows them.
"""

from __future__ import annotations

import threading

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QSplitter, QTextBrowser, QVBoxLayout, QWidget,
)

from syncviz import diagnostics
from syncviz.core import Seek
from syncviz.diagnostics import CheckResult, Status
from syncviz_app import sync_checks

MARKS = {Status.PASS: "✔", Status.WARN: "▲", Status.FAIL: "✖", Status.INCONCLUSIVE: "?", Status.NOT_APPLICABLE: "–"}
COLOURS = {Status.PASS: "#3fae5a", Status.WARN: "#e0a030", Status.FAIL: "#d9534f",
           Status.INCONCLUSIVE: "#8a8a8a", Status.NOT_APPLICABLE: "#8a8a8a"}
SLOW_RUN_NOTE = "Running. The first run on a long video scans every frame, which can take several minutes; later runs are instant."


class SyncDiagnostics(QObject):
    """Results of the checks for the open collection, and running them without freezing the window."""

    changed = Signal()
    _finished = Signal(int, object)            # collection index, results or an error message

    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self.results: list[CheckResult] = []
        self.running = False
        self.error = ""
        self._finished.connect(self._done)

    @property
    def project(self):
        return self.window.project

    @property
    def configured(self) -> bool:
        return sync_checks.has_checks(self.project)

    def summary(self) -> str:
        if self.running:
            return "running…"
        if self.error:
            return "could not run"
        return diagnostics.summarize(self.results)

    def worst(self) -> Status | None:
        return diagnostics.overall(self.results)

    def load_cached(self) -> None:
        """Show saved results for the open collection, if there are any. Never computes."""
        self.results = sync_checks.load_cached(self.project, self.project.active) or []
        self.error = ""
        self.changed.emit()

    def run(self, wait: bool = False) -> None:
        """Run every check for the open collection on another thread, then keep and show the results."""
        if self.running:
            return
        self.running, self.error = True, ""
        index = self.project.active
        self.changed.emit()

        def work() -> None:
            try:
                self._finished.emit(index, sync_checks.run_checks(self.project, index))
            except Exception as exc:                      # shown, not raised: this runs off the main thread
                self._finished.emit(index, str(exc))

        thread = threading.Thread(target=work, name="sync-checks", daemon=True)
        thread.start()
        if wait:
            thread.join()

    def _done(self, index: int, outcome) -> None:
        self.running = False
        if isinstance(outcome, str):
            self.error = outcome
        else:
            sync_checks.store(self.project, index, outcome)
            if index == self.project.active:                  # the user may have moved on to another collection
                self.results = outcome
        self.changed.emit()


class SyncStatus(QWidget):
    """One line in the sidebar that says how the sync checks stand, and opens the window."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.button = QPushButton("Sync diagnostics…")
        self.button.clicked.connect(window.open_sync_diagnostics)
        layout.addWidget(self.label, 1)
        layout.addWidget(self.button)
        window.sync.changed.connect(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        sync = self.window_.sync
        if not sync.configured:
            self.label.setText("Sync: no checks configured")
            self.label.setStyleSheet("")
            return
        worst = sync.worst()
        colour = COLOURS.get(worst, "") if worst else ""
        self.label.setText(f"Sync: {sync.summary()}")
        self.label.setStyleSheet(f"color: {colour}; font-weight: 600;" if colour else "")


class SyncDiagnosticsWindow(QWidget):
    """The checks as a list, with the evidence for the selected one drawn beside it."""

    def __init__(self, window) -> None:
        super().__init__()
        self.window_ = window
        self.sync = window.sync
        self.setWindowTitle("Sync diagnostics")
        self.resize(980, 560)
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self.heading = QLabel()
        self.heading.setStyleSheet("font-weight: 600;")
        self.run_button = QPushButton("Run checks")
        self.run_button.clicked.connect(lambda: self.sync.run())
        top.addWidget(self.heading, 1)
        top.addWidget(self.run_button)
        layout.addLayout(top)
        self.note = QLabel()
        self.note.setWordWrap(True)
        self.note.setEnabled(False)
        layout.addWidget(self.note)
        split = QSplitter(Qt.Orientation.Horizontal)
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        self.list = QListWidget()
        left_layout.addWidget(self.list, 1)
        self.text = QTextBrowser()
        left_layout.addWidget(self.text, 1)
        split.addWidget(left)
        self.plot = pg.PlotWidget()
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.2)
        split.addWidget(self.plot)
        split.setStretchFactor(1, 1)
        layout.addWidget(split, 1)
        self.list.currentRowChanged.connect(self._show)
        self.sync.changed.connect(self.refresh)
        self.refresh()

    # -- content ---------------------------------------------------------------------------
    def refresh(self) -> None:
        project = self.window_.project
        self.heading.setText(f"{project.collection.title}   —   tolerance ±{self._tolerance():g} ms")
        self.run_button.setEnabled(not self.sync.running)
        self.run_button.setText("Running…" if self.sync.running else "Run checks")
        self.note.setText(SLOW_RUN_NOTE if self.sync.running else
                          (f"Could not run: {self.sync.error}" if self.sync.error else
                           ("" if self.sync.results else "No results yet for this recording. Run the checks to see them.")))
        row = max(self.list.currentRow(), 0)
        self.list.blockSignals(True)
        self.list.clear()
        for result in self.sync.results:
            item = QListWidgetItem(f"{MARKS[result.status]}  {result.name}")
            item.setForeground(pg.mkColor(COLOURS[result.status]))
            self.list.addItem(item)
        self.list.blockSignals(False)
        if self.sync.results:
            self.list.setCurrentRow(min(row, len(self.sync.results) - 1))
            self._show(self.list.currentRow())
        else:
            self.text.clear()
            self.plot.clear()

    def _tolerance(self) -> float:
        return float((self.window_.project.config.get("sync") or {}).get("tolerance_ms", diagnostics.DEFAULT_TOLERANCE_MS))

    def _show(self, row: int) -> None:
        if not 0 <= row < len(self.sync.results):
            return
        result = self.sync.results[row]
        lines = [f"<b>{result.name}</b><br><span style='color:{COLOURS[result.status]}'><b>{MARKS[result.status]} "
                 f"{result.status.value}</b></span> &mdash; {result.summary}<br><br>"]
        lines += [f"{d}<br>" for d in result.details]
        self.text.setHtml("".join(lines))
        self._draw(result)

    # -- evidence --------------------------------------------------------------------------
    def _draw(self, result: CheckResult) -> None:
        plot = self.plot
        plot.clear()
        data = result.data
        if result.kind == "paired_events" and "error_ms" in data:
            self._draw_pairs(data)
        elif result.kind == "event_response" and "rate" in data:
            self._draw_response(data)

    def _draw_pairs(self, data: dict) -> None:
        plot = self.plot
        when, error = np.asarray(data["when"]), np.asarray(data["error_ms"])
        tol = data["tolerance_ms"]
        plot.setLabel("bottom", "time in the recording", units="s")
        plot.setLabel("left", "error (test minus reference)", units="ms")
        band = pg.LinearRegionItem(values=(-tol, tol), orientation="horizontal", movable=False,
                                   brush=pg.mkBrush(63, 174, 90, 40))
        plot.addItem(band)
        plot.addItem(pg.InfiniteLine(pos=0, angle=0, pen=pg.mkPen("#888888", style=Qt.PenStyle.DashLine)))
        outside = np.abs(error) > tol
        points = pg.ScatterPlotItem(when, error, size=7, pen=None,
                                    brush=[pg.mkBrush("#d9534f" if o else "#4fa3e0") for o in outside])
        points.sigClicked.connect(self._clicked)
        plot.addItem(points)
        fit_x = np.array([when.min(), when.max()])
        plot.plot(fit_x, data["intercept_ms"] + data["slope"] * fit_x, pen=pg.mkPen("#e0a030", width=2))
        # Always show the tolerance band, however small the errors are.
        plot.setYRange(min(error.min(), -1.5 * tol), max(error.max(), 1.5 * tol))

    def _draw_response(self, data: dict) -> None:
        plot = self.plot
        plot.setLabel("bottom", "time from the stimulus", units="ms")
        plot.setLabel("left", "rate per series", units="events/s")
        lo, hi = data["expect_ms"]
        plot.addItem(pg.LinearRegionItem(values=(lo, hi), movable=False, brush=pg.mkBrush(63, 174, 90, 50)))
        plot.addItem(pg.InfiniteLine(pos=0, angle=90, pen=pg.mkPen("#888888", style=Qt.PenStyle.DashLine)))
        plot.addItem(pg.InfiniteLine(pos=float(data["baseline"]), angle=0, pen=pg.mkPen("#888888", style=Qt.PenStyle.DotLine)))
        plot.plot(np.asarray(data["centers_ms"]), np.asarray(data["rate"]), pen=pg.mkPen("#4fa3e0", width=2))
        plot.addItem(pg.InfiniteLine(pos=float(data["peak_ms"]), angle=90, pen=pg.mkPen("#e0a030", width=2)))

    def _clicked(self, _plot, points) -> None:
        """Clicking a pair moves the playhead there, so the moment can be looked at in the other views."""
        if len(points):
            self.window_.context.bus.publish(Seek(float(points[0].pos().x())))
