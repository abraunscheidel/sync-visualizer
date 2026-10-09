"""Changing a condition by selecting its events: click the chip, change the selection, then Update or Revert (design doc 28.11)."""

import os

import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QPushButton

from syncviz.conditions import Condition
from syncviz.inspection import Selection, Target

from test_epochs import qapp, window  # noqa: F401  (fixtures)

NONE = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


# -- the selection remembers how it last changed -----------------------------------------------------------------------
def test_the_selection_says_whether_it_was_started_again_or_added_to():
    a, b, c = (Target("s", "p", "events", n, n) for n in "abc")
    selection = Selection()
    selection.set(a)
    assert selection.last_kind == "set"
    selection.toggle(b)
    assert selection.last_kind == "toggle"
    selection.extend(c, [a, b, c])
    assert selection.last_kind == "extend"
    selection.set_all([a, b])
    assert selection.last_kind == "set_all"
    selection.clear()
    assert selection.last_kind == "set"


# -- the panel ---------------------------------------------------------------------------------------------------------------
@pytest.fixture
def tracker(window):
    window.context.events.track("Lick left", "Lick right", "Contact C0")
    view = window.add_view({"type": "events", "title": "Tracker"})
    view.resize(520, 420)
    view.canvas.relayout()
    return view


def _press(view, name, modifiers=NONE):
    tile = next(t for t in view.canvas.tiles if t.name == name)
    view.pressed(tile.rect.center().toPoint(), False, modifiers)


def _buttons(window, index=0):
    chip = window.events_panel.chips.itemAt(index).widget()
    return {b.text(): b for b in chip.findChildren(QPushButton)}


def _link(window, index=0):
    """Click the chip's label, as the user does."""
    chip = window.events_panel.chips.itemAt(index).widget()
    label = next(b for b in chip.findChildren(QPushButton) if b.text() == window.context.events.items[index].label())
    label.click()


def _names(window):
    return [t.label for t in window.context.selection.targets]


def test_clicking_a_chip_selects_its_events_and_marks_it_as_the_one_being_changed(window, tracker):
    window.context.events.add(Condition(("Lick left", "Lick right")))
    _link(window)
    assert _names(window) == ["Lick left", "Lick right"] and window.events_panel.linked == 0
    assert "Update" not in _buttons(window)                                       # nothing differs yet
    assert "border" in window.events_panel.chips.itemAt(0).widget().styleSheet()


def test_adding_an_event_to_the_selection_offers_update_and_revert_and_changes_nothing_yet(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    _press(tracker, "Lick right", CTRL)
    buttons = _buttons(window)
    assert "Update" in buttons and "Revert" in buttons
    assert window.context.events.items == [Condition(("Lick left",))]             # not until Update


def test_update_makes_the_chip_use_the_selection_and_keeps_its_answer_mode_and_switch(window, tracker):
    window.context.events.add(Condition(("Lick left",), enabled=True))
    window.context.events.set_mode(0, "clip")
    _link(window)
    _press(tracker, "Contact C0", CTRL)
    _buttons(window)["Update"].click()
    condition = window.context.events.items[0]
    assert condition.events == ("Lick left", "Contact C0") and condition.mode == "clip" and condition.answer and condition.enabled
    assert "Update" not in _buttons(window) and window.events_panel.linked == 0       # done, and still the chip being changed


def test_events_can_be_taken_out_with_ctrl_and_the_chip_can_follow_a_shift_range(window, tracker):
    window.context.events.add(Condition(("Lick left", "Lick right", "Contact C0")))
    _link(window)
    _press(tracker, "Lick right", CTRL)                                              # take one out
    assert _names(window) == ["Lick left", "Contact C0"] and "Update" in _buttons(window)
    _buttons(window)["Update"].click()
    assert window.context.events.items[0].events == ("Lick left", "Contact C0")
    order = [t.name for t in tracker.canvas.tiles]
    _press(tracker, order[0])                                                         # a plain click: a different selection
    assert window.events_panel.linked is None


def test_revert_puts_the_selection_back_to_the_chips_events(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    _press(tracker, "Lick right", CTRL)
    _buttons(window)["Revert"].click()
    assert _names(window) == ["Lick left"] and "Update" not in _buttons(window)
    assert window.context.events.items == [Condition(("Lick left",))]
    assert window.events_panel.linked == 0                                             # still being changed: Ctrl-click again to try another


def test_a_plain_click_on_something_else_lets_go_of_the_chip(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    _press(tracker, "Contact C0")                                                      # a plain click: starts again
    assert window.events_panel.linked is None and "Update" not in _buttons(window)
    assert window.context.events.items == [Condition(("Lick left",))]
    assert "border" not in window.events_panel.chips.itemAt(0).widget().styleSheet()


def test_a_plain_click_on_one_of_the_chips_own_events_keeps_the_chip_linked(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    _press(tracker, "Lick left")                                                       # the same single event: nothing differs
    assert window.events_panel.linked == 0


def test_clearing_the_selection_lets_go_of_the_chip_and_deselecting_everything_with_ctrl_leaves_nothing_to_update_to(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    _press(tracker, "Lick left", CTRL)                                                 # the only event taken out
    assert window.context.selection.targets == [] and _buttons(window)["Update"].isEnabled() is False
    _buttons(window)["Revert"].click()
    assert _names(window) == ["Lick left"]
    window.context.selection.clear()
    assert window.events_panel.linked is None


def test_an_update_that_would_leave_nothing_is_refused_with_the_message_and_the_chip_stays_as_it_was(window, tracker):
    events = window.context.events
    events.add(Condition(("Lick right",), mode="clip"))                                # the clip around the right lick: 2.5 to 3.5 s
    events.add(Condition(("Contact C0",)))                                              # the contact (3.0 to 3.5) is inside it
    _link(window, 1)
    _press(tracker, "Lick left", CTRL)
    _press(tracker, "Contact C0", CTRL)                                                 # now just "Lick left": its licks are not in the clip
    assert _names(window) == ["Lick left"]
    _buttons(window, 1)["Update"].click()
    assert events.items[1].events == ("Contact C0",) and "No segment" in window.events_panel.message.text()
    assert "Update" in _buttons(window, 1)                                              # still proposed; Revert or try something else
    _buttons(window, 1)["Revert"].click()
    assert _names(window) == ["Contact C0"] and "Update" not in _buttons(window, 1)


def test_removing_the_linked_chip_lets_go_of_it(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    window.context.events.remove(0)
    assert window.events_panel.linked is None


def test_double_clicking_the_label_opens_the_dialog_instead(window, tracker, monkeypatch):
    from syncviz_app import events_panel
    window.context.events.add(Condition(("Lick left",)))
    opened = []
    monkeypatch.setattr(window.events_panel, "edit", lambda index: opened.append(index))
    chip = window.events_panel.chips.itemAt(0).widget()
    label = next(b for b in chip.findChildren(QPushButton) if b.text().startswith("Lick left"))
    label.doubleClicked.emit()
    assert opened == [0]


def test_the_chip_changed_in_the_dialog_is_not_confused_with_a_selection_change(window, tracker):
    window.context.events.add(Condition(("Lick left",)))
    _link(window)
    window.context.events.replace(0, Condition(("Contact C0",)))                       # changed some other way
    assert window.events_panel.linked is None
