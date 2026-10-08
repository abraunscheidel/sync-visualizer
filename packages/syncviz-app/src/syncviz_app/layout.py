"""What the user has changed about the window since the project file was written.

The project file is the author's description of the data and is never rewritten by the app (it is
hand-edited and has comments). Everything the user adjusts while working is kept beside it in
`<project>.layout.json` and applied on top the next time the project opens. A project can have
several named layouts (for example one for reviewing behaviour and one for whisker analysis), and
the one in use is saved automatically under its name when the window closes or another is chosen.

A layout is:

* the views the user added, and which of the project's own views they removed;
* where the panels, toolbars and sidebar are and how big (Qt's saved window state).

Each project has its own file, so projects never share or overwrite one another's layouts.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = 2
DEFAULT_NAME = "Default"


@dataclass
class Layout:
    added: list[dict] = field(default_factory=list)       # specs of views the user added
    removed: list[str] = field(default_factory=list)      # titles of project views the user removed
    window: str | None = None                             # Qt window geometry, base64
    main_state: str | None = None                         # Qt toolbar and sidebar state, base64
    views_state: str | None = None                        # Qt state of the views area, base64


@dataclass
class LayoutStore:
    """All of a project's named layouts and which one is in use."""

    current: str = DEFAULT_NAME
    layouts: dict[str, Layout] = field(default_factory=lambda: {DEFAULT_NAME: Layout()})

    @property
    def active(self) -> Layout:
        return self.layouts[self.current]

    @property
    def names(self) -> list[str]:
        return list(self.layouts)


def layout_path(project_path: str | Path) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.stem}.layout.json")


def _layout_from(data: dict) -> Layout:
    return Layout(
        added=[dict(s) for s in data.get("added", [])],
        removed=[str(t) for t in data.get("removed", [])],
        window=data.get("window"),
        main_state=data.get("main_state"),
        views_state=data.get("views_state"),
    )


def load_store(path: Path) -> LayoutStore:
    """The saved layouts, or just the default one if there is no file or it cannot be read.
    A file from before layouts were named becomes the layout called "Default"."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") == 1:
            return LayoutStore(DEFAULT_NAME, {DEFAULT_NAME: _layout_from(data)})
        if data.get("version") != VERSION:
            return LayoutStore()
        layouts = {str(name): _layout_from(body) for name, body in data["layouts"].items()}
        if not layouts:
            return LayoutStore()
        current = data.get("current")
        return LayoutStore(current if current in layouts else next(iter(layouts)), layouts)
    except (OSError, ValueError, TypeError, AttributeError, KeyError):
        return LayoutStore()


def save_store(path: Path, store: LayoutStore) -> None:
    body = {"version": VERSION, "current": store.current,
            "layouts": {name: asdict(layout) for name, layout in store.layouts.items()}}
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
