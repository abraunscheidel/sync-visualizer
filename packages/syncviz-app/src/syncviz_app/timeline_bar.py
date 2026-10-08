"""The timeline strip: playhead, segment boundaries, and each view's extent."""

from __future__ import annotations

import time

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget

from syncviz.core import Seek
from syncviz_app.context import AppContext

MARGIN = 14
EXTENT_ROW_HEIGHT = 4
EXTENT_ROW_GAP = 2
PLAYING_REPAINT_INTERVAL_S = 1 / 30


class TimelineBar(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
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

    # -- painting ------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        text = pal.color(pal.ColorRole.WindowText)
        groove = QColor(text); groove.setAlpha(28)
        band = QColor(text); band.setAlpha(22)
        current = QColor("#e0a030"); current.setAlpha(70)

        tl = self.context.timeline
        top, groove_h = 8, 24
        p.fillRect(QRectF(MARGIN, top, self.width() - 2 * MARGIN, groove_h), groove)

        nav = self.context.navigator
        if nav is not None:
            iv = nav.intervals
            for i in range(len(iv)):
                x0, x1 = self._x_of(iv.starts[i]), self._x_of(iv.stops[i])
                if x1 < MARGIN or x0 > self.width() - MARGIN:
                    continue
                if i % 2 == 0:
                    p.fillRect(QRectF(x0, top, max(x1 - x0, 1), groove_h), band)
            x0, x1 = self._x_of(nav.bounds[0]), self._x_of(nav.bounds[1])
            p.fillRect(QRectF(x0, top, max(x1 - x0, 2), groove_h), current)

        if tl.selection is not None:
            a, b = tl.selection
            sel = QColor("#4fa3e0"); sel.setAlpha(50)
            p.fillRect(QRectF(self._x_of(a), top, max(self._x_of(b) - self._x_of(a), 2), groove_h), sel)

        # One thin line per view showing where its data exists; gaps are visible in advance.
        y = top + groove_h + 6
        for i, (name, (lo, hi)) in enumerate(self.context.extents.items()):
            colour = QColor.fromHsv((i * 57) % 360, 140, 200)
            p.fillRect(QRectF(self._x_of(lo), y, max(self._x_of(hi) - self._x_of(lo), 1), EXTENT_ROW_HEIGHT), colour)
            y += EXTENT_ROW_HEIGHT + EXTENT_ROW_GAP

        p.setPen(QPen(text, 1))
        font = p.font(); font.setPointSizeF(font.pointSizeF() * 0.85); p.setFont(font)
        p.drawText(QRectF(MARGIN, self.height() - 16, 120, 14), Qt.AlignmentFlag.AlignLeft, f"{tl.start:.1f} s")
        p.drawText(QRectF(self.width() - MARGIN - 120, self.height() - 16, 120, 14),
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
            self._seek_to(event)
