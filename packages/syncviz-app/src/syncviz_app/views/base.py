"""Base class for views: the panels a user can arrange in the window.

A view reads generic resources and draws them. It never talks to another view:
user gestures become actions on the bus, and the view redraws when told the
playhead has moved.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from dataclasses import dataclass

from syncviz.sources import DataEntry
from syncviz_app.context import AppContext


def describe_delay(milliseconds: float, sentence: bool = False) -> str:
    """A view's display delay in words, so nobody has to remember which way a sign points.
    Positive means delayed (the view runs behind the playhead), negative means ahead of it."""
    if not milliseconds:
        return "No delay" if sentence else ""
    amount = f"{abs(milliseconds):g} ms"
    if sentence:
        return f"This view runs {amount} " + ("behind the playhead." if milliseconds > 0 else "ahead of the playhead.")
    return f"delayed {amount}" if milliseconds > 0 else f"ahead {amount}"


@dataclass
class ViewSetting:
    """One setting a view offers the user, shown under the Views list when the view is selected.

    `kind` is "choice" (one of `choices`, each a `(label, value)`) or "toggle" (on or off). `value` is the current value.
    The view applies a new one in `apply_setting` and returns to its project defaults in `reset_settings`; the window keeps
    the user's choices in the workspace, by view title.
    """

    key: str
    label: str
    kind: str
    value: object
    choices: list[tuple[str, object]] | None = None


@dataclass
class Candidate:
    """A view the user could add: what to call it in the dialog, and the spec that creates it."""

    label: str
    spec: dict


class View(QWidget):
    type_name = ""
    display_name = ""              # what the "add a view" dialog calls this kind of view
    default_refresh_hz = 30.0      # redraws per second while the playhead moves; see refresh.py

    def __init__(self, context: AppContext, spec: dict) -> None:
        super().__init__()
        self.context = context
        self.spec = spec
        self.title: str = spec.get("title") or self.type_name
        # Upper limit on how often this view redraws. A project can override it per view.
        # Display delay in seconds (`lag`): positive means delayed, so the view shows what the playhead showed `lag` ago;
        # negative means ahead. See describe_delay.
        # It changes only what this view draws, never the data or the timeline.
        self.lag: float = 0.0
        self.refresh_hz: float = float(spec.get("refresh_hz", self.default_refresh_hz))

    def settings(self) -> list[ViewSetting]:
        """The settings this view offers (none by default)."""
        return []

    def apply_setting(self, key: str, value) -> None:
        """Change one of the settings listed by `settings`."""

    def reset_settings(self) -> None:
        """Return every setting to what the project file gives (or the view's own default)."""

    @classmethod
    def candidates(cls, catalog: dict[str, list[DataEntry]]) -> list[Candidate]:
        """The views of this type that the available data (by source name) could feed. Types that
        return nothing can only be added through the project file."""
        return []

    def extent(self) -> tuple[float, float] | None:
        """Range of shared time this view has data for, or None if it has no time extent."""
        return None

    def time_base(self):
        """The grid of ticks this view's data naturally has (video frames, signal samples), as
        a `syncviz.core.TimeBase`, or None if it has no such grid. Offered to the user as a
        choice of what one "step" means."""
        return None

    def coverage(self) -> list[tuple[float, float]]:
        """Runs of shared time in which this view has data. Defaults to its whole extent;
        views whose data has real dropouts report them so the timeline can show the gaps."""
        extent = self.extent()
        return [] if extent is None else [extent]

    def stalled_for(self, now: float) -> float:
        """Seconds this view has been waiting, with no progress, for what it needs to show the
        current playhead position (0 if it is up to date or can answer immediately). Slow views
        such as a video decoding a distant frame override this; see `stall.py`."""
        return 0.0

    def refresh(self, time: float) -> None:
        """Redraw for the playhead at `time` (shared time). Only called while visible."""
        raise NotImplementedError

    def close_view(self) -> None:
        """Release resources (threads, files). Called when the window closes."""
