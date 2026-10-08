"""The window: fixed components around a dockable area of views.

Always present: playback and filter controls (top), project information (left),
the timeline strip (bottom). In the middle, every view the project declares is a
dock panel the user can rearrange, tab, float or hide. Video is just one of them.
"""

from __future__ import annotations

import time

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import QByteArray, QElapsedTimer, QTimer, Qt
from syncviz import plugins
from syncviz_app.details_panel import DetailsPanel
from syncviz_app.target_actions import TargetAction
from syncviz_app.loading import LoadingScreen, run_in_background
from PySide6.QtWidgets import QDialog, QDockWidget, QMainWindow, QSplitter, QVBoxLayout, QWidget

from syncviz_app.context import AppContext
from syncviz_app.debug import DebugTools
from syncviz_app.controls import CollectionBar, FilterBar, NavigationBar
from syncviz_app.info_panel import InfoPanel
from syncviz.core import Seek, SetPlaying
from syncviz_app.workspace import (
    DEFAULT_NAME, Workspace, delete_workspace, list_workspaces, load_collection_state, load_workspace,
    save_collection_state, save_workspace,
)
from syncviz_app.project import Project
from syncviz_app.refresh import PUMP_INTERVAL_S, RefreshScheduler
from syncviz_app.stall import StallGuard
from syncviz_app.sync_diagnostics import SyncDiagnostics, SyncDiagnosticsWindow, SyncStatus
from syncviz_app.timeline_bar import TimelineBar
from syncviz_app.view_factory import create_view, fit_timeline, register_view, unique_title, unregister_view
from syncviz_app.views_panel import ViewsPanel
from syncviz_app.views.base import View, describe_delay

PLAYBACK_TICK_MS = 16           # the playhead advances by elapsed wall time, so this only sets its granularity


class MainWindow(QMainWindow):
    def __init__(self, project: Project, context: AppContext, views: list[View], debug: bool = False,
                 workspace: Workspace | None = None, workspace_dir=None, workspace_name: str = DEFAULT_NAME,
                 state_dir=None) -> None:
        super().__init__()
        self.sync = SyncDiagnostics(self)                         # sync checks for the open collection
        self._sync_window = None
        self.state_dir = state_dir                                # per-collection memory on disk; None = not kept
        self._memory: dict[str, dict] = {}                        # per-collection state while the app runs
        self.workspace_dir = workspace_dir                        # this project's workspaces folder; None = workspaces are off
        self.workspace_name = workspace_name                      # the workspace in use (it may not be saved yet)
        saved = workspace or Workspace()
        self._added: dict[str, dict] = {s.get("title") or s["type"]: s for s in saved.added}
        self._removed: list[str] = list(saved.removed)
        self._view_settings: dict[str, dict] = {}                # each view's own settings by title (see View.settings)
        self._lags: dict[str, float] = {}                       # display lag in ms by view title (see View.lag)
        self.project, self.context, self.views = project, context, views
        self._colors_used = len(views)                       # colours are never reused, even after a removal
        self._set_title()
        self.resize(1500, 900)

        filter_attrs = []
        for spec in project.segmentation_specs.values():
            filter_attrs = spec.get("filters", [])
            break
        # Rows, outermost scope first: which collection (only if the project has several); playback and the
        # ways of moving (by segment, by frame); then the segment filters.
        self.collection_bar = None
        if project.multiple:
            self.collection_bar = CollectionBar(self)
            self.collection_bar.setObjectName("collections")
            self.addToolBar(Qt.ToolBarArea.TopToolBarArea, self.collection_bar)
            self.addToolBarBreak(Qt.ToolBarArea.TopToolBarArea)
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

        self.loading = LoadingScreen(self)                      # covers the window while another collection opens
        self.details_panel = DetailsPanel(context)
        details_dock = QDockWidget("Details", self)
        details_dock.setWidget(self.details_panel)
        details_dock.setObjectName("details")
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, details_dock)
        self.details_dock = details_dock
        self._register_target_actions()

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

        tools = self.menuBar().addMenu("&Tools")
        tools.addAction("Sync diagnostics…", self.open_sync_diagnostics)
        self.workspace_menu = self.menuBar().addMenu("&Workspace")
        self.workspace_menu.aboutToShow.connect(self._fill_workspace_menu)
        self._fill_workspace_menu()

        self.views_panel = ViewsPanel(self)
        sidebar.addWidget(self.views_panel)
        self.sync_status = SyncStatus(self)                       # always visible: how the sync checks stand
        sidebar.addWidget(self.sync_status)
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

        if workspace_dir is not None:
            self._restore_workspace(saved)
        else:
            QTimer.singleShot(0, self._apply_initial_sizes)

        self._restore_collection()
        self.sync.load_cached()

        self._clock = QElapsedTimer()
        self._clock.start()
        self._play_timer = QTimer(self)
        self._play_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._play_timer.timeout.connect(self._tick)
        self._play_timer.start(PLAYBACK_TICK_MS)

    # -- workspaces -----------------------------------------------------------------------------
    def _restore_workspace(self, saved: Workspace, geometry: bool = True) -> None:
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
        self._apply_settings(saved.settings)

    def _register_target_actions(self) -> None:
        """The actions that need the window: showing the Details panel, opening a target as a view, and those of the views."""
        registry = self.context.actions

        def show_details(target, _origin) -> None:
            self.context.selection.set(target)
            self.details_dock.show()
            self.details_dock.raise_()

        def ways_to_open(target) -> list[TargetAction]:
            out = []
            for name in sorted(plugins.available("views")):
                try:
                    view_class = plugins.load("views", name)
                    spec = view_class.spec_for(target)
                except Exception:
                    continue
                if spec:
                    out.append(TargetAction(f"open_as_view:{name}", view_class.display_name or name,
                                            lambda _t, _o, spec=spec: self.add_view(spec)))
            return out

        registry.register(TargetAction("show_details", "Show details", show_details,
                                       description="Select this and bring up the Details panel"))
        registry.register(TargetAction("open_as_view", "Open as view", children=ways_to_open,
                                       description="Add a view that shows this"))
        registry.add_provider(lambda: [a for view in self.views for a in view.target_actions()])
        for action in registry.all():                                  # keyboard shortcuts act on the selection
            if action.shortcut:
                shortcut = QShortcut(QKeySequence(action.shortcut), self)
                shortcut.activated.connect(lambda a=action: registry.run(a.id, self.context.selection.target, None))

    def settings(self) -> dict:
        """The working state apart from the arrangement: filters, frame step and speed."""
        out = {"navigation": self.navigation.state(), "view_lags": dict(self._lags),
               "view_settings": {t: dict(v) for t, v in self._view_settings.items()}}
        out["inspection"] = self.details_panel.state()
        if self.filter_bar is not None:
            out["filters"] = self.filter_bar.state()
        if self.collection_bar is not None:
            out["collections"] = self.collection_bar.state()
        return out

    def set_view_lag(self, view: View, milliseconds: float) -> None:
        """Delay one view's display by `milliseconds` (negative: ahead). Display only."""
        if milliseconds:
            self._lags[view.title] = float(milliseconds)
        else:
            self._lags.pop(view.title, None)
        view.lag = float(milliseconds) / 1000.0
        if view in self.views:
            dock = self.docks[self.views.index(view)]
            dock.setWindowTitle(self._dock_title(view))
        self.scheduler.changed()                              # redraw at the new offset, even while paused

    @staticmethod
    def _dock_title(view: View) -> str:
        words = describe_delay(view.lag * 1000.0)
        return f"{view.title}   [{words}]" if words else view.title

    def _apply_lags(self, lags: dict[str, float]) -> None:
        """Give every view the lag in `lags` (by title), and the rest the lag their project file gives (lag_ms), else none."""
        self._lags = {}
        for view in self.views:
            self.set_view_lag(view, float(lags.get(view.title, view.spec.get("lag_ms", 0.0))))
        if self.views_panel is not None:
            self.views_panel.show_lag()

    def set_view_setting(self, view: View, key: str, value) -> None:
        """Change one of a view's own settings (see View.settings) and remember it."""
        if view is None:
            return
        self._view_settings.setdefault(view.title, {})[key] = value
        view.apply_setting(key, value)

    def _apply_view_settings(self, saved: dict) -> None:
        """Give every view the settings in `saved` (by title), and its project defaults for the rest."""
        self._view_settings = {}
        for view in self.views:
            view.reset_settings()
            for key, value in saved.get(view.title, {}).items():
                view.apply_setting(key, value)
            if saved.get(view.title):
                self._view_settings[view.title] = dict(saved[view.title])
        if self.views_panel is not None:
            self.views_panel.show_settings()

    def _apply_settings(self, settings: dict) -> None:
        self._apply_lags(settings.get("view_lags", {}))
        self._apply_view_settings(settings.get("view_settings", {}))
        self.navigation.apply_state(settings.get("navigation", {}))
        self.details_panel.apply_state(settings.get("inspection", {}))
        if self.filter_bar is not None:
            self.filter_bar.apply_state(settings.get("filters", {}))
        if self.collection_bar is not None:
            self.collection_bar.apply_state(settings.get("collections", {}))

    def current_workspace(self) -> Workspace:
        def encode(data):
            return bytes(data.toBase64()).decode("ascii")

        return Workspace(
            added=[dict(s) for s in self._added.values()],
            removed=list(self._removed),
            window=encode(self.saveGeometry()),
            main_state=encode(self.saveState()),
            views_state=encode(self.view_host.saveState()),
            settings=self.settings(),
        )

    def _set_title(self) -> None:
        collection = f" — {self.project.collection.title}" if self.project.multiple else ""
        suffix = f" — workspace {self.workspace_name}" if self.workspace_dir is not None else ""
        self.setWindowTitle(f"Sync Visualizer — {self.project.name}{collection}{suffix}")

    def saved_workspace_names(self) -> list[str]:
        return list_workspaces(self.workspace_dir) if self.workspace_dir is not None else []

    def save_workspace_clicked(self) -> None:
        """Write the arrangement in use to its file. Nothing is saved unless this is asked for."""
        if self.workspace_dir is None:
            self.statusBar().showMessage("Workspaces are not kept in this mode", 4000)
            return
        try:
            save_workspace(self.workspace_dir, self.workspace_name, self.current_workspace())
            if self.state_dir is not None:
                self._remember_collection()
                key = self.project.collection.key
                save_collection_state(self.state_dir, key, self._memory[key])
        except OSError as exc:
            self.context.notes.append(f"workspace not saved: {exc}")
            self.statusBar().showMessage(f"Could not save workspace: {exc}", 8000)
            return
        self.statusBar().showMessage(f"Saved workspace '{self.workspace_name}'", 4000)

    def _sync_views(self, workspace: Workspace, progress=None) -> None:
        """Add and remove views until the window has the ones a workspace calls for."""
        wanted = [s for s in self.project.view_specs if (s.get("title") or s["type"]) not in workspace.removed]
        wanted += workspace.added
        titles = [s.get("title") or s["type"] for s in wanted]
        for view in [v for v in self.views if v.title not in titles]:
            self.remove_view(view, track=False, refresh=False)
        have = {v.title for v in self.views}
        missing = [s for s in wanted if (s.get("title") or s["type"]) not in have]
        for done, spec in enumerate(missing):
            if progress is not None:
                progress(f"Building {spec.get('title') or spec['type']}  ({done + 1} of {len(missing)})", done, len(missing))
            self.add_view(spec, track=False, refresh=False)
        self._added = {s.get("title") or s["type"]: s for s in workspace.added}
        self._removed = list(workspace.removed)

    def apply_workspace(self, workspace: Workspace) -> None:
        """Make the window match a workspace now: the views it has, then where the panels are."""
        self._sync_views(workspace)
        self._restore_workspace(workspace, geometry=False)           # the window keeps its size when switching
        self._views_changed()

    # -- collections -----------------------------------------------------------------------
    def _remember_collection(self) -> None:
        self._memory[self.project.collection.key] = {"time": self.context.timeline.time}

    def _restore_collection(self) -> None:
        """Return to where the playhead was in the open collection (this run, else the saved file)."""
        key = self.project.collection.key
        state = self._memory.get(key) or (load_collection_state(self.state_dir, key) if self.state_dir else {})
        if "time" in state:
            self.context.bus.publish(Seek(float(state["time"])))

    def switch_collection(self, index: int) -> bool:
        """Open another collection: its sources, segments and views replace the current ones, and the
        workspace (which views, where, what settings) carries over. If it cannot be opened, nothing changes.
        A loading screen covers the window meanwhile, so it never looks frozen."""
        project = self.project
        if index == project.active:
            return True
        if not 0 <= index < len(project.collections) or self.loading.showing:
            return False
        self.loading.begin(f"Opening {project.collections[index].title}", "Reading the files…")
        try:
            return self._switch_collection(index)
        finally:
            self.loading.end()

    def _switch_collection(self, index: int) -> bool:
        project, context = self.project, self.context
        resources = intervals = None
        try:
            def open_files():
                opened = project.open_collection(index)
                try:
                    found = None
                    if context.navigator is not None:
                        spec = next(iter(project.segmentation_specs.values()))
                        found = opened.intervals(spec["from"])
                    return opened, found
                except BaseException:
                    opened.close()
                    raise

            resources, intervals = run_in_background(open_files)         # the bar keeps moving while the files are read
        except Exception as exc:
            if resources is not None:
                resources.close()
            self.statusBar().showMessage(f"Could not open {project.collections[index].title}: {exc}", 10000)
            return False
        self.loading.progress("Closing the previous session…")
        self._remember_collection()
        context.bus.publish(SetPlaying(False))
        for view in list(self.views):
            self.remove_view(view, track=False, refresh=False)
        previous = context.resources
        project.activate(index, resources)
        context.resources, context.collection = resources, project.collection
        previous.close()
        context.notes.clear()
        if intervals is not None:
            context.navigator.replace_intervals(intervals)
            self.filter_bar.repopulate()
        self._sync_views(Workspace(added=list(self._added.values()), removed=list(self._removed)), self.loading.progress)
        self.loading.progress("Arranging the window…")
        self._apply_lags(dict(self._lags))
        self._apply_view_settings({t: dict(v) for t, v in self._view_settings.items()})
        self._views_changed()
        self._restore_collection()
        self._set_title()
        self.sync.load_cached()
        if self.collection_bar is not None:
            self.collection_bar.set_active(index)
        return True

    def switch_workspace(self, name: str) -> bool:
        """Open a saved workspace. Changes to the one in use that were not saved are dropped."""
        workspace = load_workspace(self.workspace_dir, name) if self.workspace_dir is not None else None
        if workspace is None:
            return False
        self.workspace_name = name
        self._set_title()
        self.apply_workspace(workspace)
        return True

    def save_workspace_as(self, name: str) -> bool:
        """Save the current arrangement under a new name and carry on in it (an existing name is overwritten)."""
        name = name.strip()
        if not name or self.workspace_dir is None:
            return False
        self.workspace_name = name
        self._set_title()
        self.save_workspace_clicked()
        return True

    def delete_workspace(self, name: str) -> bool:
        """Delete a saved workspace. If it is the one in use, the window keeps its arrangement but is
        no longer attached to a saved file (saving writes it again)."""
        if self.workspace_dir is None or name not in self.saved_workspace_names():
            return False
        delete_workspace(self.workspace_dir, name)
        self.statusBar().showMessage(f"Deleted workspace '{name}'", 4000)
        return True

    def reset_workspace(self) -> None:
        """Put the window back to the project's own views and the default arrangement. This changes
        only what is on screen; it is saved if and when the user saves."""
        self.apply_workspace(Workspace())
        self.statusBar().showMessage("Showing the project's defaults (save to keep them as this workspace)", 6000)

    def open_sync_diagnostics(self) -> None:
        """Show the synchronization diagnostics window (it stays open beside the main one)."""
        if self._sync_window is None:
            self._sync_window = SyncDiagnosticsWindow(self)
        self._sync_window.show()
        self._sync_window.raise_()
        self._sync_window.activateWindow()

    def _fill_workspace_menu(self) -> None:
        from PySide6.QtGui import QAction, QActionGroup

        menu = self.workspace_menu
        menu.clear()
        enabled = self.workspace_dir is not None
        saved = self.saved_workspace_names()
        group = QActionGroup(menu)
        for name in dict.fromkeys(saved + ([self.workspace_name] if enabled else [])):
            action = QAction(name if name in saved else f"{name} (not saved yet)", menu)
            action.setCheckable(True)
            action.setChecked(name == self.workspace_name)
            action.setEnabled(enabled and name in saved)
            action.triggered.connect(lambda _c=False, n=name: self.switch_workspace(n))
            group.addAction(action)
            menu.addAction(action)
        menu.addSeparator()
        save = menu.addAction(f"Save workspace '{self.workspace_name}'", self.save_workspace_clicked)
        save.setShortcut(QKeySequence.StandardKey.Save)
        save.setEnabled(enabled)
        as_new = menu.addAction("Save workspace as…", self._ask_save_workspace_as)
        as_new.setEnabled(enabled)
        delete = menu.addAction(f"Delete workspace '{self.workspace_name}'", lambda: self.delete_workspace(self.workspace_name))
        delete.setEnabled(enabled and self.workspace_name in saved)
        menu.addAction("Reset to the project's defaults", self.reset_workspace)

    def _ask_save_workspace_as(self) -> None:
        from PySide6.QtWidgets import QInputDialog

        name, ok = QInputDialog.getText(self, "Save workspace as", "Name for this arrangement of views and panels:")
        if ok:
            self.save_workspace_as(name)

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

    def add_view(self, spec: dict, track: bool = True, refresh: bool = True) -> View | None:
        """Create a view from a spec and show it. Returns None (with a note in the project panel) if
        it could not be created."""
        spec = {**spec, "title": unique_title(self.context, spec.get("title") or spec["type"])}
        view = create_view(self.context, spec)
        if view is None:
            if refresh:
                self._views_changed()
            return None
        self.views.append(view)
        register_view(self.context, view, self._colors_used)
        self._colors_used += 1
        self.docks.append(self._make_dock(view, spec.get("area", "right")))
        self.set_view_lag(view, self._lags.get(view.title, float(spec.get("lag_ms", 0.0))))
        for key, value in self._view_settings.get(view.title, {}).items():
            view.apply_setting(key, value)
        if track:
            self._added[view.title] = spec
        if refresh:
            self._views_changed()
        return view

    def remove_view(self, view: View, track: bool = True, refresh: bool = True) -> None:
        if view not in self.views:
            return
        i = self.views.index(view)
        dock = self.docks.pop(i)
        self.views.pop(i)
        self.view_host.removeDockWidget(dock)
        dock.deleteLater()
        view.close_view()
        unregister_view(self.context, view)
        if track and self._added.pop(view.title, None) is None and view.title not in self._removed:
            self._removed.append(view.title)               # one of the project's own views
        if refresh:
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
        if self._sync_window is not None:
            self._sync_window.close()
        self.context.resources.close()
        super().closeEvent(event)
