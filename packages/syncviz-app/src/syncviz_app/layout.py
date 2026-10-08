"""Layouts: what the user has arranged in the window, kept as named presets for each project.

The project file is the author's description of the data and is never rewritten by the app. A
layout is the user's arrangement on top of it:

* the views the user added, and which of the project's own views they removed;
* where the panels, toolbars and sidebar are and how big (Qt's saved window state).

Each layout is its own file, `<name>.json`, in the project's own `layouts` folder (next to the
project file, or wherever the project's `layouts_dir` says), so projects never share files. The
project file may say which layout opens first (`layout: Whisker analysis`), and `--layout NAME`
on the command line overrides that. Layouts are written only when the user saves them.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_NAME = "Default"
LAYOUTS_FOLDER = "layouts"


@dataclass
class Layout:
    added: list[dict] = field(default_factory=list)       # specs of views the user added
    removed: list[str] = field(default_factory=list)      # titles of project views the user removed
    window: str | None = None                             # Qt window geometry, base64
    main_state: str | None = None                         # Qt toolbar and sidebar state, base64
    views_state: str | None = None                        # Qt state of the views area, base64


def layouts_dir(project_path: str | Path, configured: str | None = None) -> Path:
    """The folder holding this project's layouts."""
    return Path(project_path).parent / (configured or LAYOUTS_FOLDER)


def _file(directory: Path, name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or DEFAULT_NAME
    return directory / f"{safe}.json"


def list_layouts(directory: Path) -> list[str]:
    """Names of the saved layouts, in alphabetical order."""
    names = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            names.append(str(json.loads(path.read_text(encoding="utf-8"))["name"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue                                       # not one of ours, or unreadable
    return names


def load_layout(directory: Path, name: str) -> Layout | None:
    """The named layout, or None if there is none or it cannot be read."""
    try:
        data = json.loads(_file(directory, name).read_text(encoding="utf-8"))
        return Layout(
            added=[dict(s) for s in data.get("added", [])],
            removed=[str(t) for t in data.get("removed", [])],
            window=data.get("window"),
            main_state=data.get("main_state"),
            views_state=data.get("views_state"),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_layout(directory: Path, name: str, layout: Layout) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = _file(directory, name)
    path.write_text(json.dumps({"name": name, **asdict(layout)}, indent=2), encoding="utf-8")
    return path


def delete_layout(directory: Path, name: str) -> None:
    _file(directory, name).unlink(missing_ok=True)
