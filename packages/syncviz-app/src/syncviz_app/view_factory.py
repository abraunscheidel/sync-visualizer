"""Creating views and keeping the shared context consistent as views come and go.

The context records, per view title, where its data exists and which colour it is shown in; the
timeline spans the union of the views' extents; and the stepper offers each view's grid of ticks.
All of that changes when a view is added or removed, so it is done here, in one place, for both the
views a project declares and the ones the user adds later.
"""

from __future__ import annotations

from syncviz import plugins
from syncviz.core.stepping import FIXED_INTERVAL
from syncviz_app.colors import view_color
from syncviz_app.context import AppContext
from syncviz.sources import MissingDataError
from syncviz_app.views.base import View
from syncviz_app.views.placeholder import PlaceholderView


def create_view(context: AppContext, spec: dict) -> View | None:
    """Build the view a spec describes, or note why not and return None."""
    label = spec.get("title") or spec.get("type")
    try:
        view_class = plugins.load("views", spec["type"])
    except KeyError as exc:
        context.notes.append(f"view {label!r} skipped: {exc.args[0]}")
        return None
    try:
        return view_class(context, spec)
    except MissingDataError as exc:                # this collection lacks the data: keep the panel, say so
        context.notes.append(f"view {label!r}: {exc}")
        return PlaceholderView(context, spec, str(exc))
    except Exception as exc:                       # bad data for a view must not take the app down
        context.notes.append(f"view {label!r} could not be created: {exc}")
        return None


def unique_title(context: AppContext, title: str) -> str:
    """`title`, or `title (2)` and so on if a view already has it (titles key the colours and rows)."""
    taken = set(context.colors)
    candidate, n = title, 2
    while candidate in taken:
        candidate, n = f"{title} ({n})", n + 1
    return candidate


def register_view(context: AppContext, view: View, color_index: int) -> None:
    context.colors[view.title] = view_color(color_index)
    extent = view.extent()
    if extent is not None:
        context.extents[view.title] = extent
        context.coverage[view.title] = view.coverage()
    stepper = context.stepper
    if stepper is not None and view.time_base() is not None:
        stepper.bases[view.title] = view.time_base()


def unregister_view(context: AppContext, view: View) -> None:
    for table in (context.colors, context.extents, context.coverage):
        table.pop(view.title, None)
    stepper = context.stepper
    if stepper is not None and view.title in stepper.bases:
        del stepper.bases[view.title]
        if stepper.reference == view.title:
            stepper.reference = FIXED_INTERVAL


def fit_timeline(context: AppContext) -> None:
    """The timeline spans everything: no source defines its start or end."""
    if context.extents:
        lows, highs = zip(*context.extents.values())
        context.timeline.set_range(min(lows), max(highs))
