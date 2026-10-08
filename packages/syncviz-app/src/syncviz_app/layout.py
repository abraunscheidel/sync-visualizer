"""What the user has changed about the window since the project file was written.

The project file is the author's description of the data and is never rewritten by the app (it is
hand-edited and has comments). Everything the user adjusts while working is kept beside it in
`<project>.layout.json` and applied on top the next time the project opens:

* the views the user added, and which of the project's own views they removed;
* where the panels, toolbars and sidebar are and how big (Qt's saved window state).

Delete the file, or use Layout > Reset layout, to get the project's defaults back.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

VERSION = 1


@dataclass
class Layout:
    added: list[dict] = field(default_factory=list)       # specs of views the user added
    removed: list[str] = field(default_factory=list)      # titles of project views the user removed
    window: str | None = None                             # Qt window geometry, base64
    main_state: str | None = None                         # Qt toolbar and sidebar state, base64
    views_state: str | None = None                        # Qt state of the views area, base64


def layout_path(project_path: str | Path) -> Path:
    path = Path(project_path)
    return path.with_name(f"{path.stem}.layout.json")


def load_layout(path: Path) -> Layout:
    """The saved layout, or an empty one if there is none or it cannot be read."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if data.get("version") != VERSION:
            return Layout()
        return Layout(
            added=[dict(s) for s in data.get("added", [])],
            removed=[str(t) for t in data.get("removed", [])],
            window=data.get("window"),
            main_state=data.get("main_state"),
            views_state=data.get("views_state"),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return Layout()


def save_layout(path: Path, layout: Layout) -> None:
    path.write_text(json.dumps({"version": VERSION, **asdict(layout)}, indent=2), encoding="utf-8")
