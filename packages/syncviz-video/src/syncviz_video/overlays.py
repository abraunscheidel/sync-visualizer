"""Layers drawn over the video picture.

A layer is told which moment of the video is on screen (the frame's own time, so it always matches the picture even
when decoding lags behind the playhead) and is asked to paint itself over the image. The first layer is a set of event
badges in a corner; layers that mark where something happened in the picture can follow without changing the view.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import QApplication

from syncviz_app.views.rows import glow_after_events, glow_during_intervals

CORNERS = ("top-left", "top-right", "bottom-left", "bottom-right")
OFF = "off"
DEFAULT_CORNER = "top-right"
DEFAULT_DECAY_S = 0.25            # longer than the indicator lights': an event can be shorter than one screen refresh
MARGIN = 10
VISIBLE_ABOVE = 0.02


class CornerBadges:
    """A small labelled badge for each event row, in a corner of the picture.

    A badge appears when its event happens at the frame on screen and fades over `decay` seconds (an interval's badge stays
    for as long as the interval lasts). Only lit badges are drawn, each in a fixed slot, so the picture stays clear and
    nothing shifts when another badge appears. `corner` can be "off"; rows can be hidden by name.
    """

    def __init__(self, rows: list[dict], corner: str = DEFAULT_CORNER, decay: float = DEFAULT_DECAY_S,
                 hidden: set[str] | frozenset[str] = frozenset()) -> None:
        if decay <= 0:
            raise ValueError("decay must be positive")
        self.rows = rows                                   # each: {name, kind, data}
        self.decay = float(decay)
        self.levels = np.zeros(len(rows))
        self.corner = OFF
        self.hidden: set[str] = set()
        self.set_corner(corner)
        self.set_hidden(hidden)

    @property
    def names(self) -> list[str]:
        return [row["name"] for row in self.rows]

    def set_corner(self, corner: str) -> None:
        if corner != OFF and corner not in CORNERS:
            raise ValueError(f"corner must be one of {', '.join((OFF, *CORNERS))}, not {corner!r}")
        self.corner = corner

    def set_hidden(self, names) -> None:
        self.hidden = set(names)

    def set_time(self, time: float) -> None:
        for i, row in enumerate(self.rows):
            if row["kind"] == "events":
                self.levels[i] = glow_after_events(row["data"], time, self.decay)
            else:
                self.levels[i] = glow_during_intervals(*row["data"], time, self.decay)

    def lit(self) -> list[tuple[int, str, float]]:
        """(slot, name, brightness) of the badges to draw: lit rows that are not hidden, in the slot their place among the
        shown rows gives them."""
        shown = [i for i, row in enumerate(self.rows) if row["name"] not in self.hidden]
        return [(slot, self.rows[i]["name"], float(self.levels[i])) for slot, i in enumerate(shown)
                if self.levels[i] > VISIBLE_ABOVE]

    def paint(self, painter: QPainter, image_rect: QRectF) -> None:
        if self.corner == OFF:
            return
        lit = self.lit()
        if not lit:
            return
        accent = QApplication.palette().color(QApplication.palette().ColorRole.Highlight)
        font = painter.font()
        font.setPixelSize(int(min(max(image_rect.height() * 0.035, 10), 18)))
        painter.setFont(font)
        metrics = QFontMetrics(font)
        height = metrics.height() + 8
        gap = 4
        right, bottom = self.corner.endswith("right"), self.corner.startswith("bottom")
        painter.setPen(Qt.PenStyle.NoPen)
        for slot, name, level in lit:
            width = metrics.horizontalAdvance(name) + 26
            x = image_rect.right() - MARGIN - width if right else image_rect.left() + MARGIN
            offset = slot * (height + gap)
            y = image_rect.bottom() - MARGIN - height - offset if bottom else image_rect.top() + MARGIN + offset
            box = QRectF(x, y, width, height)
            painter.setBrush(QColor(0, 0, 0, int(165 * level)))
            painter.drawRoundedRect(box, 6, 6)
            bar = QColor(accent)
            bar.setAlpha(int(255 * level))
            painter.setBrush(bar)
            painter.drawRoundedRect(QRectF(x + 6, y + 6, 5, height - 12), 2, 2)
            painter.setPen(QColor(255, 255, 255, int(255 * level)))
            painter.drawText(QRectF(x + 16, y, width - 20, height), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, name)
            painter.setPen(Qt.PenStyle.NoPen)
