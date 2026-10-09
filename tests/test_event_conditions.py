"""Event conditions: keep the segments where chosen events did, or did not, happen (design doc 28.10)."""

import numpy as np
import pytest

from syncviz.conditions import Condition, condition_mask, conditions_mask
from syncviz.core import ActionBus, SegmentNavigator
from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries

from test_epochs import TRIALS, qapp, window  # noqa: F401  (fixtures)

LICKS = EventSeries(times=np.array([1.0, 2.0, 12.0]))
TOUCHES = IntervalSeries(np.array([4.5, 6.0]), np.array([5.5, 6.5]))
FIND = {"lick": LICKS, "touch": TOUCHES}.__getitem__


# -- the pure part -------------------------------------------------------------------------------------------------
def test_a_condition_keeps_the_segments_where_any_listed_event_happened():
    assert condition_mask(TRIALS, Condition(("lick",)), FIND).tolist() == [True, False, True]
    assert condition_mask(TRIALS, Condition(("touch",)), FIND).tolist() == [True, True, False]
    assert condition_mask(TRIALS, Condition(("lick", "touch")), FIND).tolist() == [True, True, True]      # any of


def test_no_keeps_the_segments_where_none_of_them_happened():
    assert condition_mask(TRIALS, Condition(("lick", "touch"), answer=False), FIND).tolist() == [False, False, False]
    assert condition_mask(TRIALS, Condition(("lick",), answer=False), FIND).tolist() == [False, True, False]


def test_every_condition_has_to_hold_and_one_that_cannot_be_checked_is_skipped_with_a_note():
    def find(name):
        if name == "gone":
            raise KeyError("this recording has no 'gone'")
        return FIND(name)

    mask, notes = conditions_mask(TRIALS, [Condition(("lick",)), Condition(("touch",))], find)
    assert mask.tolist() == [True, False, False]
    mask, notes = conditions_mask(TRIALS, [Condition(("lick",)), Condition(("gone",))], find)
    assert mask.tolist() == [True, False, True] and len(notes) == 1 and "gone" in notes[0]
    assert conditions_mask(TRIALS, [], FIND) == (None, [])


def test_a_condition_survives_being_saved():
    condition = Condition(("lick", "touch"), False, "start")
    assert Condition.from_dict(condition.to_dict()) == condition
    assert Condition.from_dict({"events": ["x"]}) == Condition(("x",))
    assert condition.label() == "lick or touch: no"
    assert Condition.from_dict({"events": ["x"], "window_ms": [0, 500]}) == Condition(("x",))      # an old saved window is ignored


# -- the navigator ----------------------------------------------------------------------------------------------------
def _navigator():
    return SegmentNavigator(ActionBus(), TRIALS, label="Trial")


def test_a_mask_narrows_the_segments_together_with_the_attribute_filter():
    nav = _navigator()
    assert nav.set_mask(np.array([True, True, False]))
    assert nav.match_count == 2
    nav.filter(stimulus="concave")
    assert nav.match_count == 1
    assert nav.facet_counts("stimulus") == {"concave": 1, "convex": 1}      # counts leave out only the stimulus filter
    nav.clear_filter()
    assert nav.match_count == 2                                             # the mask stays when the filter is cleared
    assert nav.set_mask(None) and nav.match_count == 3


def test_a_mask_that_leaves_nothing_is_refused_and_changes_nothing():
    nav = _navigator()
    nav.set_mask(np.array([True, False, False]))
    assert not nav.set_mask(np.array([False, False, False]))
    assert nav.match_count == 1
    nav.filter(stimulus="concave")
    assert not nav.set_mask(np.array([False, True, False]))                  # no concave trial in it


def test_a_mask_for_another_number_of_segments_is_refused():
    with pytest.raises(ValueError):
        _navigator().set_mask(np.array([True]))


def test_replacing_the_segments_drops_the_mask():
    nav = _navigator()
    nav.set_mask(np.array([True, False, False]))
    nav.replace_intervals(TRIALS)
    assert nav.match_count == 3


# -- in the application --------------------------------------------------------------------------------------------------
def _select(window, name, answer=True):
    return window.context.events.add(Condition((name,), answer))


def test_the_panel_starts_empty_and_a_condition_becomes_a_chip_and_narrows_the_trials(window):
    from PySide6.QtWidgets import QPushButton
    panel, nav = window.events_panel, window.context.navigator
    assert window.context.events.items == [] and not panel.empty.isHidden() and nav.match_count == 2
    assert _select(window, "Lick left")
    assert nav.match_count == 1 and nav.number == 1
    assert panel.empty.isHidden() and panel.chips.count() == 1
    assert "Lick left: yes" in panel.chips.itemAt(0).widget().findChildren(QPushButton)[0].text()
    assert window.filter_bar.match_label.text() == "1 of 2 match"


def test_conditions_combine_with_each_other_and_with_the_filters(window):
    events, bar = window.context.events, window.filter_bar
    assert events.add(Condition(("Lick left", "Lick right")))              # either lick: trial 1
    assert events.add(Condition(("Contact C0",)))
    assert window.context.navigator.match_count == 1
    assert bar._filters["stimulus"].itemText(0) == "All (1)"               # the counts follow the conditions


def test_a_condition_that_would_leave_nothing_is_refused_with_a_message(window):
    events = window.context.events
    assert events.add(Condition(("Lick left",), answer=False))              # trial 2
    assert not events.add(Condition(("Contact C0",)))                       # the only contact is in trial 1
    assert len(events.items) == 1 and "No segment" in window.events_panel.message.text()
    assert window.context.navigator.match_count == 1


def test_removing_and_changing_conditions(window):
    events = window.context.events
    events.add(Condition(("Lick left",)))
    events.add(Condition(("Contact C0",)))
    assert events.replace(1, Condition(("Contact C0",), answer=False)) is False       # trial 1 has the contact: nothing left
    assert events.remove(0)
    assert [c.events for c in events.items] == [("Contact C0",)] and window.context.navigator.match_count == 1
    assert events.clear() and window.context.navigator.match_count == 2


def test_conditions_are_saved_in_the_workspace_and_come_back(window):
    events = window.context.events
    events.add(Condition(("Lick left", "Lick right"), answer=True))
    saved = window.settings()["events"]
    events.clear()
    events.apply_state({"conditions": saved["conditions"] + [{"events": ["not an event"]}]})
    assert events.items == [Condition(("Lick left", "Lick right"))]      # the unknown event is ignored
    assert window.context.navigator.match_count == 1


def test_conditions_are_dropped_with_a_note_if_the_chosen_segmentation_would_leave_nothing(window):
    events = window.context.events
    events.add(Condition(("Lick left",)))
    assert window.set_segmentation("touches")                                # one window, 2.5 to 3.5: no left lick in it
    assert events.items == [] and any("dropped" in n for n in window.context.notes)
    assert window.context.navigator.match_count == 1


def test_the_command_on_a_named_event_adds_a_condition_and_is_not_offered_for_other_things(window):
    from syncviz.inspection import Target
    registry = window.context.commands
    licks = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    other = Target("session", "units", "events", "7", "Unit 7")
    assert "Only segments with this event" in [c.label for c in registry.for_target(licks)]
    assert "Only segments with this event" not in [c.label for c in registry.for_target(other)]
    assert registry.run("only_with_event", licks)
    assert window.context.events.items == [Condition(("Lick left",))]


def test_the_dialog_collects_the_events_and_the_answer(window):
    from PySide6.QtCore import Qt
    from syncviz_app.events_panel import ConditionDialog
    dialog = ConditionDialog(window.context, None)
    assert dialog.condition() is None                                        # nothing chosen
    group = dialog.tree.topLevelItem(1)
    group.child(0).setCheckState(0, Qt.CheckState.Checked)
    group.child(1).setCheckState(0, Qt.CheckState.Checked)
    dialog.no.setChecked(True)
    assert dialog.condition() == Condition(("Lick left", "Lick right"), False)
    dialog.search.setText("right")
    assert group.child(0).isHidden() and not group.child(1).isHidden() and dialog.tree.topLevelItem(0).isHidden()
    assert not hasattr(dialog, "limit")                                      # no window: a condition is about the whole segment


def test_editing_a_chip_starts_from_what_it_says(window, monkeypatch):
    from syncviz_app import events_panel
    window.context.events.add(Condition(("Lick left",)))
    seen = {}

    class Fake:
        def __init__(self, context, condition, parent=None):
            seen["start"] = condition

        def exec(self):
            return events_panel.QDialog.DialogCode.Accepted

        def condition(self):
            return Condition(("Lick right",))

    monkeypatch.setattr(events_panel, "ConditionDialog", Fake)
    window.events_panel.edit(0)
    assert seen["start"] == Condition(("Lick left",)) and window.context.events.items == [Condition(("Lick right",))]


def test_the_panel_says_when_the_project_names_no_events(window):
    window.context.events.groups = {}
    from syncviz_app.events_panel import EventsPanel
    assert not EventsPanel(window.context).add_button.isEnabled()


def test_a_refused_condition_says_how_many_segments_it_matches_on_its_own(window):
    events = window.context.events
    events.add(Condition(("Lick left",)))
    assert not events.add(Condition(("Lick left",), answer=False))          # contradicts the one before
    text = window.events_panel.message.text()
    assert "No segment would be left" in text and "On its own it matches 1 of 2" in text
    assert "other conditions and filters rule out the rest" in text
