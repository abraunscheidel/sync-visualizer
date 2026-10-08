"""Layers drawn over the video picture.

A layer is told which moment of the video is on screen (the frame's own time, so it always matches the picture even
when decoding lags behind the playhead) and is asked to paint itself over the image. The first layer is a set of event
badges in a corner; layers that mark where something happened in the picture can follow without changing the view.
"""

from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPainterPath, QPen
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

    def paint(self, painter: QPainter, image_rect: QRectF, image_size: tuple[int, int] = (1, 1)) -> None:
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
