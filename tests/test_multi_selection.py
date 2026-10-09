"""Selecting several items: Ctrl-click, Shift-click, commands on the whole selection, and the Details table (design doc 28.11)."""

import os

import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt

from syncviz.conditions import Condition
from syncviz.inspection import Selection, Target

from test_epochs import qapp, window  # noqa: F401  (fixtures)

A = Target("s", "p", "events", "a", "A")
B = Target("s", "p", "events", "b", "B")
C = Target("s", "p", "events", "c", "C")
D = Target("s", "p", "events", "d", "D")


# -- the selection itself ---------------------------------------------------------------------------------------------
def test_a_plain_choice_replaces_the_selection_and_ctrl_adds_and_removes():
    selection = Selection()
    selection.set(A)
    selection.toggle(C)
    assert selection.targets == [A, C] and selection.target == C                 # `target` is the one chosen last
    selection.toggle(A)
    assert selection.targets == [C]
    selection.set(B)
    assert selection.targets == [B]
    selection.clear()
    assert selection.targets == [] and selection.target is None


def test_shift_selects_the_run_from_the_last_one_clicked_and_the_run_can_be_changed():
    selection = Selection()
    order = [A, B, C, D]
    selection.set(B)
    selection.extend(D, order)
    assert selection.targets == [B, C, D]
    selection.extend(A, order)                                                   # the anchor is still B
    assert selection.targets == [A, B]
    selection.extend(B, order)
    assert selection.targets == [B]


def test_shift_without_a_starting_point_selects_just_that_item():
    selection = Selection()
    selection.extend(C, [A, B, C])
    assert selection.targets == [C]
    selection.set(A)
    selection.extend(D, [B, C, D])                                                # A is not in this view's items
    assert selection.targets == [D]


def test_observers_hear_of_each_change_once_and_not_of_no_change():
    selection, heard = Selection(), []
    selection.subscribe(heard.append)
    selection.set(A)
    selection.set(A)                                                              # nothing changed
    selection.toggle(B)
    selection.set_all([B, B, A])                                                  # duplicates are one item
    assert heard == [[A], [A, B], [B, A]]


def test_the_time_under_the_pointer_does_not_make_two_targets_different_items():
    selection = Selection()
    selection.set(Target("s", "p", "events", "a", "A", at=1.0))
    assert selection.is_selected(Target("s", "p", "events", "a", "A", at=9.0))


# -- clicking in the views ----------------------------------------------------------------------------------------------
@pytest.fixture
def events_view(window):
    rows = [{"name": "Lick left", "kind": "events", "from": "session:processing/behavior/licks", "member": "left"},
            {"name": "Lick right", "kind": "events", "from": "session:processing/behavior/licks", "member": "right"},
            {"name": "Contact C0", "kind": "intervals", "from": "session:processing/behavior/contacts_C0"}]
    view = window.add_view({"type": "indicators", "title": "Events", "rows": rows})
    view.resize(600, 400)
    return view


def _tile(view, name):
    rect = next(r for r, row in zip(view.lamps.tile_rects(), view.rows) if row["name"] == name)
    return view.lamps.mapFromParent(QPoint(int(rect.center().x()), int(rect.center().y())))


def _click(view, name, modifiers=Qt.KeyboardModifier.NoModifier, double=False):
    view._pressed(_tile(view, name), double, modifiers)


def test_ctrl_click_adds_and_removes_tiles_and_a_plain_click_starts_again(window, events_view):
    selection = window.context.selection
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier)
    assert [t.label for t in selection.targets] == ["Lick left", "Contact C0"]
    assert events_view.lamps.selected == {0, 2}                                    # both outlined
    _click(events_view, "Lick left", Qt.KeyboardModifier.ControlModifier)
    assert [t.label for t in selection.targets] == ["Contact C0"]
    _click(events_view, "Lick right")
    assert [t.label for t in selection.targets] == ["Lick right"] and events_view.lamps.selected == {1}


def test_shift_click_selects_the_tiles_between_in_the_order_the_view_lists_them(window, events_view):
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ShiftModifier)
    assert [t.label for t in window.context.selection.targets] == ["Lick left", "Lick right", "Contact C0"]
    assert events_view.lamps.selected == {0, 1, 2}


def test_a_double_click_ignores_the_modifiers_and_runs_the_bound_command(window, events_view):
    window.context.commands.bindings["double_click"] = "select"
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier, double=True)
    assert [t.label for t in window.context.selection.targets] == ["Contact C0"]


def test_every_selected_row_of_a_tracks_view_is_marked(window):
    tracks = window.add_view({"type": "tracks", "title": "Rows", "rows": [
        {"name": "Lick left", "kind": "events", "from": "session:processing/behavior/licks", "member": "left"},
        {"name": "Lick right", "kind": "events", "from": "session:processing/behavior/licks", "member": "right"},
        {"name": "Contact C0", "kind": "intervals", "from": "session:processing/behavior/contacts_C0"}]})
    targets = tracks.selectable_targets()
    window.context.selection.set_all([targets[0], targets[2]])
    assert [b.isVisible() for b in tracks.bands] == [True, True]
    window.context.selection.set(targets[1])
    assert [b.isVisible() for b in tracks.bands] == [True, False]
    window.context.selection.clear()
    assert not any(b.isVisible() for b in tracks.bands)


def test_a_following_tracks_view_shows_every_selected_item_that_it_can(window):
    tracks = window.add_view({"type": "tracks", "title": "Follower", "follow_selection": True, "rows": [
        {"name": "Contact C0", "kind": "intervals", "from": "session:processing/behavior/contacts_C0"}]})
    left = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    right = Target("session", "processing/behavior/licks", "events", "right", "Lick right")
    window.context.selection.set_all([left, right])
    assert [r["name"] for r in tracks.rows] == ["Lick left", "Lick right"]
    window.context.selection.set_all([left, Target("session", "x", "points", None, "pose")])   # one it cannot show
    assert [r["name"] for r in tracks.rows] == ["Lick left"]


def test_escape_clears_the_whole_selection(window, events_view):
    from PySide6.QtGui import QShortcut
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier)
    next(s for s in window.findChildren(QShortcut) if s.key().toString() == "Esc").activated.emit()
    assert window.context.selection.targets == []


# -- the menu ---------------------------------------------------------------------------------------------------------------
@pytest.fixture
def captured_menu(monkeypatch):
    shown = []
    import syncviz_app.views.base as base

    class Fake:
        def exec(self, _pos):
            pass

    def build(actions, target, origin, parent):
        shown.append(([a.label for a in actions], target))
        return Fake()

    monkeypatch.setattr(base, "build_menu", build)
    return shown


def test_right_clicking_a_selected_tile_offers_what_can_be_done_with_all_of_them(window, events_view, captured_menu):
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier)
    events_view.show_menu(_tile(events_view, "Contact C0"), None)
    labels, target = captured_menu[-1]
    assert isinstance(target, list) and [t.label for t in target] == ["Lick left", "Contact C0"]
    assert {"Only segments with any of these events", "Only segments with all of these events",
            "Only segments with none of these events", "Clip around these events"} <= set(labels)
    assert "Select" not in labels                                                  # one-item commands are not offered for several


def test_right_clicking_something_not_selected_selects_it_alone_and_offers_the_one_item_menu(window, events_view, captured_menu):
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier)
    events_view.show_menu(_tile(events_view, "Lick right"), None)
    labels, target = captured_menu[-1]
    assert [t.label for t in window.context.selection.targets] == ["Lick right"]
    assert not isinstance(target, list) and "Select" in labels and "Only segments with this event" in labels


def test_the_commands_for_several_events_make_one_condition_or_one_each(window):
    registry, events = window.context.commands, window.context.events
    left = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    right = Target("session", "processing/behavior/licks", "events", "right", "Lick right")
    contact = Target("session", "processing/behavior/contacts_C0", "intervals", None, "Contact C0")
    assert registry.run_many("events_any", [left, right])
    assert events.items == [Condition(("Lick left", "Lick right"))]
    events.clear()
    assert registry.run_many("events_all", [left, contact])
    assert events.items == [Condition(("Lick left",)), Condition(("Contact C0",))]
    events.clear()
    assert registry.run_many("events_none", [right, contact])
    assert events.items == [Condition(("Lick right", "Contact C0"), answer=False)]
    events.clear()
    assert registry.run_many("clip_many", [left, right])
    assert events.items == [Condition(("Lick left", "Lick right"), mode="clip")] and window.context.navigator.label == "Clip"


def test_a_group_of_conditions_that_together_leave_nothing_is_refused_as_one(window):
    registry, events = window.context.commands, window.context.events
    left = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    right = Target("session", "processing/behavior/licks", "events", "right", "Lick right")
    assert registry.run_many("events_none", [left, right])                        # trial 2 only
    before = list(events.items)
    contact = Target("session", "processing/behavior/contacts_C0", "intervals", None, "Contact C0")
    assert registry.run_many("events_all", [left, contact]) is True                # it ran...
    assert events.items == before and "No segment" in window.events_panel.message.text()      # ...and was refused whole


def test_the_commands_for_several_need_every_item_to_be_an_event_the_project_names(window):
    registry = window.context.commands
    left = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    other = Target("session", "units", "events", "7", "Unit 7")
    assert [c.id for c in registry.for_targets([left, other])] == []
    assert not registry.run_many("events_any", [left, other])
    assert not registry.run_many("events_any", [left])                              # a single item uses the one-item commands


# -- the Details panel --------------------------------------------------------------------------------------------------------
def test_several_selected_items_show_a_table_to_compare_and_a_click_shows_one_in_full(window, events_view):
    panel = window.details_panel
    _click(events_view, "Lick left")
    assert panel.table.isHidden() and panel.tree.topLevelItemCount() > 0           # one item: as before
    _click(events_view, "Lick right", Qt.KeyboardModifier.ControlModifier)
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ControlModifier)
    assert not panel.table.isHidden() and panel.title.text() == "3 items selected"
    assert [panel.table.topLevelItem(i).text(0) for i in range(3)] == ["Lick left", "Lick right", "Contact C0"]
    headers = [panel.table.headerItem().text(c) for c in range(panel.table.columnCount())]
    assert headers[0] == "Item" and any(h.startswith("Events") for h in headers[1:])
    assert panel.tree.topLevelItemCount() == 0                                      # nothing in full until one is chosen
    panel.table.setCurrentItem(panel.table.topLevelItem(1))
    assert panel.shown.label == "Lick right" and panel.tree.topLevelItemCount() > 0
    assert len(window.context.selection.targets) == 3                               # looking at one does not change the selection
    window.context.selection.set(panel.shown)
    assert panel.table.isHidden() and panel.title.text() == "Lick right"


def test_a_very_large_selection_is_not_compared(window, events_view, monkeypatch):
    from syncviz_app import details_panel
    monkeypatch.setattr(details_panel, "MAX_ROWS", 2)
    _click(events_view, "Lick left")
    _click(events_view, "Contact C0", Qt.KeyboardModifier.ShiftModifier)
    panel = window.details_panel
    assert panel.table.topLevelItemCount() == 2 and "Too many to compare (3)" in panel.description.text()


def test_ticking_a_figure_to_show_on_hover_works_for_the_item_chosen_in_the_table(window, events_view):
    from PySide6.QtWidgets import QCheckBox
    _click(events_view, "Lick left")
    _click(events_view, "Lick right", Qt.KeyboardModifier.ControlModifier)
    panel = window.details_panel
    panel.table.setCurrentItem(panel.table.topLevelItem(0))
    boxes = panel.tree.findChildren(QCheckBox)
    boxes[-1].setChecked(not boxes[-1].isChecked())
    assert window.context.inspector.hover_keys is not None
