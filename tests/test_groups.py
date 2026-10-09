"""Groups: named sets of items chosen by a rule or listed by hand, usable wherever events are (design doc 28.16)."""

import os
from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pynwb import NWBFile, NWBHDF5IO
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from syncviz.conditions import Condition
from syncviz.groups import Group, attribute_values, check_names, members_of, merge_events, rule_text, value_matches
from syncviz.inspection import Target
from syncviz.resources.events import EventSeries
from syncviz_app.app import build_window

# unit id, depth, layer, spike times
UNITS = [(7, 437.0, "4", [1.0, 2.0, 2.01, 5.0]), (12, 917.0, "5b", [3.0]), (130, 357.0, "2/3", [0.5, 4.0]), (21, 800.0, "5b", [5.5])]
ATTRS = {str(u): {"depth": d, "layer": layer} for u, d, layer, _ in UNITS}


# -- the pure part ----------------------------------------------------------------------------------------------------
def test_a_value_is_matched_as_text_unless_both_are_numbers_and_ranges_include_their_ends():
    assert value_matches("4", "4") and value_matches("4", 4) and not value_matches("5b", "4")
    assert value_matches(437.0, 437) and value_matches(437.0, "437.0") and not value_matches(437.0, 438)
    assert value_matches("5b", ["4", "5b"]) and not value_matches("2/3", ["4", "5b"])
    assert value_matches(700.0, {"min": 700}) and value_matches(700.0, {"max": 700}) and not value_matches(699.9, {"min": 700})
    assert value_matches(5, {"min": 1, "max": 5}) and not value_matches("deep", {"min": 1})


def test_a_rule_picks_the_items_that_satisfy_all_of_it_and_a_list_picks_those_it_names_that_exist():
    assert members_of(Group("L4", "s:units", {"layer": "4"}), ATTRS) == ["7"]
    assert members_of(Group("Deep", "s:units", {"depth": {"min": 700}}), ATTRS) == ["12", "21"]
    assert members_of(Group("Deep 5b", "s:units", {"layer": "5b", "depth": {"min": 850}}), ATTRS) == ["12"]
    assert members_of(Group("Picks", "s:units", members=("130", "7", "999")), ATTRS) == ["7", "130"]      # the container's order; 999 is not here
    assert members_of(Group("None", "s:units", {"nothing": "x"}), ATTRS) == []                               # an attribute no item has


def test_a_group_needs_a_name_and_a_rule_or_a_list_and_survives_being_saved():
    with pytest.raises(ValueError):
        Group("  ", "s:units", {"layer": "4"})
    with pytest.raises(ValueError):
        Group("Empty", "s:units")
    by_rule = Group("Deep", "s:units", {"depth": {"min": 700}}, description="the deep ones")
    by_list = Group("Picks", "s:units", members=("7", "12"))
    assert Group.from_dict("Deep", by_rule.to_dict()) == by_rule and Group.from_dict("Picks", by_list.to_dict()) == by_list
    assert by_rule.by_rule and not by_list.by_rule


def test_the_group_in_words():
    assert rule_text(Group("a", "s:u", {"layer": "4"})) == "layer is 4"
    assert rule_text(Group("a", "s:u", {"layer": ["4", "5b"], "depth": {"min": 700, "max": 900}})) == "layer is 4 or 5b and depth from 700 to 900"
    assert rule_text(Group("a", "s:u", {"depth": {"min": 700}})) == "depth at least 700"
    assert rule_text(Group("a", "s:u", members=("7", "12"))) == "7, 12"


def test_the_values_to_choose_a_rule_from_are_the_distinct_ones_each_attribute_takes():
    values = attribute_values(ATTRS)
    assert values["layer"] == ["2/3", "4", "5b"] and values["depth"] == [357.0, 437.0, 800.0, 917.0]


def test_a_group_as_events_is_every_spike_of_every_member_in_time_order():
    merged = merge_events([EventSeries(times=np.array([1.0, 3.0])), EventSeries(times=np.array([2.0, 4.0]))], "g", ["a", "b"])
    assert merged.times.tolist() == [1.0, 2.0, 3.0, 4.0] and merged.metadata["members"] == ["a", "b"]
    assert len(merge_events([], "none")) == 0


def test_a_group_may_not_reuse_a_name():
    check_names([Group("A", "s:u", {"x": 1}), Group("B", "s:u", {"x": 1})], ["Lick"])
    with pytest.raises(ValueError):
        check_names([Group("A", "s:u", {"x": 1}), Group("A", "s:u", {"x": 2})], [])
    with pytest.raises(ValueError):
        check_names([Group("Lick", "s:u", {"x": 1})], ["Lick"])


# -- in the application --------------------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, qapp):
    nwb = NWBFile(session_description="s", identifier="g", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_unit_column(name="depth", description="microns")
    nwb.add_unit_column(name="layer", description="layer")
    for uid, depth, layer, spikes in UNITS:
        nwb.add_unit(id=uid, spike_times=spikes, depth=depth, layer=layer)
    nwb.add_trial(start_time=0.0, stop_time=3.0)
    nwb.add_trial(start_time=3.0, stop_time=6.0)
    with NWBHDF5IO(str(tmp_path / "session.nwb"), "w") as io:
        io.write(nwb)
    (tmp_path / "project.yaml").write_text("""
name: grouped
sources:
  session: {type: nwb, path: session.nwb}
segmentations:
  trials: {label: Trial, from: "session:intervals/trials"}
events:
  Other:
    Whole trial: {from: "session:intervals/trials"}
groups:
  Layer 4: {of: "session:units", where: {layer: "4"}, description: "Granular layer units."}
  Deep: {of: "session:units", where: {depth: {min: 700}}}
views:
  - type: events
    title: Tracker
  - type: indicators
    title: Units
    rows:
      - {name: Unit 7, kind: events, from: "session:units", member: "7"}
      - {name: Unit 12, kind: events, from: "session:units", member: "12"}
      - {name: Unit 130, kind: events, from: "session:units", member: "130"}
      - {name: Unit 21, kind: events, from: "session:units", member: "21"}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml")                       # with workspaces on, so saved groups are kept in a file
    w.show()
    yield w
    w.close()


def _unit(window, uid):
    return Target("session", "units", "events", uid, f"Unit {uid}")


def test_the_projects_groups_are_listed_with_their_items_in_the_open_recording(window):
    groups = window.context.groups
    assert groups.names() == ["Layer 4", "Deep"]
    assert groups.members(window.context.resources, "Layer 4") == ["7"] and groups.members(window.context.resources, "Deep") == ["12", "21"]
    assert not groups.is_saved("Deep")


def test_a_group_is_an_event_it_happens_when_any_member_does(window):
    events = window.context.events
    assert "Groups" in events.groups and list(events.groups["Groups"]) == ["Layer 4", "Deep"]
    assert events.find("Deep").times.tolist() == [3.0, 5.5]                         # unit 12 and unit 21 together
    assert events.find("Layer 4").times.tolist() == [1.0, 2.0, 2.01, 5.0]
    assert events.target_of("Deep") == Target("", "Deep", "group", None, "Deep")
    assert events.name_of(events.target_of("Deep")) == "Deep"


def test_conditions_clips_and_the_tracker_work_on_a_group_like_on_any_event(window):
    events = window.context.events
    assert events.add(Condition(("Deep",)))                                        # a deep unit fired at 3.0 and 5.5 s: trial 2 only
    assert window.context.navigator.match_count == 1 and window.context.navigator.number == 2
    events.clear()
    assert not events.add(Condition(("Layer 4",), answer=False))                   # unit 7 fires in both trials: none would be left
    events.clear()
    assert events.add(Condition(("Deep",), mode="clip"))
    assert window.context.navigator.label == "Deep clip" and window.context.navigator.count == 2        # 3.0 and 5.5 s, +-500 ms
    events.clear()
    events.track("Deep")
    tracker = next(v for v in window.views if v.type_name == "events")
    assert tracker.levels_at(3.0)["Deep"] == 1.0 and tracker.levels_at(4.0)["Deep"] == 0.0


def test_a_group_has_details_of_its_own(window):
    details = window.context.inspector.details(window.context.events.target_of("Layer 4"))
    values = {f.name: f.value for f in details.fields}
    assert details.description == "Granular layer units."
    assert values["Members here"] == "1" and values["Defined by"] == "layer is 4" and values["Kept in"] == "the project file"
    assert any(name.startswith("Events") for name in values) and any(name.startswith("Rate") for name in values)
    text = window.context.inspector.hover_text(window.context.events.target_of("Layer 4"))
    assert text.startswith("Layer 4") and "Members here: 1" in text


def test_selecting_a_group_selects_its_items_wherever_they_are_shown(window):
    registry, selection = window.context.commands, window.context.selection
    target = window.context.events.target_of("Deep")
    assert "Select its items" in [c.label for c in registry.for_target(target)]
    assert registry.run("select_members", target)
    assert sorted(t.member for t in selection.targets) == ["12", "21"] and all(t.kind == "events" for t in selection.targets)
    units = next(v for v in window.views if v.title == "Units")
    assert units.lamps.selected == {1, 3}                                          # its tiles for units 12 and 21 are outlined
    assert "Select its items" not in [c.label for c in registry.for_target(_unit(window, "7"))]


def test_a_group_opens_as_a_view_of_its_average_rate(window):
    registry = window.context.commands
    target = window.context.events.target_of("Deep")
    labels = [c.label for c in registry.get("open_as_view").children(target, None)]
    assert labels == ["Time series plot"]
    registry.get("open_as_view").children(target, None)[0].run(target, None)
    view = window.views[-1]
    assert view.type_name == "timeseries" and view.title == "Deep rate"
    assert view.series.values.max() > 0 and len(view.series) > 10


def test_selected_items_are_saved_as_a_group_that_is_kept_in_a_file_and_comes_back(window, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QInputDialog
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("My picks", True)))
    registry = window.context.commands
    targets = [_unit(window, "130"), _unit(window, "7")]
    assert "Save as group…" in [c.label for c in registry.for_targets(targets)]
    assert registry.run_many("save_group", targets)
    groups = window.context.groups
    assert groups.is_saved("My picks") and groups.members(window.context.resources, "My picks") == ["7", "130"]      # in the container's order
    assert "My picks" in window.context.events.groups["Groups"]
    from syncviz_app.group_store import GroupStore, groups_path
    again = GroupStore([], groups_path(tmp_path / "project.yaml", "grouped"))
    assert again.names() == ["My picks"] and again.get("My picks").members == ("130", "7")
    mixed = [_unit(window, "7"), Target("session", "processing/behavior/licks", "events", "left", "Lick")]
    assert "Save as group…" not in [c.label for c in registry.for_targets(mixed)]                  # not all from one container


def test_a_group_cannot_take_the_name_of_another_group_or_of_an_event(window, monkeypatch):
    from PySide6.QtWidgets import QInputDialog
    registry = window.context.commands
    for name in ("Deep", "Whole trial"):
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, _n=name, **k: (_n, True)))
        registry.run_many("save_group", [_unit(window, "7")])
        assert "already in use" in window.statusBar().currentMessage()
    assert window.context.groups.names() == ["Layer 4", "Deep"]


def test_removing_a_saved_group_drops_what_used_it_and_the_projects_own_cannot_be_removed(window):
    groups, events = window.context.groups, window.context.events
    groups.add(Group("Mine", "session:units", members=("7",)))
    events.track("Mine")
    events.add(Condition(("Mine",)))
    groups.remove("Mine")
    assert "Mine" not in events.tracked and events.items == [] and "Mine" not in groups.names()
    with pytest.raises(KeyError):
        groups.remove("Deep")


def test_the_groups_panel_lists_them_and_selects_and_deletes(window):
    panel = window.groups_panel
    names = [panel.tree.topLevelItem(i).text(0) for i in range(panel.tree.topLevelItemCount())]
    assert names == ["Layer 4", "Deep"] and panel.tree.topLevelItem(1).text(1) == "2"           # items here
    assert panel.tree.topLevelItem(0).text(2) == "layer is 4" and panel.empty.isHidden()
    panel.tree.setCurrentItem(panel.tree.topLevelItem(1))
    assert panel.select_button.isEnabled() and not panel.delete_button.isEnabled()              # the project's: not deletable
    panel.select_items()
    assert sorted(t.member for t in window.context.selection.targets) == ["12", "21"]
    window.context.groups.add(Group("Mine", "session:units", members=("7",)))
    panel.tree.setCurrentItem(panel.tree.topLevelItem(2))
    assert panel.delete_button.isEnabled()
    panel.delete()
    assert panel.tree.topLevelItemCount() == 2


def test_the_dialog_makes_a_rule_group_and_counts_the_items_it_picks(window):
    from syncviz_app.groups_panel import GroupDialog
    dialog = GroupDialog(window.context)
    assert dialog.container.currentData() == "session:units" and dialog.group() is None             # no name yet
    dialog.name.setText("Layer 5b")
    row = dialog.rules.itemAt(0).widget()
    row.attribute.setCurrentIndex(row.attribute.findText("layer"))
    row.value.setCurrentIndex(row.value.findText("5b"))
    group = dialog.group()
    assert group == Group("Layer 5b", "session:units", {"layer": "5b"})
    assert dialog.preview.text().startswith("2 of 4 items in the open recording match")
    row.attribute.setCurrentIndex(row.attribute.findText("depth"))                                    # a measurement: a range, by default of all of it
    assert row.operator.currentData() == "range" and (row.low.value(), row.high.value()) == (357.0, 917.0)
    row.low.setValue(700.0)
    assert dialog.group().where == {"depth": {"min": 700.0, "max": 917.0}} and dialog.preview.text().startswith("2 of 4")


def test_saved_groups_in_a_broken_file_are_ignored_with_a_note(tmp_path):
    from syncviz_app.group_store import GroupStore
    path = tmp_path / "groups" / "x.json"
    path.parent.mkdir()
    path.write_text("{ not json", encoding="utf-8")
    store = GroupStore([Group("Deep", "s:u", {"a": 1})], path)
    assert store.names() == ["Deep"] and store.notes and "could not be read" in store.notes[0]
    path.write_text('{"groups": {"Deep": {"of": "s:u", "where": {"a": 2}}, "Fine": {"of": "s:u", "members": ["1"]}}}', encoding="utf-8")
    store = GroupStore([Group("Deep", "s:u", {"a": 1})], path)
    assert store.names() == ["Deep", "Fine"] and "ignored" in store.notes[0]                        # the project's wins
