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

from dataclasses import replace

from syncviz.conditions import Condition, condition_mask, conditions_mask
from syncviz.epochs import ANCHORS, EpochSource, epochs_from_sources
from syncviz.resources import EventSeries
from syncviz.inspection import Target
from syncviz_app.project import split_ref


class EventConditions:
    def __init__(self, context, groups: dict[str, dict[str, dict]] | None = None, defaults: dict | None = None) -> None:
        self.context = context
        self.groups = groups or {}                          # scope -> event name -> {from, member?}
        self.defaults = dict(defaults or {})                # the project's `clip:` (before_ms, after_ms, anchor)
        self.clip_overrides: dict[str, dict] = {}           # per event, set by the user
        self.base = None              # set by the window: () -> (intervals, label, plural, number attribute, confine) of the segmentation in use
        self.filters_reloaded = None  # set by the window: (criteria) -> bring the attribute filters up to date after the segments changed
        self._epochs: tuple | None = None                   # (signature, clips) kept so the same clips are not made twice
        self.items: list[Condition] = []
        self.message = ""                                   # why the last change was refused, for the panel to show
        self._observers: list = []
        self._reason = ""

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
        if any(c.enabled and c.mode == "clip" and name in c.events for c in self.items):
            self.apply()                                    # the clips are cut again with the new window
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

    def _clips(self, base, names: list[str], notes: list[str]):
        """The windows cut around the events called `names`, each with its own clip, inside the segments `base`; None if there
        are none in this recording (with a note saying why)."""
        sources, used = [], []
        for name in names:
            try:
                data = self.find(name)
            except Exception as exc:                        # this recording lacks the event
                notes.append(f"clips around '{name}' skipped: {exc}")
                continue
            clip = self.clip(name)
            before, after = clip["before_ms"] / 1000.0, clip["after_ms"] / 1000.0
            if isinstance(data, EventSeries):
                sources.append(EpochSource(data.times, None, before, after))
            else:
                sources.append(EpochSource(data.starts, data.stops, before, after, clip["anchor"]))
            used.append((name, before, after, clip["anchor"]))
        if not sources:
            return None
        signature = (id(base), tuple(used))
        if self._epochs is None or self._epochs[0] != signature:
            clips = epochs_from_sources(sources, base, True, "Events", self.base_label(), "clips")
            self._epochs = (signature, clips)
        return self._epochs[1]

    def base_plural(self) -> str:
        return self.base()[2] if self.base is not None else "Segments"

    def base_label(self) -> str:
        return self.base()[1] if self.base is not None else "Segment"

    def apply(self) -> bool:
        """Make the navigated segments what the conditions ask for: the segmentation in use, or the clips around the events of the
        clip conditions that are on, kept to those that satisfy the other conditions that are on. Returns False, leaving things as
        they were, if nothing would be left."""
        nav = self.context.navigator
        self._reason = ""
        if nav is None or self.base is None:
            return True
        base, label, plural, number, confine = self.base()
        notes: list[str] = []
        names = [n for c in self.items if c.enabled and c.mode == "clip" for n in c.events]
        target, t_label, t_plural, t_number, t_confine = base, label, plural, number, confine
        if names:
            clips = self._clips(base, names, notes)
            if clips is not None and len(clips):
                target, t_number, t_confine = clips, None, True
                t_label = f"{names[0]} clip" if len(set(names)) == 1 else "Clip"
                t_plural = f"{names[0]} clips" if len(set(names)) == 1 else "Clips"
            elif clips is not None:
                self._reason = "None of those events happen inside the segments, so there are no clips."
                return False
        mask, mask_notes = conditions_mask(target, self.items, self.find)
        self.context.notes.extend(n for n in notes + mask_notes if n not in self.context.notes)
        if mask is not None and not mask.any():
            return False
        if target is not nav.intervals:
            criteria = dict(nav._criteria)                  # the attribute filters the user had set
            nav.replace_segments(target, t_label, t_plural, t_number, t_confine)
            ok = nav.set_mask(mask)
            if self.filters_reloaded is not None:
                self.filters_reloaded(criteria)
            return ok
        return nav.set_mask(mask)

    def _change(self, items: list[Condition]) -> bool:
        before = self.items
        self.items = items
        if not self.apply():
            self.items = before
            self.message = self._reason or ("No segment would be left, so that condition was not applied. "
                                            + self._why(items, before))
            self._notify()
            return False
        self.message = ""
        self._notify()
        return True

    def _why(self, items: list[Condition], before: list[Condition]) -> str:
        """A hint about the condition that was just tried: how many segments it matches on its own."""
        nav = self.context.navigator
        tried = next((c for c in items if c not in before), None)
        if tried is None or nav is None:
            return ""
        total = len(nav.intervals)
        try:
            alone = int(condition_mask(nav.intervals, tried, self.find).sum())
            return f"On its own it matches {alone} of {total}; the other conditions and filters rule out the rest."
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

    def set_enabled(self, index: int, enabled: bool) -> bool:
        """Switch a condition on or off without losing it."""
        return self.replace(index, replace(self.items[index], enabled=bool(enabled)))

    def set_mode(self, index: int, mode: str) -> bool:
        """Make a condition keep the segments where its events happened, or just the clips around them."""
        return self.replace(index, replace(self.items[index], mode=mode))

    def reapply(self) -> None:
        """The segments changed (another recording, another segmentation): the conditions apply to the new ones. A condition
        that would leave nothing is dropped, with a note, rather than leaving the user with nothing to look at."""
        if not self.items:
            self.apply()                                    # back to the segmentation itself if clips were showing
            self._notify()
            return
        if not self.apply():
            self.context.notes.append("event conditions dropped: no segment of this recording satisfies them")
            self.items = []
            self.apply()
        self._notify()

    # -- what a workspace saves --------------------------------------------------------------
    def state(self) -> dict:
        return {"conditions": [c.to_dict() for c in self.items], "clips": {k: dict(v) for k, v in self.clip_overrides.items()}}

    def apply_state(self, state: dict) -> None:
        self.clip_overrides = {str(k): dict(v) for k, v in state.get("clips", {}).items() if k in self.names()}
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
