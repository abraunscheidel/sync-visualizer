"""Assemble a running application from a project file."""

from __future__ import annotations

from pathlib import Path

from syncviz.cache import DiskCache
from syncviz.core import ActionBus, FixedStep, SegmentNavigator, Stepper, Timeline
from syncviz.core.stepping import FIXED_INTERVAL
from syncviz_app.context import AppContext
from syncviz_app.workspace import DEFAULT_NAME, workspaces_dir, load_workspace
from syncviz_app.main_window import MainWindow
from syncviz_app.project import load_project
from syncviz_app.view_factory import create_view, fit_timeline, register_view
from syncviz_app.views.base import View


DEFAULT_STEP_INTERVAL_MS = 10.0


def build_window(project_path: str | Path, debug: bool = False, use_workspace: bool = True,
                 workspace_name: str | None = None, collection: str | None = None) -> MainWindow:
    """Open a project. `workspace_name` picks the workspace (else the project file's `workspace:`, else "Default");
    `use_workspace=False` ignores workspaces altogether."""
    project = load_project(project_path, collection)
    directory = workspaces_dir(project_path, project.config.get("workspaces_dir")) if use_workspace else None
    chosen = workspace_name or project.config.get("workspace") or DEFAULT_NAME
    workspace = load_workspace(directory, chosen) if directory else None
    workspace_notes: list[str] = []
    if directory and workspace is None and (workspace_name or project.config.get("workspace")):
        workspace_notes = [f"workspace {chosen!r} was not found in {directory}; showing the project's defaults"]
    bus = ActionBus()
    timeline = Timeline(bus, 0.0, 1.0)           # real range is set once the views report theirs
    cache = DiskCache(project.root / project.config["cache"]) if "cache" in project.config else None
    context = AppContext(bus=bus, timeline=timeline, resources=project.resources, cache=cache,
                         collection=project.collection, collection_label=project.collection_label)

    # Segment navigation (the first configured segmentation).
    for name, spec in project.segmentation_specs.items():
        intervals = project.resources.intervals(spec["from"])
        context.navigator = SegmentNavigator(
            bus, intervals, label=spec.get("label", "Segment"), index_attribute=spec.get("number_attribute"),
            label_plural=spec.get("label_plural"),
        )
        break

    views: list[View] = []
    specs = project.view_specs
    if workspace is not None:
        specs = [s for s in specs if (s.get("title") or s["type"]) not in workspace.removed] + workspace.added
    for spec in specs:
        view = create_view(context, spec)
        if view is None:
            continue
        views.append(view)
        register_view(context, view, len(views) - 1)

    fit_timeline(context)

    if context.navigator is not None:
        context.navigator.select(context.navigator.index)      # move the playhead to the first segment
        first_spec = next(iter(project.segmentation_specs.values()))
        context.navigator.skip_hidden = bool(first_spec.get("skip_filtered", True))
        context.navigator.follow(timeline)                     # current segment tracks the playhead from here on

    # What one "step" means. Every view with a natural grid of ticks is offered, along with a fixed
    # interval. The starting choice is the first view's grid (shown in the toolbar, where the user
    # can change it) unless the project names one:   step: {view: "Whisker video"}  or  {interval_ms: 25}
    step_spec = project.config.get("step") or {}
    interval_ms = float(step_spec.get("interval_ms", DEFAULT_STEP_INTERVAL_MS))
    bases = {view.title: view.time_base() for view in views if view.time_base() is not None}
    bases[FIXED_INTERVAL] = FixedStep(interval_ms / 1000.0)
    reference = FIXED_INTERVAL if "interval_ms" in step_spec else step_spec.get("view")
    context.stepper = Stepper(bus, timeline, bases, reference)
    if "view" in step_spec and step_spec["view"] not in bases:
        context.notes.append(f"step view {step_spec['view']!r} has no time grid; using {context.stepper.reference!r}")

    context.notes.extend(workspace_notes)
    return MainWindow(project, context, views, debug=debug, workspace=workspace, workspace_dir=directory, workspace_name=chosen,
                      state_dir=(Path(project_path).parent / "collection_state") if use_workspace else None)
