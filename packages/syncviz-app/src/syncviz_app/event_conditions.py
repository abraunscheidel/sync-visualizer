"""The event conditions in force, and the events the project lets the user choose from (design doc 28.10).

    events:                                  # in the project file: the events a condition can be about, by scope
      Contacts:
        Whisker C0 touch: {from: "session:processing/behavior/contacts_by_whisker_C0"}
      Licks and rewards:
        Lick left: {from: "session:processing/behavior/licks", member: left}

The user adds conditions as they need them; none are in force to begin with. This is one shared piece of application state, so
it lives in a core panel (`events_panel.py`), not in a view.
"""

from __future__ import annotations

from syncviz.conditions import Condition, conditions_mask
from syncviz.inspection import Target
from syncviz_app.project import split_ref


class EventConditions:
    def __init__(self, context, groups: dict[str, dict[str, dict]] | None = None) -> None:
        self.context = context
        self.groups = groups or {}                          # scope -> event name -> {from, member?}
        self.items: list[Condition] = []
        self.message = ""                                   # why the last change was refused, for the panel to show
        self._observers: list = []

    # -- the events on offer ---------------------------------------------------------------
    def spec_of(self, name: str) -> dict:
        for events in self.groups.values():
            if name in events:
                return events[name]
        raise KeyError(f"no event named {name!r}")

    def names(self) -> list[str]:
        return [name for events in self.groups.values() for name in events]

    def find(self, name: str):
        """The data behind an event name in the open recording."""
        spec = self.spec_of(name)
        return self.context.resources.events_or_intervals(spec["from"], spec.get("member"))

    def name_of(self, target: Target) -> str | None:
        """The project's name for the event `target` points at, if it names it."""
        for events in self.groups.values():
            for name, spec in events.items():
                try:
                    source, path = split_ref(spec["from"])
                except ValueError:
                    continue
                if (source, path) == (target.source, target.path) and spec.get("member") == target.member:
                    return name
        return None

    # -- the conditions --------------------------------------------------------------------
    def subscribe(self, observer) -> None:
        self._observers.append(observer)

    def _notify(self) -> None:
        for observer in list(self._observers):
            try:
                observer()
            except RuntimeError:                            # its widget has been deleted
                self._observers.remove(observer)

    def apply(self) -> bool:
        """Restrict the navigated segments to those that satisfy every condition. Returns False, leaving things as they were,
        if that would leave none."""
        nav = self.context.navigator
        if nav is None:
            return True
        mask, notes = conditions_mask(nav.intervals, self.items, self.find)
        self.context.notes.extend(n for n in notes if n not in self.context.notes)
        return nav.set_mask(mask)

    def _change(self, items: list[Condition]) -> bool:
        before = self.items
        self.items = items
        if not self.apply():
            self.items = before
            self.message = "No segment would be left, so that condition was not applied."
            self._notify()
            return False
        self.message = ""
        self._notify()
        return True

    def add(self, condition: Condition) -> bool:
        return self._change(self.items + [condition])

    def replace(self, index: int, condition: Condition) -> bool:
        return self._change(self.items[:index] + [condition] + self.items[index + 1:])

    def remove(self, index: int) -> bool:
        return self._change(self.items[:index] + self.items[index + 1:])

    def clear(self) -> bool:
        return self._change([])

    def reapply(self) -> None:
        """The segments changed (another recording, another segmentation): the conditions apply to the new ones. A condition
        that would leave nothing is dropped, with a note, rather than leaving the user with nothing to look at."""
        if not self.items:
            self._notify()
            return
        if not self.apply():
            self.context.notes.append("event conditions dropped: no segment of this recording satisfies them")
            self.items = []
        self._notify()

    # -- what a workspace saves --------------------------------------------------------------
    def state(self) -> dict:
        return {"conditions": [c.to_dict() for c in self.items]}

    def apply_state(self, state: dict) -> None:
        items = []
        for data in state.get("conditions", []):
            try:
                condition = Condition.from_dict(data)
            except (KeyError, TypeError, ValueError):
                continue
            if all(name in self.names() for name in condition.events):
                items.append(condition)
        self.items = items
        self.reapply()
