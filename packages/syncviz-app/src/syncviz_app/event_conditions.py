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

from syncviz.conditions import Condition, condition_mask, conditions_mask
from syncviz.epochs import ANCHORS
from syncviz.inspection import Target
from syncviz_app.project import split_ref


class EventConditions:
    def __init__(self, context, groups: dict[str, dict[str, dict]] | None = None, defaults: dict | None = None) -> None:
        self.context = context
        self.groups = groups or {}                          # scope -> event name -> {from, member?}
        self.defaults = dict(defaults or {})                # the project's `clip:` (before_ms, after_ms, anchor)
        self.clip_overrides: dict[str, dict] = {}           # per event, set by the user
        self.user_segmentations: dict[str, dict] = {}       # windows the user made from events: name -> segmentation spec
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

    def find_in(self, resources, name: str):
        """The data behind an event name in the recording `resources` holds."""
        spec = self.spec_of(name)
        return resources.events_or_intervals(spec["from"], spec.get("member"))

    def find(self, name: str):
        """The data behind an event name in the open recording."""
        return self.find_in(self.context.resources, name)

    # -- the window cut around an event ----------------------------------------------------------
    def clip(self, name: str) -> dict:
        """`{before_ms, after_ms, anchor}` for an event: what the user set, else the event's own entry in the project, else the
        project's `clip:` default, else 500 ms either side of the whole event."""
        base = {"before_ms": 500.0, "after_ms": 500.0, "anchor": "span"}
        base.update({k: v for k, v in self.defaults.items() if k in base})
        spec = self.spec_of(name)
        if "clip_ms" in spec:
            base["before_ms"], base["after_ms"] = (float(v) for v in spec["clip_ms"])
        if "anchor" in spec:
            base["anchor"] = spec["anchor"]
        base.update(self.clip_overrides.get(name, {}))
        return base

    def set_clip(self, name: str, before_ms: float, after_ms: float, anchor: str) -> None:
        if anchor not in ANCHORS:
            raise ValueError(f"anchor must be one of {ANCHORS}")
        self.clip_overrides[name] = {"before_ms": max(float(before_ms), 0.0), "after_ms": max(float(after_ms), 0.0),
                                     "anchor": anchor}
        self._notify()

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
            self.message = "No segment would be left, so that condition was not applied. " + self._why(items, before)
            self._notify()
            return False
        self.message = ""
        self._notify()
        return True

    def _why(self, items: list[Condition], before: list[Condition]) -> str:
        """A hint about the condition that was just tried: how many segments it matches on its own, and whether its window is
        what rules them out."""
        nav = self.context.navigator
        tried = next((c for c in items if c not in before), None)
        if tried is None or nav is None:
            return ""
        total = len(nav.intervals)
        try:
            alone = int(condition_mask(nav.intervals, tried, self.find).sum())
            hint = f"On its own it matches {alone} of {total}."
            if tried.window_ms is not None:
                free = Condition(tried.events, tried.answer, None, tried.edge)
                anywhere = int(condition_mask(nav.intervals, free, self.find).sum())
                hint += (f" Without its window ({tried.window_ms[0]:g} to {tried.window_ms[1]:g} ms from the start of each "
                         f"segment) it would match {anywhere}.")
            else:
                hint += " The other conditions and filters rule out the rest."
            return hint
        except Exception:                                   # the data behind it is missing in this recording
            return ""

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
        return {"conditions": [c.to_dict() for c in self.items], "clips": {k: dict(v) for k, v in self.clip_overrides.items()},
                "segmentations": {k: dict(v) for k, v in self.user_segmentations.items()}}

    def apply_state(self, state: dict) -> None:
        self.clip_overrides = {str(k): dict(v) for k, v in state.get("clips", {}).items() if k in self.names()}
        self.user_segmentations = {str(k): dict(v) for k, v in state.get("segmentations", {}).items()}
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
