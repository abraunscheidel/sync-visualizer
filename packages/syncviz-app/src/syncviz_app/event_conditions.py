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
from syncviz_app.group_store import SCOPE as GROUPS_SCOPE
from syncviz_app.project import split_ref


class EventConditions:
    def __init__(self, context, groups: dict[str, dict[str, dict]] | None = None, defaults: dict | None = None,
                 track: list[str] | None = None, group_store=None) -> None:
        self.context = context
        self.group_store = group_store                      # the saved and project groups, which are events too (28.16)
        self.project_events = groups or {}                  # scope -> event name -> {from, member?}
        self.defaults = dict(defaults or {})                # the project's `clip:` (before_ms, after_ms, anchor)
        self.clip_overrides: dict[str, dict] = {}           # per event, set by the user
        self.track_default = [n for n in (track or []) if n in self.names()]   # the project's own list of events to track
        self.tracked: list[str] = list(self.track_default)  # the events the tracker shows, chosen by the viewer
        self.base = None              # set by the window: () -> (intervals, label, plural, number attribute, confine) of the segmentation in use
        self.filters_reloaded = None  # set by the window: (criteria) -> bring the attribute filters up to date after the segments changed
        self._epochs: tuple | None = None                   # (signature, clips) kept so the same clips are not made twice
        self.items: list[Condition] = []
        self.message = ""                                   # why the last change was refused, for the panel to show
        self._observers: list = []
        self._reason = ""

    # -- the events on offer ---------------------------------------------------------------
    @property
    def groups(self) -> dict[str, dict[str, dict]]:
        """Scope -> event name -> where its data is: the project's own events, and under "Groups" each group (`{group: name}`)."""
        out = dict(self.project_events)
        if self.group_store is not None and self.group_store.names():
            out[GROUPS_SCOPE] = {name: {"group": name} for name in self.group_store.names()}
        return out

    @groups.setter
    def groups(self, value) -> None:
        self.project_events = value

    def groups_changed(self) -> None:
        """A group was made or removed: anything that named one that is gone is dropped, and the lists redraw."""
        names = set(self.names())
        self.tracked = [n for n in self.tracked if n in names]
        kept = [c for c in self.items if all(e in names for e in c.events)]
        if len(kept) != len(self.items):
            self.items = kept
            self.apply()
        self._notify()

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
        if "group" in spec:
            return self.group_store.merged(resources, spec["group"])
        return resources.events_or_intervals(spec["from"], spec.get("member"))

    def warm_in(self, resources) -> None:
        """Load, ahead of need, what the project's named events stand for in the recording `resources` holds: its catalogs, each
        event's data and what kind of thing it is. Done when a session opens (off the interface thread when switching), so the
        first filter, tile or hover is not the one that waits. An event this recording lacks is skipped."""
        resources.warm()
        for name in self.names():
            try:
                self.find_in(resources, name)
                if "from" in self.spec_of(name):
                    resources.kind_of(self.spec_of(name)["from"])
            except Exception:
                pass

    def warm(self) -> None:
        self.warm_in(self.context.resources)

    def find(self, name: str):
        """The data behind an event name in the open recording."""
        return self.find_in(self.context.resources, name)

    def target_of(self, name: str) -> Target:
        """The target an event name stands for (what a tile points at), whatever the open recording holds."""
        spec = self.spec_of(name)
        if "group" in spec:
            return Target("", name, "group", None, name)    # a group is not at one place in a file
        source, path = split_ref(spec["from"])
        try:
            kind = self.context.resources.kind_of(spec["from"]) or "events"
        except Exception:                                   # the source is not in this recording
            kind = "events"
        return Target(source, path, kind, spec.get("member"), name)

    # -- the events the tracker shows ----------------------------------------------------------------
    def is_tracked(self, name: str) -> bool:
        return name in self.tracked

    def track(self, *names: str) -> None:
        added = [n for n in names if n in self.names() and n not in self.tracked]
        if added:
            self.tracked += added
            self._notify()

    def untrack(self, *names: str) -> None:
        kept = [n for n in self.tracked if n not in names]
        if len(kept) != len(self.tracked):
            self.tracked = kept
            self._notify()

    def toggle_tracking(self, name: str) -> None:
        (self.untrack if self.is_tracked(name) else self.track)(name)

    def filter_state(self, name: str) -> tuple[str, bool] | None:
        """How the conditions use an event, for its tile: ("yes" | "no" | "clips", whether that condition is on), or None if no
        condition mentions it. A condition that is on wins over one that is off, and clips over the rest."""
        found = [c for c in self.items if name in c.events]
        if not found:
            return None
        on = [c for c in found if c.enabled] or found
        pick = next((c for c in on if c.mode == "clip"), on[0])
        return ("clips" if pick.mode == "clip" else "yes" if pick.answer else "no"), pick.enabled

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
        if target.kind == "group":
            return target.path if target.path in self.names() else None
        for events in self.groups.values():
            for name, spec in events.items():
                if "from" not in spec:
                    continue
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

    def add_many(self, conditions: list[Condition]) -> bool:
        """Add several conditions as one change: all of them, or none if together they would leave nothing."""
        return self._change(self.items + list(conditions))

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
        return {"conditions": [c.to_dict() for c in self.items], "clips": {k: dict(v) for k, v in self.clip_overrides.items()},
                "tracked": list(self.tracked)}

    def apply_state(self, state: dict) -> None:
        self.clip_overrides = {str(k): dict(v) for k, v in state.get("clips", {}).items() if k in self.names()}
        self.tracked = ([str(n) for n in state["tracked"] if n in self.names()] if "tracked" in state
                        else list(self.track_default))
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
