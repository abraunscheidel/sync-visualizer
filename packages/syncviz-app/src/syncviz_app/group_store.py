"""The groups in force: those the project file defines, and those the viewer has saved (design doc 28.16).

    groups:                                   # in the project file: shared, read-only
      Layer 4: {of: "session:units", where: {layer: "4"}}
      Deep:    {of: "session:units", where: {depth: {min: 700}}}
      Picks:   {of: "session:units", members: ["7", "12"]}

The viewer's own are kept in a file of their own beside the project (`groups/<project name>.json`), written when a group is made or
removed, because making one is the act of saving it. A group appears wherever events do: it is an event stream (a unit of the group
fired), so the Events panel, the tracker and conditions use it like any other event; and its members can be selected together.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from syncviz.groups import Group, check_names, members_of, merge_events, rule_text
from syncviz.inspection import Target
from syncviz_app.project import split_ref

GROUPS_FOLDER = "groups"
SCOPE = "Groups"                    # what the group names are listed under next to the project's own scopes of events


def groups_path(project_path: str | Path, project_name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", project_name).strip(" .") or "project"
    return Path(project_path).parent / GROUPS_FOLDER / f"{safe}.json"


class GroupStore:
    def __init__(self, project_groups: list[Group] | None = None, path: Path | None = None, taken=lambda: []) -> None:
        self.project: dict[str, Group] = {g.name: g for g in (project_groups or [])}      # from the project file: read-only
        self.saved: dict[str, Group] = {}                                                  # the viewer's, kept in `path`
        self.path = path                                                                    # None: not kept
        self.taken = taken                                                                  # the names of events: a group may not reuse one
        self.notes: list[str] = []                                                          # what went wrong reading the file
        self._observers: list = []
        self.load()

    # -- the list ------------------------------------------------------------------------------
    def all(self) -> list[Group]:
        return [*self.project.values(), *self.saved.values()]

    def names(self) -> list[str]:
        return [g.name for g in self.all()]

    def get(self, name: str) -> Group:
        if name in self.project:
            return self.project[name]
        if name in self.saved:
            return self.saved[name]
        raise KeyError(f"no group named {name!r}")

    def is_saved(self, name: str) -> bool:
        """Whether the viewer made it (and so can remove it), rather than the project file."""
        return name in self.saved

    def subscribe(self, observer) -> None:
        self._observers.append(observer)

    def _notify(self) -> None:
        for observer in list(self._observers):
            try:
                observer()
            except RuntimeError:                             # its widget has been deleted
                self._observers.remove(observer)

    # -- changing it ---------------------------------------------------------------------------------
    def add(self, group: Group) -> None:
        """Save a new group. Raises `ValueError` if the name is in use (by another group or an event)."""
        check_names([*self.all(), group], self.taken())
        self.saved[group.name] = group
        self.save()
        self._notify()

    def remove(self, name: str) -> None:
        if name not in self.saved:
            raise KeyError(f"{name!r} is not one of your saved groups" if name in self.project else f"no group named {name!r}")
        del self.saved[name]
        self.save()
        self._notify()

    # -- the file ----------------------------------------------------------------------------------------
    def load(self) -> None:
        self.saved = {}
        if self.path is None or not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for name, spec in (data.get("groups") or {}).items():
                group = Group.from_dict(name, spec)
                if group.name in self.project:
                    self.notes.append(f"saved group {name!r} ignored: the project file has one of that name")
                else:
                    self.saved[group.name] = group
        except (OSError, ValueError, KeyError, TypeError) as exc:
            self.notes.append(f"saved groups could not be read from {self.path}: {exc}")

    def save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"groups": {g.name: g.to_dict() for g in self.saved.values()}}, indent=2), encoding="utf-8")

    # -- a group in a recording ------------------------------------------------------------------------------
    @staticmethod
    def attributes_in(resources, ref: str) -> dict[str, dict]:
        """Each member of the container at `ref` with its own attributes (what a rule is asked of), in the container's order."""
        return {item: dict(series.metadata) for item, series in resources.events_of(ref).items()}

    def members(self, resources, name: str) -> list[str]:
        """The ids of the items of this recording that belong to the group (none if the recording lacks the container)."""
        group = self.get(name)
        try:
            return members_of(group, self.attributes_in(resources, group.of))
        except Exception:
            return []

    def merged(self, resources, name: str):
        """The group as one stream of events: every spike of every member. Kept per recording and per definition."""
        group = self.get(name)

        def build():
            streams = resources.events_of(group.of)                        # raises if the recording lacks the container
            ids = members_of(group, {k: dict(v.metadata) for k, v in streams.items()})
            return merge_events([streams[i] for i in ids], name=f"group/{name}", members=ids)

        return resources.cached(("group", name, json.dumps(group.to_dict(), sort_keys=True, default=str)), build)

    def series(self, resources, name: str) -> list:
        """The member event series themselves (for a processor that wants them separately)."""
        group = self.get(name)
        streams = resources.events_of(group.of)
        return [streams[i] for i in members_of(group, {k: dict(v.metadata) for k, v in streams.items()})]

    def member_targets(self, resources, name: str) -> list[Target]:
        """What to select to select the group's members: one target per member, as a view of the container shows them."""
        group = self.get(name)
        source, path = split_ref(group.of)
        labels = {}
        try:
            labels = next((e.labels for e in resources.catalog(source) if e.path == path), {})
        except Exception:
            pass
        return [Target(source, path, "events", item, labels.get(item, item)) for item in self.members(resources, name)]

    def describe(self, name: str) -> str:
        return rule_text(self.get(name))
