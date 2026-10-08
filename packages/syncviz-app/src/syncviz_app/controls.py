"""Playback and segment-navigation controls."""

from __future__ import annotations

from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QLabel, QToolBar

from syncviz.core import SetPlaying, StepSegment
from syncviz_app.context import AppContext

SPEEDS = [0.1, 0.25, 0.5, 1.0, 2.0]
ALL = "All"


class ControlsBar(QToolBar):
    def __init__(self, context: AppContext, filter_attributes: list[str] | None = None) -> None:
        super().__init__("Controls")
        self.context = context
        self.setMovable(False)
        tl = context.timeline

        self.play = QAction("Play", self)
        self.play.setCheckable(True)
        self.play.setShortcut(QKeySequence("Space"))
        self.play.toggled.connect(lambda on: context.bus.publish(SetPlaying(on)))
        self.addAction(self.play)

        nav = context.navigator
        if nav is not None:
            self.addSeparator()
            prev = QAction(f"◀ Previous {nav.label.lower()}", self)
            prev.setShortcut(QKeySequence("Left"))
            prev.triggered.connect(lambda: context.bus.publish(StepSegment(-1)))
            nxt = QAction(f"Next {nav.label.lower()} ▶", self)
            nxt.setShortcut(QKeySequence("Right"))
            nxt.triggered.connect(lambda: context.bus.publish(StepSegment(+1)))
            self.addAction(prev)
            self.segment_label = QLabel()
            self.segment_label.setMinimumWidth(170)
            self.addWidget(self.segment_label)
            self.addAction(nxt)

            self._filters: dict[str, QComboBox] = {}
            for attribute in filter_attributes or []:
                if attribute not in nav.intervals.attributes:
                    context.notes.append(f"filter {attribute!r} is not an attribute of the segments; ignored")
                    continue
                box = QComboBox()
                box.addItem(ALL, None)
                for value in nav.intervals.unique(attribute):
                    box.addItem(str(value), value)
                box.currentIndexChanged.connect(self._filters_changed)
                self.addSeparator()
                self.addWidget(QLabel(f"{attribute}: "))
                self.addWidget(box)
                self._filters[attribute] = box
            nav.subscribe(lambda _n: self._update_segment_label())
            self._update_segment_label()

        self.addSeparator()
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(SPEEDS.index(1.0))
        self.speed.currentIndexChanged.connect(lambda _i: setattr(tl, "rate", self.speed.currentData()))
        self.addWidget(QLabel("Speed: "))
        self.addWidget(self.speed)

        self.time_label = QLabel()
        self.time_label.setMinimumWidth(110)
        self.addSeparator()
        self.addWidget(self.time_label)
        tl.subscribe(self._on_timeline)
        self._on_timeline(tl)

    def _on_timeline(self, tl) -> None:
        if self.play.isChecked() != tl.playing:
            self.play.blockSignals(True)
            self.play.setChecked(tl.playing)
            self.play.blockSignals(False)
        self.play.setText("Pause" if tl.playing else "Play")
        self.time_label.setText(f"{tl.time:10.3f} s")

    def _update_segment_label(self) -> None:
        nav = self.context.navigator
        self.segment_label.setText(f"  {nav.label} {nav.number}   ({nav.position + 1} of {nav.count})  ")

    def _filters_changed(self, _index: int) -> None:
        nav = self.context.navigator
        criteria = {a: box.currentData() for a, box in self._filters.items() if box.currentData() is not None}
        if not criteria:
            nav.clear_filter()
            return
        try:
            nav.filter(**criteria)
        except ValueError:
            # This combination matches nothing. Say so and leave the view as it was.
            self.segment_label.setText(f"  no {nav.label.lower()} matches  ")
