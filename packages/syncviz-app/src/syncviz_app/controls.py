"""Playback and segment-navigation controls."""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QToolBar

from syncviz.core import FixedStep, SetPlaying, StepSegment, StepTime
from syncviz.core.stepping import FIXED_INTERVAL
from syncviz_app.context import AppContext
from syncviz_app.keys import DEFAULT_KEYS

SPEEDS = [0.1, 0.25, 0.5, 1.0, 2.0]
TIME_LABEL_INTERVAL_MS = 50
ALL = "All"


class ControlsBar(QToolBar):
    def __init__(
        self,
        context: AppContext,
        filter_attributes: list[str] | None = None,
        keys: dict[str, str] | None = None,
    ) -> None:
        super().__init__("Controls")
        self.context = context
        self.keys = {**DEFAULT_KEYS, **(keys or {})}
        self.setMovable(False)
        tl = context.timeline

        self.play = QAction("Play", self)
        self.play.setCheckable(True)
        self.play.setShortcut(QKeySequence(self.keys["play_pause"]))
        self.play.toggled.connect(lambda on: context.bus.publish(SetPlaying(on)))
        self.addAction(self.play)

        nav = context.navigator
        if nav is not None:
            self.addSeparator()
            prev = QAction(f"◀ Previous {nav.label.lower()}", self)
            prev.setShortcut(QKeySequence(self.keys["previous_segment"]))
            prev.setToolTip(f"Previous {nav.label.lower()} ({self.keys['previous_segment']})")
            prev.triggered.connect(lambda: context.bus.publish(StepSegment(-1)))
            nxt = QAction(f"Next {nav.label.lower()} ▶", self)
            nxt.setShortcut(QKeySequence(self.keys["next_segment"]))
            nxt.setToolTip(f"Next {nav.label.lower()} ({self.keys['next_segment']})")
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
                self.addSeparator()
                self.addWidget(QLabel(f"{attribute}: "))
                self.addWidget(box)
                self._filters[attribute] = box
            self._refresh_options()                       # counts in the option text; dead ends disabled
            for box in self._filters.values():
                box.currentIndexChanged.connect(self._filters_changed)
            self.match_label = QLabel()
            self.match_label.setMinimumWidth(110)
            self.addSeparator()
            self.addWidget(self.match_label)
            # With a filter active, playback normally jumps over segments that don't match it.
            # Unticking this plays straight through everything instead.
            self.addSeparator()
            self.skip = QAction(f"Skip non-matching {nav.label.lower()}s", self)
            self.skip.setCheckable(True)
            self.skip.setChecked(nav.skip_hidden)
            self.skip.setToolTip("While a filter is active, playback skips segments that don't match it")
            self.skip.toggled.connect(lambda on: setattr(nav, "skip_hidden", on))
            self.addAction(self.skip)
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
        # While playing the time changes every tick; the label only needs to keep up with the eye.
        self._label_timer = QTimer(self)
        self._label_timer.setInterval(TIME_LABEL_INTERVAL_MS)
        self._label_timer.timeout.connect(self._refresh_time_label)
        tl.subscribe(self._on_timeline)
        self._on_timeline(tl)

    def _refresh_time_label(self) -> None:
        self.time_label.setText(f"{self.context.timeline.time:10.3f} s")

    def _on_timeline(self, tl) -> None:
        if self.play.isChecked() != tl.playing:
            self.play.blockSignals(True)
            self.play.setChecked(tl.playing)
            self.play.blockSignals(False)
        self.play.setText("Pause" if tl.playing else "Play")
        if tl.playing:
            if not self._label_timer.isActive():
                self._label_timer.start()
        else:
            self._label_timer.stop()
            self._refresh_time_label()              # seeks and pauses show immediately

    def _update_segment_label(self) -> None:
        nav = self.context.navigator
        self.segment_label.setText(f"  {nav.label} {nav.number}   ({nav.position + 1} of {nav.count})  ")
        self.skip.setEnabled(nav.filtered)                  # nothing to skip without a filter
        total = len(nav.intervals)
        noun = f"{nav.label.lower()}s"
        self.match_label.setText(f"{nav.count} of {total} match" if nav.filtered else f"{total} {noun}")

    def _selected(self, skip: str | None = None) -> dict:
        return {a: box.currentData() for a, box in self._filters.items()
                if a != skip and box.currentData() is not None}

    def _refresh_options(self) -> None:
        """Show how many segments each option would leave, and disable options that leave none.

        Each option is counted against the *other* filters' current choices, so the options
        always describe what clicking them would do. The selected option stays enabled.
        """
        nav = self.context.navigator
        for attribute, box in self._filters.items():
            counts = nav.facet_counts(attribute, **self._selected(skip=attribute))
            model = box.model()
            for i in range(box.count()):
                value = box.itemData(i)
                n = sum(counts.values()) if value is None else counts.get(value, 0)
                box.setItemText(i, f"{ALL} ({n})" if value is None else f"{value} ({n})")
                model.item(i).setEnabled(n > 0 or i == box.currentIndex())

    def _filters_changed(self, _index: int) -> None:
        nav = self.context.navigator
        criteria = self._selected()
        self._refresh_options()
        if not criteria:
            nav.clear_filter()
            return
        try:
            nav.filter(**criteria)
        except ValueError:
            # Unreachable from the UI, since options that match nothing are disabled.
            self.segment_label.setText(f"  no {nav.label.lower()} matches  ")


class StepBar(QToolBar):
    """Steps the playhead by one tick of a time base the user chooses.

    A tick is the next frame or sample of a view's data (for example the video's frames), or a
    fixed interval. Several views can offer a grid; the user picks which one defines the step.
    """

    def __init__(self, context: AppContext, keys: dict[str, str] | None = None) -> None:
        super().__init__("Stepping")
        self.context = context
        stepper = context.stepper
        keys = {**DEFAULT_KEYS, **(keys or {})}
        self.setMovable(False)

        back = QAction("◀ Step", self)
        back.setShortcut(QKeySequence(keys["step_back"]))
        back.setToolTip(f"Step back ({keys['step_back']})")
        back.triggered.connect(lambda: context.bus.publish(StepTime(-1)))
        forward = QAction("Step ▶", self)
        forward.setShortcut(QKeySequence(keys["step_forward"]))
        forward.setToolTip(f"Step forward ({keys['step_forward']})")
        forward.triggered.connect(lambda: context.bus.publish(StepTime(+1)))

        self.count = QSpinBox()
        self.count.setRange(1, 100000)
        self.count.setValue(stepper.count)
        self.count.setPrefix("× ")
        self.count.setToolTip("How many steps each press moves")
        self.count.valueChanged.connect(lambda v: setattr(stepper, "count", v))

        self.base = QComboBox()
        for name in stepper.bases:
            self.base.addItem(name)
        self.base.setCurrentText(stepper.reference or "")
        self.base.setToolTip("What one step means: the next frame or sample of this view's data, or a fixed interval")
        self.base.currentTextChanged.connect(self._base_changed)

        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 600000.0)
        self.interval.setDecimals(2)
        self.interval.setSuffix(" ms")
        fixed = stepper.bases.get(FIXED_INTERVAL)
        self.interval.setValue(fixed.interval * 1000.0 if isinstance(fixed, FixedStep) else 10.0)
        self.interval.valueChanged.connect(self._interval_changed)

        # Spin boxes keep the keyboard once clicked, which would swallow the step shortcuts.
        for box in (self.count, self.interval):
            box.editingFinished.connect(box.clearFocus)

        self.addAction(back)
        self.addWidget(self.count)
        self.addAction(forward)
        self.addSeparator()
        self.addWidget(QLabel("Step by: "))
        self.addWidget(self.base)
        self._interval_action = self.addWidget(self.interval)
        self._interval_action.setVisible(self.base.currentText() == FIXED_INTERVAL)

    def _base_changed(self, name: str) -> None:
        self.context.stepper.reference = name
        self._interval_action.setVisible(name == FIXED_INTERVAL)

    def _interval_changed(self, milliseconds: float) -> None:
        self.context.stepper.bases[FIXED_INTERVAL] = FixedStep(milliseconds / 1000.0)
