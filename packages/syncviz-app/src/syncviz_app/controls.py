"""The window's fixed controls, in two rows.

* NavigationBar: play, and two clearly separate ways of moving the playhead: by segment
  (a "trial"), and by frame, where a frame is whatever the user has defined it to be.
* FilterBar: which segments are shown, and whether playback skips the ones that are not.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QCheckBox, QComboBox, QDoubleSpinBox, QLabel, QSpinBox, QToolBar

from syncviz.core import FixedStep, SetPlaying, StepSegment, StepTime
from syncviz.core.stepping import FIXED_INTERVAL
from syncviz_app.context import AppContext
from syncviz_app.keys import DEFAULT_KEYS

SPEEDS = [0.1, 0.25, 0.5, 1.0, 2.0]
TIME_LABEL_INTERVAL_MS = 50
ALL = "All"


def _caption(text: str) -> QLabel:
    """A bold heading for a group of controls."""
    label = QLabel(text)
    label.setStyleSheet("font-weight: 600; padding: 0 6px;")
    return label


class NavigationBar(QToolBar):
    def __init__(self, context: AppContext, keys: dict[str, str] | None = None) -> None:
        super().__init__("Navigation")
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
            self._add_segment_group(nav)
        if context.stepper is not None:
            self._add_frame_group(context.stepper)

        self.addSeparator()
        self.speed = QComboBox()
        for s in SPEEDS:
            self.speed.addItem(f"{s:g}×", s)
        self.speed.setCurrentIndex(SPEEDS.index(1.0))
        self.speed.currentIndexChanged.connect(lambda _i: setattr(tl, "rate", self.speed.currentData()))
        self.addWidget(_caption("Speed"))
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

    # -- moving between segments ---------------------------------------------------------
    def _add_segment_group(self, nav) -> None:
        bus = self.context.bus
        noun = nav.label.lower()
        self.addSeparator()
        self.addWidget(_caption("Segment"))          # the section is generic; its items use the configured name
        self.previous_segment = QAction("◀", self)
        self.previous_segment.setShortcut(QKeySequence(self.keys["previous_segment"]))
        self.previous_segment.setToolTip(f"Previous {noun} ({self.keys['previous_segment']})")
        self.previous_segment.triggered.connect(lambda: bus.publish(StepSegment(-1)))
        self.addAction(self.previous_segment)
        self.segment_label = QLabel()
        self.segment_label.setMinimumWidth(150)
        self.addWidget(self.segment_label)
        self.next_segment = QAction("▶", self)
        self.next_segment.setShortcut(QKeySequence(self.keys["next_segment"]))
        self.next_segment.setToolTip(f"Next {noun} ({self.keys['next_segment']})")
        self.next_segment.triggered.connect(lambda: bus.publish(StepSegment(+1)))
        self.addAction(self.next_segment)
        nav.subscribe(lambda _n: self._update_segment_label())
        self._update_segment_label()

    def _update_segment_label(self) -> None:
        nav = self.context.navigator
        text = f"  {nav.label} {nav.number}   ({nav.position + 1} of {nav.count})"
        if nav.filtered and not nav.matches:
            text += "   not in filter"            # only possible while movement is not restricted to matches
        self.segment_label.setText(text + "  ")

    # -- moving by frame -----------------------------------------------------------------
    def _add_frame_group(self, stepper) -> None:
        """A "frame" is one tick of a time base the user picks: a video's frames, a signal's
        samples, or a fixed interval. It is always called a frame here; what defines it is
        the selector next to it."""
        bus = self.context.bus
        self.addSeparator()
        self.addWidget(_caption("Frame"))
        self.step_back = QAction("◀", self)
        self.step_back.setShortcut(QKeySequence(self.keys["step_back"]))
        self.step_back.setToolTip(f"Back by the number of frames shown ({self.keys['step_back']})")
        self.step_back.triggered.connect(lambda: bus.publish(StepTime(-1)))
        self.addAction(self.step_back)

        self.count = QSpinBox()
        self.count.setRange(1, 100000)
        self.count.setValue(stepper.count)
        self.count.setSuffix(" frames")
        self.count.setMinimumWidth(110)
        self.count.setToolTip("How many frames each step moves")
        self.count.valueChanged.connect(lambda v: setattr(stepper, "count", v))
        self.addWidget(self.count)

        self.step_forward = QAction("▶", self)
        self.step_forward.setShortcut(QKeySequence(self.keys["step_forward"]))
        self.step_forward.setToolTip(f"Forward by the number of frames shown ({self.keys['step_forward']})")
        self.step_forward.triggered.connect(lambda: bus.publish(StepTime(+1)))
        self.addAction(self.step_forward)

        self.addWidget(QLabel("  defined by "))
        self.base = QComboBox()
        for name in stepper.bases:
            self.base.addItem(name)
        self.base.setCurrentText(stepper.reference or "")
        self.base.setToolTip("Which view defines a frame: its next frame or sample, or a fixed interval")
        self.base.currentTextChanged.connect(self._base_changed)
        self.addWidget(self.base)

        self.interval = QDoubleSpinBox()
        self.interval.setRange(0.01, 600000.0)
        self.interval.setDecimals(2)
        self.interval.setSuffix(" ms")
        fixed = stepper.bases.get(FIXED_INTERVAL)
        self.interval.setValue(fixed.interval * 1000.0 if isinstance(fixed, FixedStep) else 10.0)
        self.interval.valueChanged.connect(self._interval_changed)
        self._interval_action = self.addWidget(self.interval)
        self._interval_action.setVisible(self.base.currentText() == FIXED_INTERVAL)

        # Spin boxes keep the keyboard once clicked, which would swallow the step shortcuts.
        for box in (self.count, self.interval):
            box.editingFinished.connect(box.clearFocus)

    def refresh_bases(self) -> None:
        """Re-list what can define a frame, after views have been added or removed."""
        stepper = self.context.stepper
        if stepper is None:
            return
        self.base.blockSignals(True)
        self.base.clear()
        for name in stepper.bases:
            self.base.addItem(name)
        self.base.setCurrentText(stepper.reference or "")
        self.base.blockSignals(False)
        self._interval_action.setVisible(self.base.currentText() == FIXED_INTERVAL)

    def _base_changed(self, name: str) -> None:
        self.context.stepper.reference = name
        self._interval_action.setVisible(name == FIXED_INTERVAL)

    def _interval_changed(self, milliseconds: float) -> None:
        self.context.stepper.bases[FIXED_INTERVAL] = FixedStep(milliseconds / 1000.0)

    # -- time display --------------------------------------------------------------------
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


class FilterBar(QToolBar):
    """Which segments are shown, how many match, and whether playback skips the rest."""

    def __init__(self, context: AppContext, filter_attributes: list[str] | None = None) -> None:
        super().__init__("Filters")
        self.context = context
        self.setMovable(False)
        nav = context.navigator
        noun = nav.plural.lower()

        self.addWidget(_caption("Filter"))
        self._filters: dict[str, QComboBox] = {}
        for attribute in filter_attributes or []:
            if attribute not in nav.intervals.attributes:
                context.notes.append(f"filter {attribute!r} is not an attribute of the segments; ignored")
                continue
            box = QComboBox()
            box.addItem(ALL, None)
            for value in nav.intervals.unique(attribute):
                box.addItem(str(value), value)
            self.addWidget(QLabel(f"  {attribute}: "))
            self.addWidget(box)
            self._filters[attribute] = box
        self._refresh_options()                       # counts in the option text; dead ends disabled
        for box in self._filters.values():
            box.currentIndexChanged.connect(self._filters_changed)

        self.match_label = QLabel()
        self.match_label.setMinimumWidth(110)
        self.addSeparator()
        self.addWidget(self.match_label)

        # The filter says which segments match; this decides whether moving is restricted to them.
        self.addSeparator()
        self.skip = QCheckBox(f"Skip non-matching {noun}")
        self.skip.setChecked(nav.skip_hidden)
        self.skip.setToolTip(
            f"On: every way of moving (previous/next, stepping, playback, clicking the timeline) stays\n"
            f"within the {noun} that match the filter. Off: they visit every one, and the filter only\n"
            f"highlights the matches."
        )
        self.skip.toggled.connect(lambda on: setattr(nav, "skip_hidden", on))
        self.addWidget(self.skip)

        nav.subscribe(lambda _n: self._update_match_label())
        self._update_match_label()

    def _update_match_label(self) -> None:
        nav = self.context.navigator
        total = len(nav.intervals)
        noun = nav.plural.lower()
        self.match_label.setText(f"{nav.match_count} of {total} match" if nav.filtered else f"{total} {noun}")

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
            self.match_label.setText(f"no {nav.label.lower()} matches")
