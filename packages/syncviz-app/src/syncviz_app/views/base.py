"""Base class for views: the panels a user can arrange in the window.

A view reads generic resources and draws them. It never talks to another view:
user gestures become actions on the bus, and the view redraws when told the
playhead has moved.
"""

from __future__ import annotations

from PySide6.QtWidgets import QWidget

from syncviz_app.context import AppContext


class View(QWidget):
    type_name = ""

    def __init__(self, context: AppContext, spec: dict) -> None:
        super().__init__()
        self.context = context
        self.spec = spec
        self.title: str = spec.get("title") or self.type_name

    def extent(self) -> tuple[float, float] | None:
        """Range of shared time this view has data for, or None if it has no time extent."""
        return None

    def refresh(self, time: float) -> None:
        """Redraw for the playhead at `time` (shared time). Only called while visible."""
        raise NotImplementedError

    def close_view(self) -> None:
        """Release resources (threads, files). Called when the window closes."""
