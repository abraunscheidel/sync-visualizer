"""Epochs: counting what falls in each segment, and cutting windows around events (design doc 28.9)."""

import os

import numpy as np
import pytest

from syncviz.epochs import count_in_segments, derive_epochs, measure
from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries

TRIALS = IntervalSeries(np.array([0.0, 5.0, 10.0]), np.array([5.0, 10.0, 15.0]),
                        {"stimulus": np.array(["concave", "convex", "concave"]), "number": np.array([1, 2, 3])},
                        descriptions={"stimulus": "the shape shown"})


# -- counting inside segments -------------------------------------------------------------------------------------
def test_instants_are_counted_in_the_segment_that_holds_them():
    events = EventSeries(times=np.array([1.0, 2.0, 5.0, 12.0]))
    assert count_in_segments(TRIALS, events).tolist() == [2, 1, 1]          # 5.0 belongs to the segment starting at 5.0


def test_an_interval_is_counted_by_overlap_or_by_either_edge():
    contacts = IntervalSeries(np.array([4.5, 6.0, 20.0]), np.array([5.5, 6.5, 21.0]))
    assert count_in_segments(TRIALS, contacts).tolist() == [1, 2, 0]         # the first one straddles trials 1 and 2
    assert count_in_segments(TRIALS, contacts, "start").tolist() == [1, 1, 0]
    assert count_in_segments(TRIALS, contacts, "stop").tolist() == [0, 2, 0]


def test_a_measure_becomes_an_attribute_that_can_be_filtered_by():
    events = EventSeries(times=np.array([1.0, 2.0, 12.0]))
    counted = measure(TRIALS, "Licks", events)
    assert counted.attributes["Licks"].tolist() == [2, 0, 1]
    seen = measure(TRIALS, "Lick", events, as_="presence", labels=("none", "some"), description="Whether the mouse licked.")
    assert seen.attributes["Lick"].tolist() == ["some", "none", "some"]
    assert seen.select(Lick="some").tolist() == [0, 2]                         # the ordinary segment filter works on it
    assert seen.descriptions["Lick"] == "Whether the mouse licked." and seen.descriptions["stimulus"] == "the shape shown"
    assert "Lick" not in TRIALS.attributes                                     # the original is untouched


def test_unknown_edge_or_form_is_refused():
    with pytest.raises(ValueError):
        count_in_segments(TRIALS, IntervalSeries(np.array([1.0]), np.array([2.0])), "middle")
    with pytest.raises(ValueError):
        measure(TRIALS, "x", EventSeries(times=np.array([1.0])), as_="mean")


# -- windows around events ----------------------------------------------------------------------------------------
def test_a_window_surrounds_each_event():
    epochs = derive_epochs([2.0, 8.0], before=0.5, after=1.0)
    assert epochs.starts.tolist() == [1.5, 7.5] and epochs.stops.tolist() == [3.0, 9.0]
    assert epochs.attributes["Events"].tolist() == [1, 1]


def test_windows_that_overlap_are_merged_and_say_how_many_events_they_hold():
    epochs = derive_epochs([2.0, 2.3, 2.5, 8.0], before=0.5, after=0.5)
    assert epochs.starts.tolist() == [1.5, 7.5] and epochs.stops.tolist() == [3.0, 8.5]
    assert epochs.attributes["Events"].tolist() == [3, 1]
    assert len(derive_epochs([2.0, 2.3], before=0.1, after=0.1, merge=False)) == 2


def test_inside_a_parent_a_window_is_clipped_to_it_and_takes_its_attributes():
    epochs = derive_epochs([4.8, 5.1, 7.0], before=0.5, after=0.5, parent=TRIALS, parent_name="Trial")
    # 4.8 is in trial 1 (clipped to end at 5.0); 5.1 and 7.0 are in trial 2 (5.1's window is clipped to start at 5.0)
    assert epochs.starts.tolist() == [4.3, 5.0, 6.5] and epochs.stops.tolist() == [5.0, 5.6, 7.5]
    assert epochs.attributes["stimulus"].tolist() == ["concave", "convex", "convex"]
    assert epochs.attributes["Trial"].tolist() == [1, 2, 2]
    assert epochs.descriptions["stimulus"] == "the shape shown"


def test_events_outside_every_parent_segment_get_no_window():
    epochs = derive_epochs([-3.0, 7.0, 40.0], before=0.1, after=0.1, parent=TRIALS)
    assert epochs.attributes["number"].tolist() == [2]


def test_windows_never_overlap_so_the_navigator_can_use_them():
    rng = np.random.default_rng(0)
    epochs = derive_epochs(rng.uniform(0, 15, 300), before=0.3, after=0.3, parent=TRIALS)
    assert np.all(epochs.starts[1:] >= epochs.stops[:-1])
    for i in range(len(epochs)):
        assert epochs.index_at(float(epochs.starts[i])) == i


def test_a_negative_window_is_refused():
    with pytest.raises(ValueError):
        derive_epochs([1.0], before=-0.1, after=0.1)


# -- in a project ----------------------------------------------------------------------------------------------------
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("pynwb")

from PySide6.QtWidgets import QApplication

from syncviz_app.app import build_window
from syncviz_app.segmentation import segments

from test_descriptions import _write_nwb


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, qapp):
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text("""
name: epochs
sources:
  session: {type: nwb, path: session.nwb}
glossary:
  Contact: "Whether a whisker touched the object during the trial."
segmentations:
  trials:
    label: Trial
    from: "session:intervals/trials"
    filters: [stimulus, Contact, Licks]
    measures:
      Contact: {from: "session:processing/behavior/contacts_C0", as: presence, labels: [no touch, touch]}
      Licks: {from: "session:processing/behavior/licks", member: left}
  touches:
    label: Touch
    derive: {from: "session:processing/behavior/contacts_C0", edge: start, before_ms: 500, after_ms: 500, within: trials}
    filters: [stimulus]
views:
  - type: tracks
    title: Trials
    rows: [{name: Trials, kind: intervals, from: "session:intervals/trials"}]
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml", use_workspace=False)
    w.show()
    yield w
    w.close()


def test_a_measure_from_events_is_a_filter_like_any_other(window):
    bar, nav = window.filter_bar, window.context.navigator
    assert "Contact" in bar._filters and "Licks" in bar._filters
    assert [bar._filters["Contact"].itemText(i) for i in range(3)] == ["All (2)", "no touch (1)", "touch (1)"]
    box = bar._filters["Contact"]
    box.setCurrentIndex(box.findData("touch"))
    assert nav.match_count == 1 and nav.number == 1                      # the trial with the contact (3.0 to 3.5)
    assert "touched the object" in box.toolTip()                          # described by the project's glossary


def test_measures_combine_with_the_other_filters(window):
    bar, nav = window.filter_bar, window.context.navigator
    licks = bar._filters["Licks"]
    licks.setCurrentIndex(licks.findData(2))                           # two left licks: only trial 1
    assert nav.match_count == 1
    contact = bar._filters["Contact"]
    assert [contact.itemText(i) for i in range(3)] == ["All (1)", "no touch (0)", "touch (1)"]
    assert not contact.model().item(contact.findData("no touch")).isEnabled()      # would leave nothing


def test_a_derived_segmentation_cuts_windows_around_the_events_inside_the_trials(window):
    project = window.project
    touches = segments(project.segmentation_specs, "touches", window.context.resources)
    assert touches.starts.tolist() == [2.5] and touches.stops.tolist() == [3.5]       # contact starts at 3.0
    assert touches.attributes["stimulus"].tolist() == ["concave"] and touches.attributes["Trial"].tolist() == [1]
    assert segments(project.segmentation_specs, "touches", window.context.resources) is touches    # built once


def test_segmentations_that_refer_to_each_other_in_a_circle_are_refused(window):
    specs = {"a": {"derive": {"from": "session:processing/behavior/contacts_C0", "within": "b"}},
             "b": {"derive": {"from": "session:processing/behavior/contacts_C0", "within": "a"}}}
    with pytest.raises(ValueError, match="circle"):
        segments(specs, "a", window.context.resources)


# -- choosing which segmentation to move between -------------------------------------------------------------------
def test_the_user_can_switch_between_trials_and_windows_around_contacts(window):
    from syncviz.core import Seek
    bar, nav = window.filter_bar, window.context.navigator
    assert [bar.segmentation.itemText(i) for i in range(bar.segmentation.count())] == ["Trials", "Touchs"]
    window.context.bus.publish(Seek(3.2))
    assert nav.label == "Trial" and nav.count == 2
    assert window.set_segmentation("touches")
    assert nav.label == "Touch" and nav.count == 1 and window.context.timeline.time == pytest.approx(3.2)   # still inside it
    assert list(bar._filters) == ["stimulus"] and bar.active == "touches"                             # its own filters
    assert window.navigation.segment_label.text().strip().startswith("Touch 1")
    assert "touch" in window.navigation.next_segment.toolTip().lower()
    assert window.set_segmentation("trials")
    assert nav.label == "Trial" and nav.number == 1 and list(bar._filters) == ["stimulus", "Contact", "Licks"]


def test_switching_to_windows_the_playhead_is_outside_of_moves_to_the_nearest_one(window):
    from syncviz.core import Seek
    window.context.bus.publish(Seek(8.0))                                   # trial 2: there is no contact in it
    window.set_segmentation("touches")
    assert window.context.timeline.time == pytest.approx(2.5)                # the only window, which is before: the last one


def test_windows_become_the_only_places_the_playhead_can_go(window):
    window.set_segmentation("touches")
    assert window.context.timeline.allows(3.0) and not window.context.timeline.allows(8.0)
    window.set_segmentation("trials")
    assert window.context.timeline.allows(8.0)


def test_the_chosen_segmentation_is_saved_in_the_workspace_and_restored(window):
    window.set_segmentation("touches")
    saved = window.settings()["filters"]
    assert saved["segmentation"] == "touches"
    window.set_segmentation("trials")
    window.filter_bar.apply_state(saved)
    assert window.active_segmentation == "touches" and window.context.navigator.label == "Touch"


def test_a_segmentation_that_cannot_be_built_leaves_everything_as_it_was(window):
    window.project.config["segmentations"]["bad"] = {"label": "Bad", "derive": {"from": "session:processing/behavior/none"}}
    assert not window.set_segmentation("bad")
    assert window.active_segmentation == "trials" and window.context.navigator.label == "Trial"
    assert not window.set_segmentation("missing")
    box = window.filter_bar.segmentation
    window.filter_bar._segmentation_chosen(1)                                # choosing it in the box also works...
    assert window.active_segmentation == "touches"


def test_yaml_turns_unquoted_yes_and_no_into_booleans_so_the_labels_are_checked(window):
    specs = {"checked": {**window.project.segmentation_specs["trials"],
                        "measures": {"Contact": {"from": "session:processing/behavior/contacts_C0", "as": "presence",
                                                 "labels": [False, True]}}}}
    with pytest.raises(ValueError, match="quotes"):
        segments(specs, "checked", window.context.resources)
