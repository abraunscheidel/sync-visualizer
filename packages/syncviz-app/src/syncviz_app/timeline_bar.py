"""The timeline strip: playhead and segments, and where each view has data.

The grey bar is the shared timeline: its bands are segments (such as trials), the amber
band is the current one and the blue band the selection. Below it, "Data coverage" has one
line per view, in that view's colour, drawn only where the view has data, so gaps in a
source show as breaks. The same colour marks the view's panel title.
"""

from __future__ import annotations

import bisect
import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QToolTip, QWidget

from syncviz.core import Seek
from syncviz_app.context import AppContext

MARGIN = 14
GROOVE_TOP = 8
GROOVE_HEIGHT = 24
CAPTION_TOP = GROOVE_TOP + GROOVE_HEIGHT + 4
CAPTION_HEIGHT = 12
ROWS_TOP = CAPTION_TOP + CAPTION_HEIGHT + 2
ROW_HEIGHT = 6
ROW_PITCH = 8                           # row height plus the gap below it
LABELS_HEIGHT = 18
PLAYING_REPAINT_INTERVAL_S = 1 / 30


class TimelineBar(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self._names = list(context.extents)                 # row order
        self.setFixedHeight(ROWS_TOP + max(len(self._names), 1) * ROW_PITCH + 6 + LABELS_HEIGHT)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMouseTracking(True)                         # tooltips while hovering, not just dragging
        self._last_request = 0.0
        context.timeline.subscribe(self._on_timeline)
        if context.navigator is not None:
            context.navigator.subscribe(lambda _n: self.update())

    def _on_timeline(self, tl) -> None:
        now = time.perf_counter()
        if tl.playing and now - self._last_request < PLAYING_REPAINT_INTERVAL_S:
            return                       # the strip moves slowly; no need to repaint it every tick
        self._last_request = now
        self.update()

    # -- coordinates ---------------------------------------------------------------------
    def _x_of(self, time: float) -> float:
        tl = self.context.timeline
        width = max(self.width() - 2 * MARGIN, 1)
        return MARGIN + (time - tl.start) / (tl.stop - tl.start) * width

    def _time_at(self, x: float) -> float:
        tl = self.context.timeline
        width = max(self.width() - 2 * MARGIN, 1)
        return tl.start + (x - MARGIN) / width * (tl.stop - tl.start)

    def _pixel_runs(self, runs: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Coverage runs in pixels, with gaps narrower than a pixel closed up.

        A gap too small to see would otherwise leave anti-aliasing seams that look like
        texture. Every gap is still reported in the tooltip and the project panel.
        """
        merged: list[list[float]] = []
        for lo, hi in runs:
            x0, x1 = self._x_of(lo), self._x_of(hi)
            if merged and x0 - merged[-1][1] < 1.0:
                merged[-1][1] = max(merged[-1][1], x1)
            else:
                merged.append([x0, x1])
        return [(a, b) for a, b in merged]

    # -- what is under the pointer -------------------------------------------------------
    def row_at(self, y: float) -> str | None:
        """Name of the view whose coverage line is at height `y`, if any."""
        if y < ROWS_TOP:
            return None
        row = int((y - ROWS_TOP) // ROW_PITCH)
        return self._names[row] if 0 <= row < len(self._names) else None

    def has_data_at(self, name: str, time: float) -> bool:
        runs = self.context.coverage.get(name, [])
        i = bisect.bisect_right([r[0] for r in runs], time) - 1
        return i >= 0 and time <= runs[i][1]

    def tooltip_at(self, x: float, y: float) -> str | None:
        name = self.row_at(y)
        if name is None:
            return None
        lo, hi = self.context.extents[name]
        t = self._time_at(x)
        runs = self.context.coverage.get(name, [])
        lines = [name, f"Data from {lo:.2f} to {hi:.2f} s"]
        if len(runs) > 1:
            lines.append(f"{len(runs) - 1} gap{'s' if len(runs) > 2 else ''} in between")
        lines.append(f"At {t:.2f} s: {'has data' if self.has_data_at(name, t) else 'no data'}")
        return "\n".join(lines)

    # -- painting ------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text = pal.color(pal.ColorRole.WindowText)
        groove = QColor(text); groove.setAlpha(28)
        band = QColor(text); band.setAlpha(22)
        current = QColor("#e0a030"); current.setAlpha(70)
        muted = QColor(text); muted.setAlpha(140)

        tl = self.context.timeline
        top, groove_h = GROOVE_TOP, GROOVE_HEIGHT
        p.fillRect(QRectF(MARGIN, top, self.width() - 2 * MARGIN, groove_h), groove)

        nav = self.context.navigator
        if nav is not None:
            iv = nav.intervals
            matching = QColor("#4fa3e0"); matching.setAlpha(95)
            dimmed = QColor(text); dimmed.setAlpha(8)
            for i in range(len(iv)):
                x0, x1 = self._x_of(iv.starts[i]), self._x_of(iv.stops[i])
                if x1 < MARGIN or x0 > self.width() - MARGIN:
                    continue
                if nav.filtered:                  # matches stand out; the rest recede
                    p.fillRect(QRectF(x0, top, max(x1 - x0 - 0.5, 1), groove_h), matching if nav.is_match(i) else dimmed)
                elif i % 2 == 0:
                    p.fillRect(QRectF(x0, top, max(x1 - x0, 1), groove_h), band)
            x0, x1 = self._x_of(nav.bounds[0]), self._x_of(nav.bounds[1])
            p.fillRect(QRectF(x0, top, max(x1 - x0, 2), groove_h), current)

        if tl.selection is not None:
            a, b = tl.selection
            sel = QColor("#4fa3e0"); sel.setAlpha(50)
            p.fillRect(QRectF(self._x_of(a), top, max(self._x_of(b) - self._x_of(a), 2), groove_h), sel)

        font = p.font(); font.setPointSizeF(font.pointSizeF() * 0.8); p.setFont(font)
        p.setPen(muted)
        p.drawText(QRectF(MARGIN, CAPTION_TOP, 200, CAPTION_HEIGHT), Qt.AlignmentFlag.AlignLeft, "Data coverage")

        # One line per view, in its colour, drawn only where it has data.
        for row, name in enumerate(self._names):
            y = ROWS_TOP + row * ROW_PITCH
            colour = QColor(self.context.colors.get(name, "#888888"))
            for x0, x1 in self._pixel_runs(self.context.coverage.get(name, [])):
                p.fillRect(QRectF(x0, y, max(x1 - x0, 1), ROW_HEIGHT), colour)

        p.setPen(QPen(text, 1))
        label_y = self.height() - LABELS_HEIGHT + 2
        p.drawText(QRectF(MARGIN, label_y, 120, 14), Qt.AlignmentFlag.AlignLeft, f"{tl.start:.1f} s")
        p.drawText(QRectF(self.width() - MARGIN - 120, label_y, 120, 14),
                   Qt.AlignmentFlag.AlignRight, f"{tl.stop:.1f} s")

        x = self._x_of(tl.time)
        p.setPen(QPen(QColor("#e0a030"), 2))
        p.drawLine(int(x), 2, int(x), top + groove_h + 2)

    # -- interaction ---------------------------------------------------------------------
    def _seek_to(self, event) -> None:
        self.context.bus.publish(Seek(self._time_at(event.position().x())))
        self.update()                    # dragging must feel immediate, so this bypasses the throttle

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._seek_to(event)

    def mouseMoveEvent(self, event) -> None:
        if event.buttons() & Qt.MouseButton.LeftButton:
            QToolTip.hideText()
            self._seek_to(event)
            return
        tip = self.tooltip_at(event.position().x(), event.position().y())
        if tip:
            QToolTip.showText(event.globalPosition().toPoint(), tip, self)
        else:
            QToolTip.hideText()
