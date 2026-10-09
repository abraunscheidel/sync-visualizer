"""The event tracker: tiles that light when the events the viewer tracks happen (design doc 28.11).

Which events are tracked is shared state (`EventConditions.tracked`, kept in the workspace, empty unless the project names a `track:`
list); this view only presents them, so it has a display delay like any view and there can be more than one. Tiles are grouped by the
scope the project gives them. Below them, collapsed to begin with, are the rest of the events the project names as grayed tiles that
do not light: they can be selected and filtered by like any other, and double-clicking one tracks it. A tile also shows how the event is
being used as a filter (yes, no, or clips).
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from syncviz.resources import EventSeries
from syncviz_app.views.base import Candidate, View, ViewSetting
from syncviz_app.views.rows import glow_after_events, glow_during_intervals

DEFAULT_DECAY_S = 0.25
TILE_MIN_W, TILE_H, GAP, HEADER_H = 120, 40, 6, 24
UNLIT_ALPHA, LIT_ALPHA = 30, 255
BADGE_COLOURS = {"yes": "#3a9d5d", "no": "#c0392b", "clips": "#4fa3e0"}


class _Tile:
    __slots__ = ("name", "rect", "tracked")

    def __init__(self, name: str, rect: QRectF, tracked: bool) -> None:
        self.name, self.rect, self.tracked = name, rect, tracked


class _Canvas(QWidget):
    """Draws the headings and tiles. It does not own any state: the view tells it what to show."""

    def __init__(self, view: "EventTrackerView") -> None:
        super().__init__()
        self.view = view
        self.tiles: list[_Tile] = []
        self.headings: list[tuple[str, QRectF, bool]] = []      # text, where, whether clicking it opens or closes the others
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setMouseTracking(True)

    # -- layout: headings and rows of tiles, top to bottom --------------------------------------------
    def relayout(self) -> None:
        view, width = self.view, max(self.width(), TILE_MIN_W + 2 * GAP)
        columns = max(1, int((width - GAP) // (TILE_MIN_W + GAP)))
        tile_w = (width - GAP * (columns + 1)) / columns
        self.tiles, self.headings = [], []
        y = float(GAP)

        def add_group(title: str, names: list[str], tracked: bool, opens: bool = False) -> None:
            nonlocal y
            self.headings.append((title, QRectF(GAP, y, width - 2 * GAP, HEADER_H), opens))
            y += HEADER_H
            for i, name in enumerate(names):
                row, col = divmod(i, columns)
                self.tiles.append(_Tile(name, QRectF(GAP + col * (tile_w + GAP), y + row * (TILE_H + GAP), tile_w, TILE_H), tracked))
            y += -(-len(names) // columns) * (TILE_H + GAP) + GAP

        tracked_by_scope = view.tracked_by_scope()
        for scope, names in tracked_by_scope.items():
            add_group(scope, names, True)
        others = view.untracked()
        if others:
            add_group(f"{'▾' if view.show_others else '▸'} Other events ({len(others)})",
                      others if view.show_others else [], False, opens=True)
        elif not tracked_by_scope:
            self.headings.append(("No events to show. The project names none.", QRectF(GAP, y, width - 2 * GAP, HEADER_H), False))
            y += HEADER_H
        self.setFixedHeight(int(y + GAP))

    def resizeEvent(self, event) -> None:
        self.relayout()
        super().resizeEvent(event)

    def tile_at(self, point) -> _Tile | None:
        return next((t for t in self.tiles if t.rect.contains(QPointF(point))), None)

    def heading_at(self, point):
        return next((h for h in self.headings if h[1].contains(QPointF(point))), None)

    # -- painting ---------------------------------------------------------------------------------------
    def paintEvent(self, _event) -> None:
        view = self.view
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self.palette()
        dark, bright, lit = (pal.color(pal.ColorRole.WindowText), pal.color(pal.ColorRole.HighlightedText),
                             pal.color(pal.ColorRole.Highlight))
        heading_font = QFont(p.font())
        heading_font.setBold(True)
        for text, rect, opens in self.headings:
            p.setFont(heading_font)
            p.setPen(QColor(dark.red(), dark.green(), dark.blue(), 170))
            p.drawText(rect, Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        for tile in self.tiles:
            level = view.level_of(tile.name) if tile.tracked else 0.0
            has_data = view.has_data(tile.name)
            fill = QColor(lit if tile.tracked else dark)
            fill.setAlpha(int(UNLIT_ALPHA + (LIT_ALPHA - UNLIT_ALPHA) * level) if tile.tracked else 14)
            outline = QColor(dark)
            outline.setAlpha(70 if tile.tracked else 50)
            p.setPen(QPen(outline, 1, Qt.PenStyle.SolidLine if tile.tracked else Qt.PenStyle.DashLine))
            p.setBrush(fill)
            p.drawRoundedRect(tile.rect, 6, 6)
            if view.is_selected(view.events.target_of(tile.name)):
                p.setPen(QPen(lit.lighter(130), 3))
                p.setBrush(Qt.BrushStyle.NoBrush)
                p.drawRoundedRect(tile.rect.adjusted(1, 1, -1, -1), 6, 6)
            alpha = 255 if tile.tracked and has_data else 120
            colour = QColor(int(dark.red() + (bright.red() - dark.red()) * level), int(dark.green() + (bright.green() - dark.green()) * level),
                            int(dark.blue() + (bright.blue() - dark.blue()) * level), alpha)
            font = QFont(p.font())
            font.setBold(level > 0.5)
            p.setFont(font)
            p.setPen(colour)
            state = view.events.filter_state(tile.name)
            reserve = 44 if state else 8
            text = QFontMetrics(font).elidedText(tile.name, Qt.TextElideMode.ElideRight, int(tile.rect.width() - reserve))
            p.drawText(tile.rect.adjusted(8, 0, -8, 0), Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
            if state:
                word, on = state
                badge = QColor(BADGE_COLOURS[word])
                badge.setAlpha(255 if on else 110)
                small = QFont(p.font())
                small.setBold(True)
                small.setPointSizeF(max(small.pointSizeF() * 0.8, 6.5))
                p.setFont(small)
                box = QRectF(tile.rect.right() - 42, tile.rect.top() + 5, 36, 15)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(badge)
                p.drawRoundedRect(box, 4, 4)
                p.setPen(QColor("white"))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, word if on else f"{word}·off")
        p.end()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.view.pressed(event.position().toPoint(), False, event.modifiers())

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.view.pressed(event.position().toPoint(), True, event.modifiers())


class EventTrackerView(View):
    type_name = "events"
    display_name = "Event tracker"

    @classmethod
    def candidates(cls, catalog):
        return [Candidate("Event tracker", {"type": cls.type_name, "title": "Event tracker"},
                          "Tiles that light when the events you track happen. Track events from the list of the project's events "
                          "below the tiles, or from an event's menu.")]

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        if context.events is None:
            raise ValueError("the event tracker needs the project's events")
        self.events = context.events
        self.decay = float(spec.get("decay", DEFAULT_DECAY_S))
        if self.decay <= 0:
            raise ValueError("decay must be positive")
        self._default_show_others = bool(spec.get("show_others", False))
        self.show_others = self._default_show_others
        self._data: dict[str, object | None] = {}                # event name -> its data in this recording, or None if it has none
        self._levels: dict[str, float] = {}
        self.canvas = _Canvas(self)
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setWidget(self.canvas)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(area)
        self.enable_hover(self.canvas)
        self.events.subscribe(self._changed)
        self.canvas.relayout()

    # -- what is shown ----------------------------------------------------------------------------------------
    def tracked_by_scope(self) -> dict[str, list[str]]:
        out = {}
        for scope, events in self.events.groups.items():
            names = [n for n in events if self.events.is_tracked(n)]
            if names:
                out[scope] = names
        return out

    def untracked(self) -> list[str]:
        return [n for n in self.events.names() if not self.events.is_tracked(n)]

    def _changed(self) -> None:
        self.canvas.relayout()
        self.canvas.update()

    def _load(self, name: str):
        if name not in self._data:
            try:
                self._data[name] = self.events.find(name)
            except Exception:                                    # the recording lacks it
                self._data[name] = None
        return self._data[name]

    def has_data(self, name: str) -> bool:
        return self._load(name) is not None

    def level_of(self, name: str) -> float:
        return self._levels.get(name, 0.0)

    def levels_at(self, time: float) -> dict[str, float]:
        out = {}
        for name in self.events.tracked:
            data = self._load(name)
            if data is None:
                continue
            out[name] = (glow_after_events(data.times, time, self.decay) if isinstance(data, EventSeries)
                         else glow_during_intervals(data.starts, data.stops, time, self.decay))
        return out

    def refresh(self, time: float) -> None:
        levels = self.levels_at(time)
        if levels != self._levels:
            self._levels = levels
            self.canvas.update()

    # -- pointing and clicking ------------------------------------------------------------------------------
    def target_at(self, pos):
        tile = self.canvas.tile_at(self.canvas.mapFrom(self, pos))
        return None if tile is None else self.events.target_of(tile.name)

    def selectable_targets(self):
        return [self.events.target_of(t.name) for t in self.canvas.tiles]

    def selection_changed(self) -> None:
        self.canvas.update()

    def pressed(self, point, double: bool, modifiers) -> None:
        heading = self.canvas.heading_at(point)
        if heading is not None and heading[2] and not double:       # the "Other events" heading opens and closes the list
            self._set_show_others(not self.show_others)
            return
        tile = self.canvas.tile_at(point)
        if tile is not None:
            self.click_at(self.events.target_of(tile.name), modifiers, double)

    def _set_show_others(self, value: bool) -> None:
        hook = self.context.set_view_setting                     # so the choice is kept with the workspace
        if hook is not None:
            hook(self, "others", value)
        else:
            self.apply_setting("others", value)

    # -- settings, kept with the workspace ---------------------------------------------------------------------
    def settings(self):
        return [ViewSetting("others", "Show the other events", "toggle", self.show_others,
                            description="List the events the project names that are not being tracked, as grayed tiles you can "
                                        "select and filter by.")]

    def apply_setting(self, key: str, value) -> None:
        if key == "others":
            self.show_others = bool(value)
            self.canvas.relayout()
            self.canvas.update()

    def reset_settings(self) -> None:
        self.apply_setting("others", self._default_show_others)
