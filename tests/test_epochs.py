"""Epochs: counting what falls in each segment, and cutting windows around events (design doc 28.9)."""

import os

import numpy as np
import pytest

from syncviz.epochs import EpochSource, count_in_segments, derive_epochs, epochs_from_sources, measure
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
events:
  Contacts:
    Contact C0: {from: "session:processing/behavior/contacts_C0"}
  Licks:
    Lick left: {from: "session:processing/behavior/licks", member: left}
    Lick right: {from: "session:processing/behavior/licks", member: right}
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


# -- windows around events that last, and several kinds of event at once ----------------------------------------------
CONTACTS = (np.array([3.0, 7.0]), np.array([4.2, 7.1]))                  # a long touch in trial 1, a brief one in trial 2


def test_the_whole_event_is_the_default_thing_to_cut_around():
    epochs = epochs_from_sources([EpochSource(*CONTACTS, before=0.5, after=0.5)])
    assert epochs.starts.tolist() == [2.5, 6.5] and epochs.stops.tolist() == [4.7, 7.6]


def test_only_the_start_or_only_the_end_can_be_the_anchor():
    start = epochs_from_sources([EpochSource(*CONTACTS, before=0.5, after=0.5, anchor="start")])
    assert start.starts.tolist() == [2.5, 6.5] and start.stops.tolist() == [3.5, 7.5]
    end = epochs_from_sources([EpochSource(*CONTACTS, before=0.5, after=0.5, anchor="stop")])
    assert end.starts.tolist() == pytest.approx([3.7, 6.6]) and end.stops.tolist() == pytest.approx([4.7, 7.6])
    with pytest.raises(ValueError):
        epochs_from_sources([EpochSource(*CONTACTS, anchor="middle")])


def test_an_instant_has_no_edges_so_the_anchor_does_not_matter():
    for anchor in ("span", "start", "stop"):
        epochs = epochs_from_sources([EpochSource(np.array([2.0]), None, 0.5, 1.0, anchor)])
        assert epochs.starts.tolist() == [1.5] and epochs.stops.tolist() == [3.0]


def test_each_source_has_its_own_window_and_overlapping_ones_are_merged_so_nothing_is_left_out():
    licks = EpochSource(np.array([3.5, 12.0]), None, before=0.1, after=0.1)
    contacts = EpochSource(*CONTACTS, before=0.5, after=0.5)
    epochs = epochs_from_sources([licks, contacts])
    # the lick's short window at 3.5 lies inside the long contact window, so they become one; the others stand alone
    assert epochs.starts.tolist() == [2.5, 6.5, 11.9] and epochs.stops.tolist() == [4.7, 7.6, 12.1]
    assert epochs.attributes["Events"].tolist() == [2, 1, 1]


def test_inside_a_parent_a_window_follows_where_the_event_starts_and_is_clipped_to_it():
    long_touch = (np.array([4.5]), np.array([6.0]))                       # starts in trial 1, ends in trial 2
    epochs = epochs_from_sources([EpochSource(*long_touch, before=0.5, after=0.5)], parent=TRIALS, parent_name="Trial")
    assert epochs.starts.tolist() == [4.0] and epochs.stops.tolist() == [5.0]        # clipped to trial 1, where it begins
    assert epochs.attributes["Trial"].tolist() == [1]


def test_the_end_anchored_window_belongs_to_the_trial_the_event_ends_in():
    long_touch = (np.array([4.5]), np.array([6.0]))
    epochs = epochs_from_sources([EpochSource(*long_touch, before=0.5, after=0.5, anchor="stop")], parent=TRIALS)
    assert epochs.attributes["number"].tolist() == [2]


# -- clip windows and the windows a user makes --------------------------------------------------------------------------
def test_a_clip_window_comes_from_the_user_else_the_event_else_the_project_else_a_default(window):
    events = window.context.events
    assert events.clip("Lick left") == {"before_ms": 500.0, "after_ms": 500.0, "anchor": "span"}
    events.defaults = {"before_ms": 300, "anchor": "start"}
    assert events.clip("Lick left") == {"before_ms": 300, "after_ms": 500.0, "anchor": "start"}
    events.groups["Licks"]["Lick left"]["clip_ms"] = [100, 900]
    assert events.clip("Lick left")["before_ms"] == 100.0 and events.clip("Lick left")["after_ms"] == 900.0
    events.set_clip("Lick left", 50, 60, "stop")
    assert events.clip("Lick left") == {"before_ms": 50.0, "after_ms": 60.0, "anchor": "stop"}
    with pytest.raises(ValueError):
        events.set_clip("Lick left", 1, 1, "middle")


def test_clip_windows_are_saved_in_the_workspace_and_unknown_events_are_ignored(window):
    events = window.context.events
    events.set_clip("Contact C0", 250, 750, "start")
    saved = window.settings()["events"]
    events.clip_overrides = {}
    events.apply_state({**saved, "clips": {**saved["clips"], "Not an event": {"before_ms": 1, "after_ms": 1, "anchor": "span"}}})
    assert events.clip("Contact C0")["before_ms"] == 250.0 and "Not an event" not in events.clip_overrides


def test_a_derived_segmentation_cuts_around_the_whole_contact_unless_told_otherwise(window):
    specs = {"trials": window.project.segmentation_specs["trials"],
             "whole": {"label": "Whole", "derive": {"from": "session:processing/behavior/contacts_C0", "before_ms": 500,
                                                     "after_ms": 500, "within": "trials"}}}
    whole = segments(specs, "whole", window.context.resources)
    assert whole.starts.tolist() == [2.5] and whole.stops.tolist() == [4.0]           # the contact lasts from 3.0 to 3.5
    specs["onset"] = {"label": "Onset", "derive": {**specs["whole"]["derive"], "anchor": "start"}}
    assert segments(specs, "onset", window.context.resources).stops.tolist() == [3.5]


def test_making_windows_around_events_uses_each_events_own_clip_and_adds_a_segmentation_to_choose(window):
    events = window.context.events
    events.set_clip("Lick left", 100, 100, "span")
    events.set_clip("Contact C0", 500, 500, "span")
    assert window.windows_around(["Lick left", "Contact C0"])
    nav = window.context.navigator
    assert window.active_segmentation == "around: Lick left + Contact C0"
    assert nav.label == "window" and nav.count == 3                          # two short lick windows, then the longer contact one
    assert "around: Lick left + Contact C0" in [window.filter_bar.segmentation.itemData(i)
                                                for i in range(window.filter_bar.segmentation.count())]


def test_windows_around_one_event_are_named_after_it_and_use_its_clip(window):
    window.context.events.set_clip("Contact C0", 250, 250, "span")
    assert window.windows_around(["Contact C0"])
    assert window.context.navigator.label == "Contact C0 window"
    assert window.context.navigator.bounds == pytest.approx((2.75, 3.75))
    window.context.events.set_clip("Contact C0", 1000, 1000, "span")             # asking again with a new clip replaces it
    assert window.windows_around(["Contact C0"])
    assert window.context.navigator.bounds == pytest.approx((2.0, 4.5))


def test_the_windows_a_user_made_come_back_with_the_workspace(window):
    window.windows_around(["Contact C0"])
    saved = window.settings()
    window.set_segmentation("trials")
    del window.project.config["segmentations"]["around: Contact C0"]
    window.context.events.user_segmentations.clear()
    window._apply_settings(saved)
    assert window.active_segmentation == "around: Contact C0" and window.context.navigator.label == "Contact C0 window"


def test_the_commands_are_offered_on_named_events_and_the_clip_dialog_sets_the_clip(window, monkeypatch):
    from syncviz.inspection import Target
    registry = window.context.commands
    contact = Target("session", "processing/behavior/contacts_C0", "intervals", None, "Contact C0")
    other = Target("session", "units", "events", "7", "Unit 7")
    assert {"Make windows around this event", "Clip window…"} <= {c.label for c in registry.for_target(contact)}
    assert not {"Make windows around this event", "Clip window…"} & {c.label for c in registry.for_target(other)}
    from syncviz_app import events_panel

    class Fake:
        def __init__(self, name, clip, parent=None):
            self.seen = (name, clip)

        def exec(self):
            return events_panel.QDialog.DialogCode.Accepted

        def values(self):
            return 10.0, 20.0, "stop"

    monkeypatch.setattr(events_panel, "ClipDialog", Fake)
    registry.run("set_clip", contact)
    assert window.context.events.clip("Contact C0") == {"before_ms": 10.0, "after_ms": 20.0, "anchor": "stop"}
    assert registry.run("windows_around", contact) and window.context.navigator.label == "Contact C0 window"


def test_the_clip_dialog_starts_from_the_current_clip_and_returns_its_values(window):
    from syncviz_app.events_panel import ClipDialog
    dialog = ClipDialog("Contact C0", {"before_ms": 250.0, "after_ms": 750.0, "anchor": "start"})
    assert dialog.values() == (250.0, 750.0, "start")
    dialog.anchor.setCurrentIndex(dialog.anchor.findData("stop"))
    assert dialog.values()[2] == "stop"
