"""Project configuration: sources, and lazy access to the resources inside them.

References look like "session:processing/behavior/licks": a source name from the
project's `sources` section, a colon, then a path inside that source. Resources
are read on first use and kept, so several views can share one.
"""

from __future__ import annotations

import glob
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

import json

from syncviz import plugins, processors
from syncviz.resources import EventSeries, IntervalSeries, TimeSeries
from syncviz.catalog import Collection, discover, fill, has_unfilled
from syncviz.sources import MissingDataError, Source

_NON_CONSTRUCTOR_KEYS = {"type", "sync_signal"}


def split_ref(ref: str) -> tuple[str, str]:
    source, sep, path = ref.partition(":")
    if not sep or not source or not path:
        raise ValueError(f"reference {ref!r} must look like 'source:path'")
    return source, path


class MissingSourceError(MissingDataError):
    """The collection has no source of this name (for example no video for one recording)."""


class ResourceStore:
    def __init__(self, sources: dict[str, Source]) -> None:
        self.sources = sources
        self._cache: dict[tuple, Any] = {}

    def close(self) -> None:
        for source in self.sources.values():
            source.close()

    def source(self, name: str) -> Source:
        if name not in self.sources:
            raise MissingSourceError(f"no source named {name!r} (this collection has: {sorted(self.sources)})")
        return self.sources[name]

    def _get(self, key: tuple, load):
        if key not in self._cache:
            self._cache[key] = load()
        return self._cache[key]

    def timeseries(self, ref: str, member: str | None = None) -> TimeSeries:
        name, path = split_ref(ref)
        source = self.source(name)
        only = None if member is None else [member]
        members = self._get(("ts", ref, member), lambda: source.read_timeseries(path, only=only))
        if member is None:
            if len(members) != 1:
                raise ValueError(f"{ref!r} has several members {sorted(members)}; name one with 'member'")
            return next(iter(members.values()))
        return members[member]

    def events(self, ref: str, member: str | None = None) -> EventSeries:
        name, path = split_ref(ref)
        source = self.source(name)
        members = self._get(("ev", ref), lambda: source.read_events(path))
        if member is None:
            if len(members) != 1:
                raise ValueError(f"{ref!r} has several members {sorted(members)}; name one with 'member'")
            return next(iter(members.values()))
        return members[member]

    def events_of(self, ref: str) -> dict[str, EventSeries]:
        """Every member of an event container, such as all the units of a recording."""
        name, path = split_ref(ref)
        source = self.source(name)
        return self._get(("ev", ref), lambda: source.read_events(path))

    def derived(self, spec: dict) -> TimeSeries:
        """A series computed by a processor from other resources, as the spec says:

            {process: population_rate, inputs: ["session:units", {from: "session:licks", member: left}], bin_ms: 10}

        An input written as text is every member of that event container; one written as `{from, member}` is one
        member. Other keys are the processor's parameters. The result is kept, so views share it."""
        key = ("derived", json.dumps(spec, sort_keys=True, default=str))

        def build():
            inputs: list[EventSeries] = []
            for item in spec.get("inputs", []):
                if isinstance(item, str):
                    inputs += list(self.events_of(item).values())
                else:
                    inputs.append(self.events(item["from"], item.get("member")))
            params = {k: v for k, v in spec.items() if k not in ("process", "inputs")}
            return processors.get(spec["process"])().run(inputs, **params)

        return self._get(key, build)

    def intervals(self, ref: str) -> IntervalSeries:
        name, path = split_ref(ref)
        source = self.source(name)
        return self._get(("iv", ref), lambda: source.read_intervals(path))


@dataclass
class Project:
    """A project file, and the collection currently open in it.

    Without a `collections` section the project is a single recording (one collection called
    "default") and `sources` are used as written. With one, `sources` is a template: its
    `{placeholders}` are filled from each collection, and a source whose file is not there for a
    collection is simply left out, so views that need it show "no data".
    """

    path: Path
    root: Path
    config: dict
    collections: list[Collection]
    active: int = 0
    sources: dict[str, Source] = field(init=False)
    resources: ResourceStore = field(init=False)

    def __post_init__(self) -> None:
        self.sources = self.build_sources(self.collections[self.active])
        self.resources = ResourceStore(self.sources)

    @property
    def name(self) -> str:
        """Display name: `name` from the config, else the project folder's name."""
        return str(self.config.get("name") or self.path.resolve().parent.name)

    @property
    def collection(self) -> Collection:
        return self.collections[self.active]

    @property
    def multiple(self) -> bool:
        return len(self.collections) > 1

    @property
    def collection_label(self) -> str:
        return str((self.config.get("collections") or {}).get("label") or "Collection")

    @property
    def view_specs(self) -> list[dict]:
        return list(self.config.get("views", []))

    @property
    def segmentation_specs(self) -> dict[str, dict]:
        return dict(self.config.get("segmentations", {}))

    # -- sources ---------------------------------------------------------------------------
    def build_sources(self, collection: Collection) -> dict[str, Source]:
        templated = bool(self.config.get("collections"))
        sources: dict[str, Source] = {}
        for name, spec in (self.config.get("sources") or {}).items():
            spec = fill(dict(spec), collection.fields) if templated else dict(spec)
            if templated and has_unfilled(spec):
                continue                                           # the collection lacks a field this source needs
            kwargs = {k: v for k, v in spec.items() if k not in _NON_CONSTRUCTOR_KEYS}
            if "path" in kwargs:
                path = self._resolve_path(kwargs["path"], must_exist=templated)
                if path is None:
                    continue                                       # no such file for this collection
                kwargs["path"] = path
            sources[name] = plugins.load("sources", spec["type"])(**kwargs)
        return sources

    def _resolve_path(self, text: str, must_exist: bool) -> Path | None:
        if any(ch in text for ch in "*?["):
            found = sorted(glob.glob(str(self.root / text)))
            return Path(found[0]).resolve() if found else None
        path = (self.root / text).resolve()
        return path if (path.exists() or not must_exist) else None

    def open_collection(self, index: int) -> ResourceStore:
        """The resources of another collection, ready to use. Nothing changes until `activate`."""
        return ResourceStore(self.build_sources(self.collections[index]))

    def activate(self, index: int, resources: ResourceStore) -> None:
        self.active, self.resources, self.sources = index, resources, resources.sources


def load_project(path: str | Path, collection: str | None = None) -> Project:
    """Read a project file and find its collections (nothing is read from any source yet).
    `collection` is the key of the one to open first (else the file's `collection:`, else the first)."""
    path = Path(path)
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = (path.parent / config.get("root", ".")).resolve()
    spec = config.get("collections")
    if spec:
        collections = discover(spec["from"], root, spec.get("attributes"))
        if not collections:
            raise ValueError(f"no {spec.get('label', 'collection').lower()}s found by {spec['from']}")
    else:
        collections = [Collection("default", str(config.get("name") or path.resolve().parent.name))]
    wanted = collection or config.get("collection")
    keys = [c.key for c in collections]
    if wanted is not None and wanted not in keys:
        raise ValueError(f"no collection {wanted!r} (found: {', '.join(keys[:12])}{' ...' if len(keys) > 12 else ''})")
    return Project(path=path, root=root, config=config, collections=collections,
                   active=keys.index(wanted) if wanted is not None else 0)
