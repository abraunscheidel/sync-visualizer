"""Workspaces: what the user has arranged in the window, kept as named presets for each project.

The project file is the author's description of the data and is never rewritten by the app. A
workspace is the user's arrangement on top of it:

* the views the user added, and which of the project's own views they removed;
* where the panels, toolbars and sidebar are and how big (Qt's saved window state);
* the working settings: the filters and whether movement skips what they hide, the playback speed,
  what a frame is and how many each step moves, and where the playhead is (never whether it is playing).

Each workspace is its own file, `<name>.json`, in the project's own `workspaces` folder (next to the
project file, or wherever the project's `workspaces_dir` says), so projects never share files. The
project file may say which workspace opens first (`workspace: Whisker analysis`), and `--workspace NAME`
on the command line overrides that. Workspaces are written only when the user saves them.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_NAME = "Default"
WORKSPACES_FOLDER = "workspaces"


@dataclass
class Workspace:
    added: list[dict] = field(default_factory=list)       # specs of views the user added
    removed: list[str] = field(default_factory=list)      # titles of project views the user removed
    window: str | None = None                             # Qt window geometry, base64
    main_state: str | None = None                         # Qt toolbar and sidebar state, base64
    views_state: str | None = None                        # Qt state of the views area, base64
    settings: dict = field(default_factory=dict)          # filters, frame step, speed, playhead (see controls.py)


def workspaces_dir(project_path: str | Path, configured: str | None = None) -> Path:
    """The folder holding this project's workspaces."""
    return Path(project_path).parent / (configured or WORKSPACES_FOLDER)


def _file(directory: Path, name: str) -> Path:
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .") or DEFAULT_NAME
    return directory / f"{safe}.json"


def list_workspaces(directory: Path) -> list[str]:
    """Names of the saved workspaces, in alphabetical order."""
    names = []
    for path in sorted(directory.glob("*.json")) if directory.is_dir() else []:
        try:
            names.append(str(json.loads(path.read_text(encoding="utf-8"))["name"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue                                       # not one of ours, or unreadable
    return names


def load_workspace(directory: Path, name: str) -> Workspace | None:
    """The named workspace, or None if there is none or it cannot be read."""
    try:
        data = json.loads(_file(directory, name).read_text(encoding="utf-8"))
        return Workspace(
            added=[dict(s) for s in data.get("added", [])],
            removed=[str(t) for t in data.get("removed", [])],
            window=data.get("window"),
            main_state=data.get("main_state"),
            views_state=data.get("views_state"),
            settings=dict(data.get("settings", {})),
        )
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_workspace(directory: Path, name: str, workspace: Workspace) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = _file(directory, name)
    path.write_text(json.dumps({"name": name, **asdict(workspace)}, indent=2), encoding="utf-8")
    return path


def load_collection_state(directory: Path, key: str) -> dict:
    """What is remembered about one collection (for now where the playhead was); {} if nothing."""
    try:
        return dict(json.loads((directory / f"{key}.json").read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return {}


def save_collection_state(directory: Path, key: str, state: dict) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{key}.json").write_text(json.dumps(state, indent=2), encoding="utf-8")


def delete_workspace(directory: Path, name: str) -> None:
    _file(directory, name).unlink(missing_ok=True)
