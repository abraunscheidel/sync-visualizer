"""One colour per view, used wherever a view is represented outside its own panel."""

from __future__ import annotations

from PySide6.QtGui import QColor

_GOLDEN_RATIO_CONJUGATE = 0.618033988749895


def view_color(index: int) -> str:
    """A distinct, readable colour for the index-th view (stepping the hue by the golden ratio
    keeps neighbours well apart however many views there are)."""
    hue = (0.08 + index * _GOLDEN_RATIO_CONJUGATE) % 1.0
    return QColor.fromHsvF(hue, 0.55, 0.85).name()
