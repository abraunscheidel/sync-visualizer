"""The window: fixed components around a dockable area of views.

Always present: playback and filter controls (top), project information (left),
the timeline strip (bottom). In the middle, every view the project declares is a
dock panel the user can rearrange, tab, float or hide. Video is just one of them.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QElapsedTimer, QTimer, Qt
from PySide6.QtWidgets import QDockWidget, QMainWindow, QVBoxLayout, QWidget

from syncviz_app.context import AppContext
from syncviz_app.controls import ControlsBar
from syncviz_app.info_panel import InfoPanel
from syncviz_app.project import Project
from syncviz_app.refresh import PUMP_INTERVAL_S, RefreshScheduler
from syncviz_app.timeline_bar import TimelineBar
from syncviz_app.views.base import View

PLAYBACK_TICK_MS = 16           # the playhead advances by elapsed wall time, so this only sets its granularity


class MainWindow(QMainWindow):
    def __init__(self, project: Project, context: AppContext, views: list[View]) -> None:
        super().__init__()
        self.project, self.context, self.views = project, context, views
        self.setWindowTitle(f"Sync Visualizer — {project.name}")
        self.resize(1500, 900)

        filter_attrs = []
        for spec in project.segmentation_specs.values():
            filter_attrs = spec.get("filters", [])
            break
        self.controls = ControlsBar(context, filter_attrs)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.controls)

        self.info = InfoPanel(project, context)
        info_dock = QDockWidget("Project", self)
        info_dock.setWidget(self.info)
        info_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)   # always present
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, info_dock)

        # Views live in their own dock host so the timeline strip can sit beneath all of them.
        self.view_host = QMainWindow()
        self.view_host.setWindowFlags(Qt.WindowType.Widget)
        self.view_host.setDockNestingEnabled(True)
        self.docks: list[QDockWidget] = []
        for i, view in enumerate(views):
            dock = QDockWidget(view.title)
            dock.setWidget(view)
            dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
            area = {"left": Qt.DockWidgetArea.LeftDockWidgetArea,
                    "right": Qt.DockWidgetArea.RightDockWidgetArea,
                    "bottom": Qt.DockWidgetArea.BottomDockWidgetArea}.get(
                        view.spec.get("area", "left" if i == 0 else "right"), Qt.DockWidgetArea.RightDockWidgetArea)
            self.view_host.addDockWidget(area, dock)
            self.docks.append(dock)
        QTimer.singleShot(0, self._apply_initial_sizes)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view_host, 1)
        self.timeline_bar = TimelineBar(context)
        layout.addWidget(self.timeline_bar)
        self.setCentralWidget(central)

        view_menu = self.menuBar().addMenu("&Views")
        for dock in self.docks:
            view_menu.addAction(dock.toggleViewAction())

        # Views redraw from a scheduler, not on every playhead event. Each has its own rate,
        # and a governor lowers them all if the interface starts to fall behind (see refresh.py).
        self.scheduler = RefreshScheduler(views)
        context.timeline.subscribe(lambda _t: self.scheduler.changed())
        self._pump_timer = QTimer(self)
        self._pump_timer.setTimerType(Qt.TimerType.PreciseTimer)      # the governor reads this timer's lateness
        self._pump_timer.timeout.connect(self._pump)
        self._pump_timer.start(int(PUMP_INTERVAL_S * 1000))

        self._clock = QElapsedTimer()
        self._clock.start()
        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._play_timer.timeout.connect(self._tick)
        self._play_timer.start(PLAYBACK_TICK_MS)

    def _apply_initial_sizes(self) -> None:
        """Give the first (left) view about half the width; stack the rest evenly on the right."""
        left = [d for d in self.docks if self.view_host.dockWidgetArea(d) == Qt.DockWidgetArea.LeftDockWidgetArea]
        right = [d for d in self.docks if self.view_host.dockWidgetArea(d) == Qt.DockWidgetArea.RightDockWidgetArea]
        width, height = self.view_host.width(), self.view_host.height()
        if left and right:
            self.view_host.resizeDocks(left[:1] + right[:1], [int(width * 0.5), int(width * 0.5)],
                                       Qt.Orientation.Horizontal)
        if len(right) > 1:
            self.view_host.resizeDocks(right, [height // len(right)] * len(right), Qt.Orientation.Vertical)

    def _tick(self) -> None:
        dt = self._clock.restart() / 1000.0
        self.context.timeline.advance(dt)

    def _pump(self) -> None:
        self.scheduler.pump(time.perf_counter(), self.context.timeline.time)

    def refresh_now(self) -> None:
        """Redraw every visible view immediately, ignoring rate limits."""
        self.scheduler.changed()
        self.scheduler.pump(time.perf_counter(), self.context.timeline.time, force=True)

    def closeEvent(self, event) -> None:
        self._play_timer.stop()
        self._pump_timer.stop()
        for view in self.views:
            view.close_view()
        super().closeEvent(event)
