"""Assemble a running application from a project file."""

from __future__ import annotations

from pathlib import Path

from syncviz import plugins
from syncviz.cache import DiskCache
from syncviz.core import ActionBus, FixedStep, SegmentNavigator, Stepper, Timeline
from syncviz.core.stepping import FIXED_INTERVAL
from syncviz_app.colors import view_color
from syncviz_app.context import AppContext
from syncviz_app.main_window import MainWindow
from syncviz_app.project import load_project, split_ref
from syncviz_app.views.base import View


DEFAULT_STEP_INTERVAL_MS = 10.0


def build_window(project_path: str | Path, debug: bool = False) -> MainWindow:
    project = load_project(project_path)
    bus = ActionBus()
    timeline = Timeline(bus, 0.0, 1.0)           # real range is set once the views report theirs
    cache = DiskCache(project.root / project.config["cache"]) if "cache" in project.config else None
    context = AppContext(bus=bus, timeline=timeline, resources=project.resources, cache=cache)

    # Segment navigation (the first configured segmentation).
    for name, spec in project.segmentation_specs.items():
        intervals = project.resources.intervals(spec["from"])
        context.navigator = SegmentNavigator(
            bus, intervals, label=spec.get("label", "Segment"), index_attribute=spec.get("number_attribute"),
            label_plural=spec.get("label_plural"),
        )
        break

    views: list[View] = []
    for spec in project.view_specs:
        try:
            view_class = plugins.load("views", spec["type"])
        except KeyError as exc:
            context.notes.append(f"view {spec.get('title') or spec['type']!r} skipped: {exc.args[0]}")
            continue
        view = view_class(context, spec)
        views.append(view)
        context.colors[view.title] = view_color(len(views) - 1)
        extent = view.extent()
        if extent is not None:
            context.extents[view.title] = extent
            context.coverage[view.title] = view.coverage()

    # The timeline spans everything: no source defines its start or end.
    if context.extents:
        lows, highs = zip(*context.extents.values())
        timeline.set_range(min(lows), max(highs))

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

    return MainWindow(project, context, views, debug=debug)
