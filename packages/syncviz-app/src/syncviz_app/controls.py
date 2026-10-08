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


def saved_in_workspace(widget):
    """Mark an input control as part of what a workspace saves (see workspace.py and docs/checklists.md).
    Every input control must be marked either this way or with `not_saved`, which a test enforces."""
    widget.setProperty("workspace", "saved")
    return widget


def not_saved(widget, reason: str):
    """Mark an input control as deliberately left out of workspaces, saying why."""
    widget.setProperty("workspace", f"not saved: {reason}")
    return widget


def _plain(value):
    """A value as plain JSON data (numpy scalars from data files become Python ones)."""
    return value.item() if hasattr(value, "item") else value


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
        self.speed = saved_in_workspace(QComboBox())
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
        self._defaults = self.state()

    # -- saved state ---------------------------------------------------------------------
    def state(self) -> dict:
        """The settings this bar holds, as plain data, for saving in a workspace."""
        out = {"speed": self.context.timeline.rate}
        stepper = self.context.stepper
        if stepper is not None:
            out.update({"frames": stepper.count, "frame_defined_by": stepper.reference,
                        "interval_ms": self.interval.value()})
        return out

    def apply_state(self, state: dict) -> None:
        """Set the bar from saved settings; anything missing returns to how the bar started."""
        state = {**self._defaults, **state}
        index = self.speed.findData(float(state["speed"]))
        if index >= 0:
            self.speed.setCurrentIndex(index)
        if self.context.stepper is not None and "frames" in state:
            self.count.setValue(int(state["frames"]))
            self.interval.setValue(float(state["interval_ms"]))
            name = state.get("frame_defined_by")
            if name is not None and self.base.findText(name) >= 0:
                self.base.setCurrentText(name)

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

        self.count = saved_in_workspace(QSpinBox())
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
        self.base = saved_in_workspace(QComboBox())
        for name in stepper.bases:
            self.base.addItem(name)
        self.base.setCurrentText(stepper.reference or "")
        self.base.setToolTip("Which view defines a frame: its next frame or sample, or a fixed interval")
        self.base.currentTextChanged.connect(self._base_changed)
        self.addWidget(self.base)

        self.interval = saved_in_workspace(QDoubleSpinBox())
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
            box = saved_in_workspace(QComboBox())
            box.addItem(ALL, None)
            for value in nav.intervals.unique(attribute):
                box.addItem(str(value), value)
            label = QLabel(f"  {attribute}: ")
            tip = context.explain(attribute, nav.intervals.descriptions.get(attribute, ""))
            if tip:
                label.setToolTip(tip)
                box.setToolTip(tip)
            self.addWidget(label)
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
        self.skip = saved_in_workspace(QCheckBox(f"Skip non-matching {noun}"))
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
        self._defaults = self.state()

    # -- saved state ---------------------------------------------------------------------
    def state(self) -> dict:
        """Which value each filter has (None = all) and whether movement skips what they hide."""
        return {"filters": {a: _plain(box.currentData()) for a, box in self._filters.items()},
                "skip": self.skip.isChecked()}

    def apply_state(self, state: dict) -> None:
        """Set the filters from saved settings; anything missing returns to how the bar started."""
        filters = {**self._defaults["filters"], **state.get("filters", {})}
        self.skip.setChecked(bool(state.get("skip", self._defaults["skip"])))
        for attribute, box in self._filters.items():
            wanted = filters.get(attribute)
            index = 0
            for i in range(box.count()):
                data = box.itemData(i)
                if wanted is not None and data is not None and (data == wanted or str(data) == str(wanted)):
                    index = i
                    break
            box.blockSignals(True)
            box.setCurrentIndex(index)
            box.blockSignals(False)
        self._filters_changed(0)

    def repopulate(self) -> None:
        """Refill the options from the navigator's (new) segments, with every filter back on All.
        A filter whose attribute the new segments lack is disabled."""
        nav = self.context.navigator
        for attribute, box in self._filters.items():
            box.blockSignals(True)
            box.clear()
            box.addItem(ALL, None)
            present = attribute in nav.intervals.attributes
            for value in (nav.intervals.unique(attribute) if present else []):
                box.addItem(str(value), value)
            box.setEnabled(present)
            box.blockSignals(False)
        self._refresh_options()
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
            if attribute not in nav.intervals.attributes:
                continue
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


class CollectionBar(QToolBar):
    """Which collection (recording) is open: previous / next, a picker, and filters on the
    collections' own attributes (which mouse, which day). It works like the segment filters one
    level up. Moving to another collection reloads everything in the window for it."""

    def __init__(self, window, keys: dict[str, str] | None = None) -> None:
        super().__init__("Collections")
        self.window_ = window
        project = window.project
        self.collections = project.collections
        self.keys = {**DEFAULT_KEYS, **(keys or {})}
        self.setMovable(False)
        noun = project.collection_label
        self.addWidget(_caption(noun))
        self.previous = QAction("◀", self)
        self.previous.setShortcut(QKeySequence(self.keys["previous_collection"]))
        self.previous.setToolTip(f"Previous {noun.lower()} ({self.keys['previous_collection']})")
        self.previous.triggered.connect(lambda: self.step(-1))
        self.addAction(self.previous)
        self.picker = not_saved(QComboBox(), "which one is open belongs to the session, not to how the window looks")
        self.picker.setMinimumWidth(260)
        self.picker.setToolTip(f"Choose a {noun.lower()}")
        self.addWidget(self.picker)
        self.next = QAction("▶", self)
        self.next.setShortcut(QKeySequence(self.keys["next_collection"]))
        self.next.setToolTip(f"Next {noun.lower()} ({self.keys['next_collection']})")
        self.next.triggered.connect(lambda: self.step(+1))
        self.addAction(self.next)

        # One filter for each attribute that actually tells collections apart.
        names = sorted({a for c in self.collections for a in c.attributes})
        self._filters: dict[str, QComboBox] = {}
        for attribute in names:
            values = sorted({c.attributes[attribute] for c in self.collections if attribute in c.attributes}, key=str)
            if len(values) < 2:
                continue
            box = saved_in_workspace(QComboBox())
            box.addItem(ALL, None)
            for value in values:
                box.addItem(project.show_attribute(attribute, value), value)
            self.addWidget(QLabel(f"  {project.attribute_names(attribute)[0]}: "))
            self.addWidget(box)
            self._filters[attribute] = box
        self.match_label = QLabel()
        self.addSeparator()
        self.addWidget(self.match_label)
        self._refresh_options()
        self._refresh_picker()
        self.picker.activated.connect(self._picked)
        for box in self._filters.values():
            box.currentIndexChanged.connect(self._filters_changed)

    # -- which collections match ---------------------------------------------------------
    def _selected(self, skip: str | None = None) -> dict:
        return {a: b.currentData() for a, b in self._filters.items() if a != skip and b.currentData() is not None}

    def _matches(self, criteria: dict) -> list[int]:
        return [i for i, c in enumerate(self.collections) if all(c.attributes.get(a) == v for a, v in criteria.items())]

    def matching(self) -> list[int]:
        return self._matches(self._selected())

    def _refresh_options(self) -> None:
        project = self.window_.project
        for attribute, box in self._filters.items():
            rows = [self.collections[i] for i in self._matches(self._selected(skip=attribute))]
            model = box.model()
            for i in range(box.count()):
                value = box.itemData(i)
                n = len(rows) if value is None else sum(1 for c in rows if c.attributes.get(attribute) == value)
                if value is None:                  # "All" counts what the filter chooses between (mice), not the sessions
                    kinds = len({c.attributes[attribute] for c in rows if attribute in c.attributes})
                    one, many = project.attribute_names(attribute)
                    box.setItemText(i, f"{ALL} ({kinds} {one if kinds == 1 else many})")
                else:                              # a value counts the collections it leaves (sessions)
                    noun = (project.collection_label if n == 1 else project.collection_plural).lower()
                    box.setItemText(i, f"{project.show_attribute(attribute, value)} ({n} {noun})")
                model.item(i).setEnabled(n > 0 or i == box.currentIndex())

    def _refresh_picker(self) -> None:
        """List the matching collections, plus the open one if the filters leave it out."""
        active = self.window_.project.active
        shown = sorted(set(self.matching()) | {active})
        self.picker.blockSignals(True)
        self.picker.clear()
        for i in shown:
            self.picker.addItem(self.collections[i].title, i)
        self.picker.setCurrentIndex(shown.index(active))
        self.picker.blockSignals(False)
        total, matching = len(self.collections), len(self.matching())
        self.match_label.setText(f"{matching} of {total} match" if matching != total else f"{total}")
        self.previous.setEnabled(self._neighbor(-1) is not None)
        self.next.setEnabled(self._neighbor(+1) is not None)

    def set_active(self, _index: int) -> None:
        """The window opened another collection: show it."""
        self._refresh_picker()

    # -- moving ----------------------------------------------------------------------------
    def _neighbor(self, direction: int) -> int | None:
        active = self.window_.project.active
        ahead = [i for i in self.matching() if (i > active if direction > 0 else i < active)]
        return (min(ahead) if direction > 0 else max(ahead)) if ahead else None

    def step(self, direction: int) -> None:
        target = self._neighbor(direction)
        if target is not None:
            self.window_.switch_collection(target)

    def _picked(self, row: int) -> None:
        self.window_.switch_collection(int(self.picker.itemData(row)))

    def _filters_changed(self, _index: int) -> None:
        self._refresh_options()
        matches = self.matching()
        active = self.window_.project.active
        if matches and active not in matches:           # keep the open one if it still matches, else move as little as possible
            later = [i for i in matches if i > active]
            self.window_.switch_collection(min(later) if later else max(matches))
        self._refresh_picker()

    # -- saved state -----------------------------------------------------------------------
    def state(self) -> dict:
        return {"filters": {a: _plain(b.currentData()) for a, b in self._filters.items()}}

    def apply_state(self, state: dict) -> None:
        """Set the filters from saved settings without leaving the open collection."""
        wanted = state.get("filters", {})
        for attribute, box in self._filters.items():
            value, index = wanted.get(attribute), 0
            for i in range(box.count()):
                data = box.itemData(i)
                if value is not None and data is not None and (data == value or str(data) == str(value)):
                    index = i
                    break
            box.blockSignals(True)
            box.setCurrentIndex(index)
            box.blockSignals(False)
        self._refresh_options()
        self._refresh_picker()
