"""Indicator lights: one tile per row, filling the panel, that lights when its event happens at the playhead.

No time axis: the shared playhead is the time. Each lamp's brightness depends only on how long ago
its event was (an event fades over `decay` seconds of recording time; an interval stays lit while
the playhead is inside it), so pausing, scrubbing and stepping all show the right thing, and an
event that fell between two redraws still shows as a glow.
"""

from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from syncviz_app.views.base import View
from syncviz_app.views.rows import (
    extent_of, glow_after_events, glow_during_intervals, load_row_data, row_candidates, row_target,
)

DEFAULT_DECAY_S = 0.15
GAP = 4                          # pixels between tiles
TARGET_ASPECT = 1.8              # tiles are a little wider than tall, which suits a label
UNLIT_ALPHA, LIT_ALPHA = 30, 255


class _Lamps(QWidget):
    """Tiles that together fill the panel, one per row, lit by brightness 0..1. The label sits inside
    the tile. The grid is chosen to give the biggest, most even tiles, unless `columns` fixes it."""

    def __init__(self, labels: list[str], columns: int | None = None) -> None:
        super().__init__()
        self.labels = labels
        self.columns = None if columns is None else max(int(columns), 1)     # None: pick the best fit
        self.levels = np.zeros(len(labels))
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(120, 60)

    def grid(self, width: float, height: float) -> tuple[int, int]:
        """(columns, rows): the fixed columns if the project gave them, else the arrangement whose tiles
        are closest to the target shape without leaving many empty."""
        n = len(self.labels)
        if self.columns is not None:
            return self.columns, max(math.ceil(n / self.columns), 1)
        best, best_cost = (1, max(n, 1)), math.inf
        for columns in range(1, max(n, 1) + 1):
            rows = math.ceil(n / columns)
            tile_w, tile_h = width / columns, height / rows
            if tile_w <= 0 or tile_h <= 0:
                continue
            cost = abs(math.log((tile_w / tile_h) / TARGET_ASPECT)) + 0.5 * (columns * rows - n) / max(n, 1)
            if cost < best_cost:
                best, best_cost = (columns, rows), cost
        return best

    def tile_rects(self) -> list[QRectF]:
        """Where each tile is drawn: together they fill the whole widget."""
        columns, rows = self.grid(self.width(), self.height())
        w, h = self.width() / columns, self.height() / rows
        return [QRectF((i // rows) * w, (i % rows) * h, w, h).adjusted(GAP / 2, GAP / 2, -GAP / 2, -GAP / 2)
                for i in range(len(self.labels))]

    def set_levels(self, levels: np.ndarray) -> None:
        if not np.array_equal(levels, self.levels):
            self.levels = levels
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        dark, bright = pal.color(pal.ColorRole.WindowText), pal.color(pal.ColorRole.HighlightedText)
        lit = pal.color(pal.ColorRole.Highlight)
        for rect, label, level in zip(self.tile_rects(), self.labels, self.levels):
            level = float(level)
            fill = QColor(lit)
            fill.setAlpha(int(UNLIT_ALPHA + (LIT_ALPHA - UNLIT_ALPHA) * level))
            outline = QColor(dark)
            outline.setAlpha(70)
            p.setPen(QPen(outline, 1))
            p.setBrush(fill)
            p.drawRoundedRect(rect, 6, 6)
            # The label turns from the normal text colour to the highlighted-text colour as the tile lights.
            p.setPen(QColor(int(dark.red() + (bright.red() - dark.red()) * level),
                            int(dark.green() + (bright.green() - dark.green()) * level),
                            int(dark.blue() + (bright.blue() - dark.blue()) * level)))
            font = p.font()
            font.setBold(level > 0.5)
            font.setPixelSize(int(min(max(rect.height() * 0.3, 9), 24)))
            p.setFont(font)
            while font.pixelSize() > 9 and QFontMetrics(font).horizontalAdvance(label) > rect.width() - 10:
                font.setPixelSize(font.pixelSize() - 1)
                p.setFont(font)
            text = QFontMetrics(font).elidedText(label, Qt.TextElideMode.ElideRight, int(rect.width() - 10))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)


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
            self.rows.append({"name": row.get("name", ""), "kind": row["kind"], "data": load_row_data(context, row), "spec": row})
        self.lamps = _Lamps([r["name"] for r in self.rows], spec.get("columns"))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.lamps)
        self.enable_hover(self.lamps)

    def target_at(self, pos):
        point = self.lamps.mapFrom(self, pos)
        for rect, row in zip(self.lamps.tile_rects(), self.rows):
            if rect.contains(point.x(), point.y()):
                return row_target(row["spec"])
        return None

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
