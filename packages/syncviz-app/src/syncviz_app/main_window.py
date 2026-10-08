"""The window: fixed components around a dockable area of views.

Always present: playback and filter controls (top), project information (left),
the timeline strip (bottom). In the middle, every view the project declares is a
dock panel the user can rearrange, tab, float or hide. Video is just one of them.
"""

from __future__ import annotations

import time

from PySide6.QtGui import QKeySequence
from PySide6.QtCore import QByteArray, QElapsedTimer, QTimer, Qt
from PySide6.QtWidgets import QDialog, QDockWidget, QMainWindow, QSplitter, QVBoxLayout, QWidget

from syncviz_app.context import AppContext
from syncviz_app.debug import DebugTools
from syncviz_app.controls import FilterBar, NavigationBar
from syncviz_app.info_panel import InfoPanel
from syncviz_app.layout import DEFAULT_NAME, Layout, delete_layout, list_layouts, load_layout, save_layout
from syncviz_app.project import Project
from syncviz_app.refresh import PUMP_INTERVAL_S, RefreshScheduler
from syncviz_app.stall import StallGuard
from syncviz_app.timeline_bar import TimelineBar
from syncviz_app.view_factory import create_view, fit_timeline, register_view, unique_title, unregister_view
from syncviz_app.views_panel import ViewsPanel
from syncviz_app.views.base import View

PLAYBACK_TICK_MS = 16           # the playhead advances by elapsed wall time, so this only sets its granularity


class MainWindow(QMainWindow):
    def __init__(self, project: Project, context: AppContext, views: list[View], debug: bool = False,
                 layout: Layout | None = None, layout_dir=None, layout_name: str = DEFAULT_NAME) -> None:
        super().__init__()
        self.layout_dir = layout_dir                        # this project's layouts folder; None = layouts are off
        self.layout_name = layout_name                      # the layout in use (it may not be saved yet)
        saved = layout or Layout()
        self._added: dict[str, dict] = {s.get("title") or s["type"]: s for s in saved.added}
        self._removed: list[str] = list(saved.removed)
        self.project, self.context, self.views = project, context, views
        self._colors_used = len(views)                       # colours are never reused, even after a removal
        self._set_title()
        self.resize(1500, 900)

        filter_attrs = []
        for spec in project.segmentation_specs.values():
            filter_attrs = spec.get("filters", [])
            break
        # Top row: playback and the two ways of moving (by segment, by frame). Second row: filters.
        self.navigation = NavigationBar(context)
        self.navigation.setObjectName("navigation")
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.navigation)
        self.filter_bar = None
        if context.navigator is not None:
            self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
            self.filter_bar = FilterBar(context, filter_attrs)
            self.filter_bar.setObjectName("filters")
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.filter_bar)

        # The sidebar: which views are showing, above what the project contains.
        self.info = InfoPanel(project, context)
        self.docks: list[QDockWidget] = []
        self.view_host = QMainWindow()
        self.views_panel: ViewsPanel | None = None
        sidebar = QSplitter(Qt.Orientation.Vertical)
        info_dock = QDockWidget("Project", self)
        info_dock.setWidget(sidebar)
        info_dock.setObjectName("project")
        info_dock.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetMovable)   # always present
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, info_dock)

        # Views live in their own dock host so the timeline strip can sit beneath all of them.
        self.view_host.setWindowFlags(Qt.WindowType.Widget)
        self.view_host.setDockNestingEnabled(True)
        for i, view in enumerate(views):
            self.docks.append(self._make_dock(view, view.spec.get("area", "left" if i == 0 else "right")))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.view_host, 1)
        self.timeline_bar = TimelineBar(context)
        layout.addWidget(self.timeline_bar)
        self.setCentralWidget(central)

        self.layout_menu = self.menuBar().addMenu("&Layout")
        self.layout_menu.aboutToShow.connect(self._fill_layout_menu)
        self._fill_layout_menu()

        self.views_panel = ViewsPanel(self)
        sidebar.addWidget(self.views_panel)
        sidebar.addWidget(self.info)
        sidebar.setStretchFactor(1, 1)

        # Views redraw from a scheduler, not on every playhead event. Each has its own rate,
        # and a governor lowers them all if the interface starts to fall behind (see refresh.py).
        self.scheduler = RefreshScheduler(views)
        context.timeline.subscribe(lambda _t: self.scheduler.changed())
        self.stall_guard = StallGuard(context.timeline, views)
        self.debug = DebugTools(self) if debug else None      # off unless run in debug mode
        self._pump_timer = QTimer(self)
        self._pump_timer.setTimerType(Qt.TimerType.PreciseTimer)      # the governor reads this timer's lateness
        self._pump_timer.timeout.connect(self._pump)
        self._pump_timer.start(int(PUMP_INTERVAL_S * 1000))

        if layout_dir is not None:
            self._restore_layout(saved)
        else:
            QTimer.singleShot(0, self._apply_initial_sizes)

        self._clock = QElapsedTimer()
        self._clock.start()
        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._play_timer.timeout.connect(self._tick)
        self._play_timer.start(PLAYBACK_TICK_MS)

    # -- layouts -----------------------------------------------------------------------------
    def _restore_layout(self, saved: Layout, geometry: bool = True) -> None:
        """Apply saved panel positions (after every panel exists), and the window's size if `geometry`."""
        def decode(text):
            return QByteArray.fromBase64(text.encode("ascii"))

        if geometry and saved.window:
            self.restoreGeometry(decode(saved.window))
        if saved.main_state:
            self.restoreState(decode(saved.main_state))
        restored = bool(saved.views_state) and self.view_host.restoreState(decode(saved.views_state))
        if not restored:
            QTimer.singleShot(0, self._apply_initial_sizes)
        if self.views_panel is not None:
            self.views_panel.sync()

    def current_layout(self) -> Layout:
        def encode(data):
            return bytes(data.toBase64()).decode("ascii")

        return Layout(
            added=[dict(s) for s in self._added.values()],
            removed=list(self._removed),
            window=encode(self.saveGeometry()),
            main_state=encode(self.saveState()),
            views_state=encode(self.view_host.saveState()),
        )

    def _set_title(self) -> None:
        suffix = f" — layout {self.layout_name}" if self.layout_dir is not None else ""
        self.setWindowTitle(f"Sync Visualizer — {self.project.name}{suffix}")

    def saved_layout_names(self) -> list[str]:
        return list_layouts(self.layout_dir) if self.layout_dir is not None else []

    def save_layout_clicked(self) -> None:
        """Write the arrangement in use to its file. Nothing is saved unless this is asked for."""
        if self.layout_dir is None:
            self.statusBar().showMessage("Layouts are not kept in this mode", 4000)
            return
        try:
            save_layout(self.layout_dir, self.layout_name, self.current_layout())
        except OSError as exc:
            self.context.notes.append(f"layout not saved: {exc}")
            self.statusBar().showMessage(f"Could not save layout: {exc}", 8000)
            return
        self.statusBar().showMessage(f"Saved layout '{self.layout_name}'", 4000)

    def apply_layout(self, layout: Layout) -> None:
        """Make the window match a layout now: the views it has, then where the panels are."""
        wanted = [s for s in self.project.view_specs if (s.get("title") or s["type"]) not in layout.removed]
        wanted += layout.added
        titles = [s.get("title") or s["type"] for s in wanted]
        for view in [v for v in self.views if v.title not in titles]:
            self.remove_view(view)
        have = {v.title for v in self.views}
        for spec in wanted:
            if (spec.get("title") or spec["type"]) not in have:
                self.add_view(spec)
        self._added = {s.get("title") or s["type"]: s for s in layout.added}
        self._removed = list(layout.removed)
        self._restore_layout(layout, geometry=False)           # the window keeps its size when switching
        self._views_changed()

    def switch_layout(self, name: str) -> bool:
        """Open a saved layout. Changes to the one in use that were not saved are dropped."""
        layout = load_layout(self.layout_dir, name) if self.layout_dir is not None else None
        if layout is None:
            return False
        self.layout_name = name
        self._set_title()
        self.apply_layout(layout)
        return True

    def save_layout_as(self, name: str) -> bool:
        """Save the current arrangement under a new name and carry on in it (an existing name is overwritten)."""
        name = name.strip()
        if not name or self.layout_dir is None:
            return False
        self.layout_name = name
        self._set_title()
        self.save_layout_clicked()
        return True

    def delete_layout(self, name: str) -> bool:
        """Delete a saved layout. If it is the one in use, the window keeps its arrangement but is
        no longer attached to a saved file (saving writes it again)."""
        if self.layout_dir is None or name not in self.saved_layout_names():
            return False
        delete_layout(self.layout_dir, name)
        self.statusBar().showMessage(f"Deleted layout '{name}'", 4000)
        return True

    def reset_layout(self) -> None:
        """Put the window back to the project's own views and the default arrangement. This changes
        only what is on screen; it is saved if and when the user saves."""
        self.apply_layout(Layout())
        self.statusBar().showMessage("Showing the project's defaults (save to keep them as this layout)", 6000)

    def _fill_layout_menu(self) -> None:
        from PySide6.QtGui import QAction, QActionGroup

        menu = self.layout_menu
        menu.clear()
        enabled = self.layout_dir is not None
        saved = self.saved_layout_names()
        group = QActionGroup(menu)
        for name in dict.fromkeys(saved + ([self.layout_name] if enabled else [])):
            action = QAction(name if name in saved else f"{name} (not saved yet)", menu)
            action.setCheckable(True)
            action.setChecked(name == self.layout_name)
            action.setEnabled(enabled and name in saved)
            action.triggered.connect(lambda _c=False, n=name: self.switch_layout(n))
            group.addAction(action)
            menu.addAction(action)
        menu.addSeparator()
        save = menu.addAction(f"Save layout '{self.layout_name}'", self.save_layout_clicked)
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.setEnabled(enabled)
        as_new = menu.addAction("Save layout as…", self._ask_save_layout_as)
        as_new.setEnabled(enabled)
        delete = menu.addAction(f"Delete layout '{self.layout_name}'", lambda: self.delete_layout(self.layout_name))
        delete.setEnabled(enabled and self.layout_name in saved)
        menu.addAction("Reset to the project's defaults", self.reset_layout)

    def _ask_save_layout_as(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Save layout as", "Name for this arrangement of views and panels:")
        if ok:
            self.save_layout_as(name)

    def _make_dock(self, view: View, area: str) -> QDockWidget:
        dock = QDockWidget(view.title)
        dock.setObjectName(f"view:{view.title}")
        dock.setWidget(view)
        colour = self.context.colors.get(view.title)
        if colour:      # the stripe matches this view's line in the timeline's data coverage
            dock.setStyleSheet(f"QDockWidget::title {{ border-left: 6px solid {colour}; padding-left: 6px; }}")
        dock.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        where = {"left": Qt.DockWidgetArea.LeftDockWidgetArea,
                 "right": Qt.DockWidgetArea.RightDockWidgetArea,
                 "bottom": Qt.DockWidgetArea.BottomDockWidgetArea}.get(area, Qt.DockWidgetArea.RightDockWidgetArea)
        self.view_host.addDockWidget(where, dock)
        return dock

    # -- adding and removing views ---------------------------------------------------------
    def source_catalog(self) -> dict:
        """What every source offers, by source name (see Source.catalog)."""
        return {name: source.catalog() for name, source in self.context.resources.sources.items()}

    def choose_view_to_add(self) -> None:
        from syncviz_app.add_view_dialog import AddViewDialog

        dialog = AddViewDialog(self.source_catalog(), self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.spec() is not None:
            self.add_view(dialog.spec())

    def add_view(self, spec: dict) -> View | None:
        """Create a view from a spec and show it. Returns None (with a note in the project panel) if
        it could not be created."""
        spec = {**spec, "title": unique_title(self.context, spec.get("title") or spec["type"])}
        view = create_view(self.context, spec)
        if view is None:
            self._views_changed()
            return None
        self.views.append(view)
        register_view(self.context, view, self._colors_used)
        self._colors_used += 1
        self.docks.append(self._make_dock(view, spec.get("area", "right")))
        self._added[view.title] = spec
        self._views_changed()
        return view

    def remove_view(self, view: View) -> None:
        if view not in self.views:
            return
        i = self.views.index(view)
        dock = self.docks.pop(i)
        self.views.pop(i)
        self.view_host.removeDockWidget(dock)
        dock.deleteLater()
        view.close_view()
        unregister_view(self.context, view)
        if self._added.pop(view.title, None) is None and view.title not in self._removed:
            self._removed.append(view.title)               # one of the project's own views
        self._views_changed()

    def _views_changed(self) -> None:
        """Bring everything that lists or depends on the views up to date."""
        fit_timeline(self.context)
        self.timeline_bar.rebuild()
        self.navigation.refresh_bases()
        self.info.rebuild()
        if self.views_panel is not None:
            self.views_panel.rebuild()
        self.scheduler.changed()

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
        now = time.perf_counter()
        self.scheduler.pump(now, self.context.timeline.time)
        self.stall_guard.check(now)

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
