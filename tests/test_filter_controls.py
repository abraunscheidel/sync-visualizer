"""The toolbar's filter dropdowns: counts, dead ends disabled, and the match label."""

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication

from syncviz.core import ActionBus, SegmentNavigator, Timeline
from syncviz.resources import IntervalSeries
from syncviz_app.controls import FilterBar


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def controls(qapp):
    intervals = IntervalSeries(
        starts=[0.0, 10.0, 20.0, 30.0, 40.0, 50.0],
        stops=[9.0, 19.0, 29.0, 39.0, 49.0, 59.0],
        attributes={
            "stimulus": np.array(["convex", "concave", "convex", "concave", "convex", "concave"]),
            "outcome": np.array(["correct", "correct", "correct", "error", "correct", "error"]),
        },
    )
    bus = ActionBus()
    timeline = Timeline(bus, 0.0, 60.0)
    nav = SegmentNavigator(bus, intervals, label="Trial")
    nav.follow(timeline)
    context = SimpleNamespace(bus=bus, timeline=timeline, navigator=nav, notes=[])
    bar = FilterBar(context, ["stimulus", "outcome"])
    return bar, nav


def texts(box):
    return [box.itemText(i) for i in range(box.count())]


def enabled(box):
    return [box.model().item(i).isEnabled() for i in range(box.count())]


def choose(box, value):
    box.setCurrentIndex(next(i for i in range(box.count()) if box.itemData(i) == value))


def test_options_show_how_many_segments_they_would_leave(controls):
    bar, _ = controls

    assert texts(bar._filters["stimulus"]) == ["All (6)", "concave (3)", "convex (3)"]
    assert texts(bar._filters["outcome"]) == ["All (6)", "correct (4)", "error (2)"]
    assert bar.match_label.text() == "6 trials"


def test_options_that_would_match_nothing_are_disabled(controls):
    bar, _ = controls

    choose(bar._filters["outcome"], "error")          # only concave trials have errors

    stimulus = bar._filters["stimulus"]
    assert texts(stimulus) == ["All (2)", "concave (2)", "convex (0)"]
    assert enabled(stimulus) == [True, True, False]


def test_counts_follow_the_other_filters_and_the_match_label_updates(controls):
    bar, nav = controls

    choose(bar._filters["stimulus"], "convex")

    assert nav.count == 3
    assert bar.match_label.text() == "3 of 6 match"
    assert texts(bar._filters["outcome"]) == ["All (3)", "correct (3)", "error (0)"]
    assert enabled(bar._filters["outcome"]) == [True, True, False]


def test_the_selected_option_stays_enabled_and_clearing_restores_everything(controls):
    bar, nav = controls
    choose(bar._filters["stimulus"], "convex")
    choose(bar._filters["outcome"], "correct")
    assert enabled(bar._filters["stimulus"])[bar._filters["stimulus"].currentIndex()]

    choose(bar._filters["stimulus"], None)
    choose(bar._filters["outcome"], None)

    assert nav.count == 6 and not nav.filtered
    assert all(enabled(bar._filters["stimulus"])) and all(enabled(bar._filters["outcome"]))
    assert bar.match_label.text() == "6 trials"


def test_a_dead_end_combination_cannot_be_reached_from_the_ui(controls):
    bar, nav = controls
    choose(bar._filters["stimulus"], "convex")

    outcome = bar._filters["outcome"]
    error_index = next(i for i in range(outcome.count()) if outcome.itemData(i) == "error")

    assert not outcome.model().item(error_index).isEnabled()
    assert nav.count == 3                              # still the previous, consistent filter


def test_the_skip_option_is_a_checkbox_that_is_always_enabled_and_drives_the_navigator(controls):
    bar, nav = controls

    assert bar.skip.isEnabled()                       # even with no filter applied
    bar.skip.setChecked(False)
    assert nav.skip_hidden is False
    bar.skip.setChecked(True)
    assert nav.skip_hidden is True

    choose(bar._filters["stimulus"], "convex")
    assert bar.skip.isEnabled()                       # and still, with one
