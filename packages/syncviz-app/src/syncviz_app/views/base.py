"""Base class for views: the panels a user can arrange in the window.

A view reads generic resources and draws them. It never talks to another view:
user gestures become actions on the bus, and the view redraws when told the
playhead has moved.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtWidgets import QToolTip, QWidget

from dataclasses import dataclass

from syncviz.inspection import Target
from syncviz.sources import DataEntry
from syncviz_app.context import AppContext
from syncviz_app.commands import build_menu


def describe_delay(milliseconds: float, sentence: bool = False) -> str:
    """A view's display delay in words, so nobody has to remember which way a sign points.
    Positive means delayed (the view runs behind the playhead), negative means ahead of it."""
    if not milliseconds:
        return "No delay" if sentence else ""
    amount = f"{abs(milliseconds):g} ms"
    if sentence:
        return f"This view runs {amount} " + ("behind the playhead." if milliseconds > 0 else "ahead of the playhead.")
    return f"delayed {amount}" if milliseconds > 0 else f"ahead {amount}"


@dataclass
class ViewSetting:
    """One setting a view offers the user, shown under the Views list when the view is selected.

    `kind` is "choice" (one of `choices`, each a `(label, value)`) or "toggle" (on or off). `value` is the current value.
    The view applies a new one in `apply_setting` and returns to its project defaults in `reset_settings`; the window keeps
    the user's choices in the workspace, by view title.
    """

    key: str
    label: str
    kind: str
    value: object
    choices: list[tuple[str, object]] | None = None
    description: str = ""                           # what the setting is and how to read it, shown as a tooltip
    group: str | None = None            # toggles that share a group are shown together under one switch for the whole group


@dataclass
class Candidate:
    """A view the user could add: what to call it in the dialog, and the spec that creates it."""

    label: str
    spec: dict
    description: str = ""                       # what the data is, shown as a tooltip


class View(QWidget):
    type_name = ""
    display_name = ""              # what the "add a view" dialog calls this kind of view
    default_refresh_hz = 30.0      # redraws per second while the playhead moves; see refresh.py

    def __init__(self, context: AppContext, spec: dict) -> None:
        super().__init__()
        self.context = context
        self.spec = spec
        self.title: str = spec.get("title") or self.type_name
        # Upper limit on how often this view redraws. A project can override it per view.
        # Display delay in seconds (`lag`): positive means delayed, so the view shows what the playhead showed `lag` ago;
        # negative means ahead. See describe_delay.
        # It changes only what this view draws, never the data or the timeline.
        self.lag: float = 0.0
        self.temporary: bool = bool(spec.get("temporary", False))    # not part of the workspace until the user keeps it
        self.refresh_hz: float = float(spec.get("refresh_hz", self.default_refresh_hz))
        context.selection.subscribe(lambda _target: self.selection_changed())

    def selection_changed(self) -> None:
        """The shared selection changed; a view that can show which of its items is selected redraws that."""

    def selectable_targets(self) -> list[Target]:
        """The items this view shows, in the order it lists them, so a Shift-click can select the run between two. Views that show
        several items override this."""
        return []

    def click_at(self, target: Target, modifiers=None, double: bool = False) -> None:
        """A click on `target` in this view: Ctrl adds or removes it from the selection, Shift selects the run from the last one
        clicked, and a plain click (or double click) runs the command the project binds to it (select, and so on)."""
        selection = self.context.selection
        if not double and modifiers is not None:
            if modifiers & Qt.KeyboardModifier.ControlModifier:
                selection.toggle(target)
                return
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                selection.extend(target, self.selectable_targets())
                return
        self.context.commands.trigger("double_click" if double else "click", target, self)

    def select_at(self, pos: QPoint) -> bool:
        """Select whatever is under `pos` (this view's coordinates). Returns whether there was something. Selecting never
        moves time or playback (design doc 28.7)."""
        target = self.target_at(pos)
        if target is None:
            return False
        self.context.selection.set(target)
        return True

    def is_selected(self, target: Target | None) -> bool:
        return self.context.selection.is_selected(target)

    def settings(self) -> list[ViewSetting]:
        """The settings this view offers (none by default)."""
        return []

    def apply_setting(self, key: str, value) -> None:
        """Change one of the settings listed by `settings`."""

    def reset_settings(self) -> None:
        """Return every setting to what the project file gives (or the view's own default)."""

    @classmethod
    def candidates(cls, catalog: dict[str, list[DataEntry]]) -> list[Candidate]:
        """The views of this type that the available data (by source name) could feed. Types that
        return nothing can only be added through the project file."""
        return []

    def target_at(self, pos: QPoint) -> Target | None:
        """What is under `pos` (in this view's own coordinates), or None. A view only says what it points at; the facts
        about it come from the inspector (design doc 28.7). Views that show data override this."""
        return None

    def enable_hover(self, *widgets: QWidget) -> None:
        """Show the inspector's tooltip, and the context menu, for what is under the pointer in these child widgets."""
        for widget in widgets:
            widget.installEventFilter(self)

    def commands(self) -> list:
        """Actions this view adds for the items it shows (`Command`s), beside the ones every item gets."""
        return []

    @classmethod
    def spec_for(cls, target: Target) -> dict | None:
        """The spec of a view of this type that would show `target`, or None if this type cannot show it. This is
        what lets "Open as view" offer every way a target can be visualized."""
        return None

    def show_menu(self, pos: QPoint, global_pos) -> None:
        """The context menu: the actions that apply to what is under `pos`."""
        registry = self.context.commands
        target = self.target_at(pos) if registry is not None else None
        if target is None:
            return
        selection = self.context.selection
        if selection.is_selected(target) and len(selection.targets) > 1:      # on a selected item: act on the whole selection
            actions = registry.for_targets(selection.targets, self)
            if actions:
                build_menu(actions, list(selection.targets), self, self).exec(global_pos)
            return
        if not selection.is_selected(target):                                  # on something else: that becomes the selection
            selection.set(target)
        actions = registry.for_target(target, self)
        if actions:
            build_menu(actions, target, self, self).exec(global_pos)

    def hover_text(self, pos: QPoint) -> str:
        inspector = self.context.inspector
        target = self.target_at(pos) if inspector is not None else None
        return "" if target is None else inspector.hover_text(target)

    def eventFilter(self, obj, event) -> bool:
        if event.type() == QEvent.Type.ContextMenu:
            self.show_menu(self.mapFromGlobal(event.globalPos()), event.globalPos())
            return True
        if event.type() == QEvent.Type.ToolTip:
            text = self.hover_text(self.mapFromGlobal(event.globalPos()))
            if text:
                QToolTip.showText(event.globalPos(), text, obj)
            else:
                QToolTip.hideText()
            return True
        return super().eventFilter(obj, event)

    def extent(self) -> tuple[float, float] | None:
        """Range of shared time this view has data for, or None if it has no time extent."""
        return None

    def time_base(self):
        """The grid of ticks this view's data naturally has (video frames, signal samples), as
        a `syncviz.core.TimeBase`, or None if it has no such grid. Offered to the user as a
        choice of what one "step" means."""
        return None

    def coverage(self) -> list[tuple[float, float]]:
        """Runs of shared time in which this view has data. Defaults to its whole extent;
        views whose data has real dropouts report them so the timeline can show the gaps."""
        extent = self.extent()
        return [] if extent is None else [extent]

    def stalled_for(self, now: float) -> float:
        """Seconds this view has been waiting, with no progress, for what it needs to show the
        current playhead position (0 if it is up to date or can answer immediately). Slow views
        such as a video decoding a distant frame override this; see `stall.py`."""
        return 0.0

    def refresh(self, time: float) -> None:
        """Redraw for the playhead at `time` (shared time). Only called while visible."""
        raise NotImplementedError

    def close_view(self) -> None:
        """Release resources (threads, files). Called when the window closes."""
