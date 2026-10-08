"""Actions on what a view points at (design doc section 28.7).

An action is a named operation on a `Target`: select it, seek to its time, open it as a view, copy its details. They
live in a registry of their own and know nothing about menus. The context menu is one way to trigger them; a click
binding (`interaction:` in the project file), a keyboard shortcut or a button are others. Views and plugins add actions
by returning them from `View.target_actions` or by registering them here.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtGui import QAction, QGuiApplication
from PySide6.QtWidgets import QMenu

from syncviz.core import Seek
from syncviz.inspection import Target

DEFAULT_BINDINGS = {"click": "select", "double_click": "seek"}


@dataclass
class TargetAction:
    id: str
    label: str
    run: Callable[[Target, object], None] | None = None          # (target, the view it was pointed at in, if any)
    applies: Callable[[Target], bool] = lambda target: True
    shortcut: str = ""                                            # shown in the menu; bound to the selection by the window
    children: Callable[[Target], list["TargetAction"]] | None = None   # makes this a submenu of other actions
    description: str = ""


class ActionRegistry:
    """Every action available on targets, and the gestures bound to them."""

    def __init__(self, context, bindings: dict | None = None, keys: dict | None = None) -> None:
        self.context = context
        self.bindings = {**DEFAULT_BINDINGS, **{str(k): str(v) for k, v in (bindings or {}).items()}}
        self._actions: dict[str, TargetAction] = {}
        self._providers: list[Callable[[], list[TargetAction]]] = []
        self._install_builtins(keys or {})

    # -- registering -----------------------------------------------------------------------
    def register(self, action: TargetAction) -> None:
        self._actions[action.id] = action

    def add_provider(self, provider: Callable[[], list[TargetAction]]) -> None:
        """Actions that come and go, such as those of whichever views are open."""
        self._providers.append(provider)

    def all(self) -> list[TargetAction]:
        out = list(self._actions.values())
        for provider in self._providers:
            out += provider()
        return out

    def get(self, action_id: str) -> TargetAction | None:
        return next((a for a in self.all() if a.id == action_id), None)

    # -- using them ------------------------------------------------------------------------
    def for_target(self, target: Target) -> list[TargetAction]:
        """The actions that apply to `target`, in the order registered (a submenu only if it has anything in it)."""
        out = []
        for action in self.all():
            if not action.applies(target):
                continue
            if action.children is not None and not action.children(target):
                continue
            out.append(action)
        return out

    def run(self, action_id: str, target: Target | None, origin=None) -> bool:
        """Run one action on a target if it applies. Returns whether it ran."""
        action = self.get(action_id)
        if action is None or action.run is None or target is None or not action.applies(target):
            return False
        action.run(target, origin)
        return True

    def trigger(self, gesture: str, target: Target | None, origin=None) -> bool:
        """Run the action the project binds to a gesture ("click", "double_click")."""
        action_id = self.bindings.get(gesture)
        return bool(action_id) and self.run(action_id, target, origin)

    # -- the actions every application has -----------------------------------------------
    def _install_builtins(self, keys: dict) -> None:
        context = self.context

        def seek(target: Target, origin) -> None:
            moment = target.time if target.time is not None else target.at
            lag = getattr(origin, "lag", 0.0)                    # the view shows `lag` behind the playhead
            if moment is not None and context.timeline.allows(moment + lag):
                context.bus.publish(Seek(moment + lag))

        def copy_details(target: Target, _origin) -> None:
            QGuiApplication.clipboard().setText(context.inspector.full_text(target))

        self.register(TargetAction("select", "Select", lambda t, o: context.selection.set(t),
                                   description="Make this the selected item; its details show in the Details panel"))
        self.register(TargetAction("seek", "Go to this time", seek,
                                   applies=lambda t: t.time is not None or t.at is not None,
                                   description="Move the playhead to this moment"))
        self.register(TargetAction("copy_details", "Copy details", copy_details,
                                   description="Copy the description and every figure as text"))
        self.register(TargetAction("clear_selection", "Clear selection", lambda t, o: context.selection.clear(),
                                   applies=lambda t: context.selection.is_selected(t),
                                   shortcut=keys.get("clear_selection", "")))


def build_menu(actions: list[TargetAction], target: Target, origin, parent=None) -> QMenu:
    """A context menu of `actions` for `target`. Submenus come from actions that have children."""
    menu = QMenu(parent)
    _fill(menu, actions, target, origin)
    return menu


def _fill(menu: QMenu, actions: list[TargetAction], target: Target, origin) -> None:
    for action in actions:
        if action.children is not None:
            _fill(menu.addMenu(action.label), action.children(target), target, origin)
            continue
        text = f"{action.label}\t{action.shortcut}" if action.shortcut else action.label
        entry = QAction(text, menu)
        if action.description:
            entry.setToolTip(action.description)
        entry.triggered.connect(lambda _checked=False, a=action: a.run(target, origin))
        menu.addAction(entry)
