"""What stands in for a view whose data this collection does not have."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout

from syncviz_app.views.base import View


class PlaceholderView(View):
    """Keeps the view's panel, title and place, and says calmly that there is nothing to show here.
    The panel stays because the next collection may have the data."""

    type_name = "placeholder"

    def __init__(self, context, spec: dict, reason: str = "") -> None:
        super().__init__(context, spec)
        self.reason = reason
        layout = QVBoxLayout(self)
        message = QLabel(f"No data in this {context.collection_label.lower()}")
        message.setAlignment(Qt.AlignmentFlag.AlignCenter)
        message.setEnabled(False)                       # dimmed, like the video's placeholder
        layout.addWidget(message)
        if reason:
            detail = QLabel(reason)
            detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
            detail.setEnabled(False)
            detail.setWordWrap(True)
            small = detail.font()
            small.setPointSizeF(small.pointSizeF() * 0.85)
            detail.setFont(small)
            layout.addWidget(detail)

    def refresh(self, time: float) -> None:
        """Nothing to draw."""
