"""Collections: a project can hold many recordings ("sessions", "animals", "runs"...), each a bundle
of sources that share one timeline.

The core calls the bundle a *collection*; what it is called on screen is the project's `label`.
A collection is found by a *provider* (how the project says where to look) and described by:

* `fields`: text that fills the placeholders in the project's source definitions, such as `{path}`,
  `{dir}` and `{stem}` of the file that was found, so one set of definitions serves every collection;
* `attributes`: facts about the collection (which mouse, which day) that the user can filter by.

Built-in providers are `glob` (a folder pattern) and `list` (an explicit list). More can be added
as plugins in the entry-point group `syncviz.collection_providers`.
"""

from __future__ import annotations

import glob
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any, Protocol

from syncviz import plugins

_PLACEHOLDER = re.compile(r"\{(\w+)\}")


@dataclass(frozen=True)
class Collection:
    key: str                                              # unique and safe to use in a file name
    title: str                                            # what the picker shows
    fields: dict[str, str] = field(default_factory=dict)
    attributes: dict[str, Any] = field(default_factory=dict)


class CollectionProvider(Protocol):
    def discover(self, spec: dict, base: Path) -> list[Collection]:
        """The collections described by `spec` (the project's `collections.from`), looking relative to `base`."""


def fill(template: Any, fields: dict[str, str]) -> Any:
    """`template` with each `{name}` replaced from `fields`, through nested dicts and lists.
    A placeholder with no field is left as it is, so the caller can tell the template did not apply."""
    if isinstance(template, str):
        return _PLACEHOLDER.sub(lambda m: str(fields.get(m.group(1), m.group(0))), template)
    if isinstance(template, dict):
        return {k: fill(v, fields) for k, v in template.items()}
    if isinstance(template, list):
        return [fill(v, fields) for v in template]
    return template


def has_unfilled(value: Any) -> bool:
    """Whether a filled template still contains a `{placeholder}` (a field the collection lacks)."""
    if isinstance(value, str):
        return bool(_PLACEHOLDER.search(value))
    if isinstance(value, dict):
        return any(has_unfilled(v) for v in value.values())
    if isinstance(value, list):
        return any(has_unfilled(v) for v in value)
    return False


def safe_key(text: str) -> str:
    return re.sub(r"[^\w.+-]+", "_", text).strip("_") or "collection"


def extract_attributes(patterns: dict[str, str], text: str) -> dict[str, str]:
    """For each attribute, the first group (or whole match) of its regular expression in `text`."""
    found = {}
    for name, pattern in (patterns or {}).items():
        match = re.search(pattern, text)
        if match:
            found[name] = match.group(1) if match.groups() else match.group(0)
    return found


def _unique(collections: list[Collection]) -> list[Collection]:
    seen: dict[str, int] = {}
    out = []
    for c in collections:
        n = seen.get(c.key, 0)
        seen[c.key] = n + 1
        out.append(c if n == 0 else Collection(f"{c.key}-{n + 1}", c.title, c.fields, c.attributes))
    return out


class GlobProvider:
    """One collection per file matching a pattern, for example `data/*/*.nwb`."""

    def discover(self, spec: dict, base: Path, attribute_patterns: dict[str, str] | None = None) -> list[Collection]:
        out = []
        for found in sorted(glob.glob(str(base / spec["glob"]), recursive=True)):
            path = Path(found)
            relative = PurePosixPath(path.relative_to(base).as_posix())
            fields = {"path": str(relative), "dir": str(relative.parent), "stem": path.stem, "name": path.name}
            out.append(Collection(safe_key(path.stem), path.stem, fields,
                                  extract_attributes(attribute_patterns or {}, str(relative))))
        return _unique(out)


class ListProvider:
    """Collections written out one by one:

        from:
          list:
            - {title: "219CR day 1", path: a.nwb, video: a.mkv, attributes: {mouse: 219CR}}

    Every entry other than `key`, `title` and `attributes` fills placeholders of the same name."""

    def discover(self, spec: dict, base: Path, attribute_patterns: dict[str, str] | None = None) -> list[Collection]:
        out = []
        for i, item in enumerate(spec["list"]):
            item = dict(item)
            attributes = dict(item.pop("attributes", {}) or {})
            title = str(item.pop("title", None) or item.get("path") or f"{i + 1}")
            key = safe_key(str(item.pop("key", None) or title))
            fields = {k: str(v) for k, v in item.items()}
            attributes = {**extract_attributes(attribute_patterns or {}, fields.get("path", "")), **attributes}
            out.append(Collection(key, title, fields, attributes))
        return _unique(out)


BUILTIN_PROVIDERS: dict[str, type] = {"glob": GlobProvider, "list": ListProvider}


def discover(spec: dict, base: Path, attribute_patterns: dict[str, str] | None = None) -> list[Collection]:
    """Find the collections a project's `from:` describes, using the provider named by its one key."""
    kinds = [k for k in spec if k in BUILTIN_PROVIDERS or k in plugins.available("collection_providers")]
    if len(kinds) != 1:
        known = ", ".join(sorted({*BUILTIN_PROVIDERS, *plugins.available("collection_providers")}))
        raise ValueError(f"collections `from` needs exactly one of: {known} (got {sorted(spec)})")
    kind = kinds[0]
    provider = BUILTIN_PROVIDERS[kind]() if kind in BUILTIN_PROVIDERS else plugins.load("collection_providers", kind)()
    return provider.discover(spec, base, attribute_patterns)
