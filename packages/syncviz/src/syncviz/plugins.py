"""Plugin discovery via Python entry points.

Plugin packages register implementations in their pyproject.toml, e.g.

    [project.entry-points."syncviz.sources"]
    nwb = "syncviz_nwb:NWBSource"

and the core resolves a config's `type: nwb` to that object without ever
importing the plugin package directly.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint, entry_points

GROUPS = {
    "sources": "syncviz.sources",
    "processors": "syncviz.processors",
    "sync_methods": "syncviz.sync_methods",
    "sync_detectors": "syncviz.sync_detectors",
    "views": "syncviz.views",
}


def available(kind: str) -> dict[str, EntryPoint]:
    """Registered plugins of one kind, keyed by the name used in project configs."""
    return {ep.name: ep for ep in entry_points(group=GROUPS[kind])}


def load(kind: str, name: str) -> object:
    plugins = available(kind)
    if name not in plugins:
        known = ", ".join(sorted(plugins)) or "none installed"
        raise KeyError(f"no {kind} plugin named {name!r} (available: {known})")
    return plugins[name].load()
