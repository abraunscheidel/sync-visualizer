"""Layers drawn over the video picture.

A layer is told which moment of the video is on screen (the frame's own time, so it always matches the picture even
when decoding lags behind the playhead) and is asked to paint itself over the image. Layers mark where something is or happened
in the picture. Events as such (a lick, a reward) are shown by the event tracker view, not over the picture.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QApplication

from syncviz_app.views.rows import glow_after_events, glow_during_intervals

DEFAULT_DECAY_S = 0.25            # longer than the indicator lights': an event can be shorter than one screen refresh
MARGIN = 10
VISIBLE_ABOVE = 0.02


# -- layers that mark where something is in the picture -----------------------------------------------------
PALETTE_START = 0.0
GOLDEN = 0.618033988749895


def palette(index: int) -> QColor:
    """A distinct, bright colour for the index-th tracked thing."""
    return QColor.fromHsvF((PALETTE_START + index * GOLDEN) % 1.0, 0.75, 1.0)


class TrackedLines:
    """Line segments that follow something being tracked, such as a whisker from its base to its tip.

    Each line has four series (the x and y of two points, in the stored units of the file) that are looked up at the time of
    the frame on screen. Positions are converted to picture pixels with `units_per_pixel`, which is taken from the
    series' own conversion factor when the project does not say. A frame with no tracked sample close enough in time, or
    with a missing value, shows no line rather than a stale one.
    """

    def __init__(self, items: list[dict], hidden=frozenset()) -> None:
        self.items = items               # each: name, times, base_x, base_y, tip_x, tip_y (arrays), scale (pixels per stored unit), color
        self.hidden: set[str] = set(hidden)
        self.points: list[tuple[float, float, float, float] | None] = [None] * len(items)

    @property
    def names(self) -> list[str]:
        return [item["name"] for item in self.items]

    def set_hidden(self, names) -> None:
        self.hidden = set(names)

    def set_time(self, time: float) -> None:
        for i, item in enumerate(self.items):
            times = item["times"]
            j = int(np.searchsorted(times, time))
            candidates = [k for k in (j - 1, j) if 0 <= k < len(times)]
            if not candidates:
                self.points[i] = None
                continue
            k = min(candidates, key=lambda c: abs(times[c] - time))
            if abs(times[k] - time) > item["max_gap"]:
                self.points[i] = None
                continue
            values = np.array([item[key][k] for key in ("base_x", "base_y", "tip_x", "tip_y")], dtype=float)
            self.points[i] = None if not np.isfinite(values).all() else tuple(values * item["scale"])

    def paint(self, painter: QPainter, image_rect: QRectF, image_size: tuple[int, int] = (1, 1)) -> None:
        width, _height = image_size
        zoom = image_rect.width() / max(width, 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for item, point in zip(self.items, self.points):
            if point is None or item["name"] in self.hidden:
                continue
            bx, by, tx, ty = point
            pen = QPen(item["color"], max(2.0, zoom * 2.5))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(image_rect.left() + bx * zoom, image_rect.top() + by * zoom),
                             QPointF(image_rect.left() + tx * zoom, image_rect.top() + ty * zoom))


class ContactMarkers:
    """A ring where each interval happens in the picture (for a whisker contact, at the whisker's tip), shown while the
    interval lasts and fading after it. The position is a column of the interval table, in picture pixels."""

    def __init__(self, items: list[dict], decay: float = DEFAULT_DECAY_S, hidden=frozenset()) -> None:
        if decay <= 0:
            raise ValueError("decay must be positive")
        self.items = items               # each: name, starts, stops, x, y (arrays aligned with starts), scale, color
        self.decay = float(decay)
        self.hidden: set[str] = set(hidden)
        self.state: list[tuple[float, float, float] | None] = [None] * len(items)      # (x, y, brightness)

    @property
    def names(self) -> list[str]:
        return [item["name"] for item in self.items]

    def set_hidden(self, names) -> None:
        self.hidden = set(names)

    def set_time(self, time: float) -> None:
        for i, item in enumerate(self.items):
            j = int(np.searchsorted(item["starts"], time, side="right")) - 1
            level = glow_during_intervals(item["starts"], item["stops"], time, self.decay)
            x, y = (item["x"][j], item["y"][j]) if j >= 0 else (np.nan, np.nan)
            self.state[i] = (float(x) * item["scale"], float(y) * item["scale"], level) if level > VISIBLE_ABOVE and np.isfinite([x, y]).all() else None

    def paint(self, painter: QPainter, image_rect: QRectF, image_size: tuple[int, int] = (1, 1)) -> None:
        width, _height = image_size
        zoom = image_rect.width() / max(width, 1)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for item, state in zip(self.items, self.state):
            if state is None or item["name"] in self.hidden:
                continue
            x, y, level = state
            colour = QColor(item["color"])
            colour.setAlpha(int(255 * level))
            painter.setPen(QPen(colour, max(2.0, zoom * 3.0)))
            radius = max(10.0, zoom * 16.0)
            painter.drawEllipse(QPointF(image_rect.left() + x * zoom, image_rect.top() + y * zoom), radius, radius)


SKELETON_STYLES = ("curve", "points", "both")
SKELETON_LABELS = {"curve": "Curve", "points": "Points", "both": "Curve and points"}


class TrackedSkeletons:
    """Tracked points drawn on the picture, as a smooth curve through them, as dots, or both.

    Each item is a `PointTracks` (for a whisker: eight markers from tip to base). The positions are looked up at the time of
    the frame on screen; a frame with no tracked sample close enough shows nothing. The points are in picture pixels unless the
    project gives `units_per_pixel`.
    """

    def __init__(self, items: list[dict], style: str = "curve", hidden=frozenset()) -> None:
        self.items = items               # each: name, group, tracks (PointTracks), scale (pixels per stored unit), color, order
        self.hidden: set[str] = set(hidden)
        self.style = "curve"
        self.set_style(style)
        self.points: list[np.ndarray | None] = [None] * len(items)

    @property
    def names(self) -> list[str]:
        return [item["name"] for item in self.items]

    def set_style(self, style: str) -> None:
        if style not in SKELETON_STYLES:
            raise ValueError(f"style must be one of {', '.join(SKELETON_STYLES)}, not {style!r}")
        self.style = style

    def set_hidden(self, names) -> None:
        self.hidden = set(names)

    def set_time(self, time: float) -> None:
        for i, item in enumerate(self.items):
            found = item["tracks"].at(time)
            self.points[i] = None if found is None else found * item["scale"]

    def paint(self, painter: QPainter, image_rect: QRectF, image_size: tuple[int, int] = (1, 1)) -> None:
        width, _height = image_size
        zoom = image_rect.width() / max(width, 1)

        def place(point) -> QPointF:
            return QPointF(image_rect.left() + float(point[0]) * zoom, image_rect.top() + float(point[1]) * zoom)

        for item, found in zip(self.items, self.points):
            if found is None or item["name"] in self.hidden:
                continue
            ordered = [place(found[i]) for i in item["order"] if np.isfinite(found[i]).all()]
            if not ordered:
                continue
            if self.style in ("curve", "both") and len(ordered) >= 2:
                path = QPainterPath(ordered[0])
                for a, b in zip(ordered[1:-1], ordered[2:]):         # curve through the points: each is a control point, curve joins the midpoints
                    path.quadTo(a, QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2))
                path.lineTo(ordered[-1])
                pen = QPen(item["color"], max(2.0, zoom * 2.5))
                pen.setCapStyle(Qt.PenCapStyle.RoundCap)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPath(path)
            if self.style in ("points", "both"):
                radius = max(2.5, zoom * 3.0)
                painter.setPen(QPen(QColor(0, 0, 0, 140), 1))
                painter.setBrush(item["color"])
                for k, point in enumerate(ordered):
                    painter.drawEllipse(point, radius * (1.5 if k == 0 else 1.0), radius * (1.5 if k == 0 else 1.0))   # the first (the tip) is larger
