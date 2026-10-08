"""Project configuration: sources, and lazy access to the resources inside them.

References look like "session:processing/behavior/licks": a source name from the
project's `sources` section, a colon, then a path inside that source. Resources
are read on first use and kept, so several views can share one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from syncviz import plugins
from syncviz.resources import EventSeries, IntervalSeries, TimeSeries
from syncviz.sources import Source

_NON_CONSTRUCTOR_KEYS = {"type", "sync_signal"}


def split_ref(ref: str) -> tuple[str, str]:
    source, sep, path = ref.partition(":")
    if not sep or not source or not path:
        raise ValueError(f"reference {ref!r} must look like 'source:path'")
    return source, path


class ResourceStore:
    def __init__(self, sources: dict[str, Source]) -> None:
        self.sources = sources
        self._cache: dict[tuple, Any] = {}

    def close(self) -> None:
        for source in self.sources.values():
            source.close()

    def source(self, name: str) -> Source:
        if name not in self.sources:
            raise KeyError(f"no source named {name!r} (declared: {sorted(self.sources)})")
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

    def intervals(self, ref: str) -> IntervalSeries:
        name, path = split_ref(ref)
        source = self.source(name)
        return self._get(("iv", ref), lambda: source.read_intervals(path))


@dataclass
class Project:
    path: Path
    root: Path
    config: dict
    sources: dict[str, Source]
    resources: ResourceStore = field(init=False)

    def __post_init__(self) -> None:
        self.resources = ResourceStore(self.sources)

    @property
    def name(self) -> str:
        """Display name: `name` from the config, else the project folder's name."""
        return str(self.config.get("name") or self.path.resolve().parent.name)

    @property
    def view_specs(self) -> list[dict]:
        return list(self.config.get("views", []))

    @property
    def segmentation_specs(self) -> dict[str, dict]:
        return dict(self.config.get("segmentations", {}))


def load_project(path: str | Path) -> Project:
    """Read a project file and construct its sources (nothing is read from them yet)."""
    path = Path(path)
    config = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    root = (path.parent / config.get("root", ".")).resolve()
    sources: dict[str, Source] = {}
    for name, spec in (config.get("sources") or {}).items():
        spec = dict(spec)
        kwargs = {k: v for k, v in spec.items() if k not in _NON_CONSTRUCTOR_KEYS}
        if "path" in kwargs:
            kwargs["path"] = (root / kwargs["path"]).resolve()
        sources[name] = plugins.load("sources", spec["type"])(**kwargs)
    return Project(path=path, root=root, config=config, sources=sources)
