"""Indicator lights: one lamp per row that lights when its event happens at the playhead.

No time axis: the shared playhead is the time. Each lamp's brightness depends only on how long ago
its event was (an event fades over `decay` seconds of recording time; an interval stays lit while
the playhead is inside it), so pausing, scrubbing and stepping all show the right thing, and an
event that fell between two redraws still shows as a glow.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from syncviz_app.views.base import View
from syncviz_app.views.rows import (
    extent_of, glow_after_events, glow_during_intervals, load_row_data, row_candidates,
)

DEFAULT_DECAY_S = 0.15
MIN_CELL_H, MAX_CELL_H = 6, 28
COMFORTABLE_CELL_H = 18          # with `columns` unset, lamps flow into more columns rather than get squeezed below this
MIN_COLUMN_W = 150


class _Lamps(QWidget):
    """Draws the lamps and their labels, in `columns` columns filled top to bottom."""

    def __init__(self, labels: list[str], columns: int | None = None) -> None:
        super().__init__()
        self.labels = labels
        self.columns = None if columns is None else max(int(columns), 1)     # None: as many as the panel's height calls for
        self.levels = np.zeros(len(labels))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(120, 60)

    def effective_columns(self, width: float, height: float) -> int:
        """The fixed number of columns if the project gave one, else enough that lamps keep a
        comfortable height, as far as the width allows."""
        if self.columns is not None:
            return self.columns
        n = len(self.labels)
        wanted = math.ceil(n * COMFORTABLE_CELL_H / max(height, 1))
        return max(1, min(wanted, n, int(width // MIN_COLUMN_W) or 1))

    def set_levels(self, levels: np.ndarray) -> None:
        if not np.array_equal(levels, self.levels):
            self.levels = levels
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text, lit = pal.color(pal.ColorRole.WindowText), pal.color(pal.ColorRole.Highlight)
        n = len(self.labels)
        if n == 0:
            return
        columns = self.effective_columns(self.width(), self.height())
        per_column = math.ceil(n / columns)
        cell_w = self.width() / columns
        cell_h = min(max(self.height() / per_column, MIN_CELL_H), MAX_CELL_H)
        size = max(cell_h - 6, 6)
        font = p.font()
        font.setPixelSize(int(min(max(cell_h * 0.55, 9), 15)))
        p.setFont(font)
        for i, (label, level) in enumerate(zip(self.labels, self.levels)):
            column, row = divmod(i, per_column)
            x, y = column * cell_w + 8, row * cell_h + (cell_h - size) / 2
            lamp = QRectF(x, y, size, size)
            fill = QColor(lit)
            fill.setAlpha(int(28 + 227 * float(level)))        # never fully off, so the lamps stay visible
            p.setPen(QPen(text if level > 0.5 else QColor(text.red(), text.green(), text.blue(), 90), 1))
            p.setBrush(fill)
            p.drawRoundedRect(lamp, 3, 3)
            p.setPen(text)
            p.drawText(QRectF(x + size + 8, row * cell_h, cell_w - size - 20, cell_h),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)


class IndicatorsView(View):
    type_name = "indicators"
    display_name = "Indicator lights"

    @classmethod
    def candidates(cls, catalog):
        return row_candidates(catalog, cls.type_name)

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        self.decay = float(spec.get("decay", DEFAULT_DECAY_S))
        if self.decay <= 0:
            raise ValueError("decay must be positive")
        self.rows = []
        for row in spec["rows"]:
            self.rows.append({"name": row.get("name", ""), "kind": row["kind"], "data": load_row_data(context, row)})
        self.lamps = _Lamps([r["name"] for r in self.rows], spec.get("columns"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lamps)

    def extent(self):
        return extent_of((r["kind"], r["data"]) for r in self.rows)

    def levels_at(self, time: float) -> np.ndarray:
        out = np.zeros(len(self.rows))
        for i, row in enumerate(self.rows):
            if row["kind"] == "events":
                out[i] = glow_after_events(row["data"], time, self.decay)
            else:
                out[i] = glow_during_intervals(*row["data"], time, self.decay)
        return out

    def refresh(self, time: float) -> None:
        self.lamps.set_levels(self.levels_at(time))
