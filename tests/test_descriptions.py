"""What a field is: the description the file gives, and the project's note on how to read it, shown as tooltips."""

import os
from datetime import datetime, timezone

import numpy as np
import pytest
from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralEvents
from pynwb.epoch import TimeIntervals
from PySide6.QtWidgets import QApplication

from syncviz_app.add_view_dialog import AddViewDialog
from syncviz_app.app import build_window
from syncviz_app.context import explain
from syncviz_nwb import NWBSource

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _write_nwb(path):
    nwb = NWBFile(session_description="s", identifier="d", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial_column(name="stimulus", description="(str) the shape shown, concave or convex")
    nwb.add_trial_column(name="plain", description="no description")
    for i, (a, b) in enumerate([(0.0, 5.0), (5.0, 10.0)]):
        nwb.add_trial(start_time=a, stop_time=b, stimulus=["concave", "convex"][i], plain=i)
    behavior = nwb.create_processing_module("behavior", "b")
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0, 1.0], unit="n/a", timestamps=[1.0, 2.0], description="times of the left licks")
    licks.create_timeseries(name="right", data=[1.0], unit="n/a", timestamps=[3.0])
    behavior.add(licks)
    contacts = TimeIntervals(name="contacts_C0", description="time and location of contacts made by whisker C0")
    contacts.add_interval(start_time=3.0, stop_time=3.5)
    behavior.add(contacts)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


# -- from the file ---------------------------------------------------------------------------------------
def test_column_descriptions_travel_with_the_intervals_and_placeholders_are_dropped(tmp_path):
    _write_nwb(tmp_path / "s.nwb")
    table = NWBSource(tmp_path / "s.nwb").read_intervals("intervals/trials")
    assert table.descriptions == {"stimulus": "(str) the shape shown, concave or convex"}


def test_the_catalog_carries_the_descriptions_of_containers_and_their_members(tmp_path):
    _write_nwb(tmp_path / "s.nwb")
    entries = {e.path.rsplit("/", 1)[-1]: e for e in NWBSource(tmp_path / "s.nwb").catalog()}
    licks = entries["licks"]
    assert licks.description == ""                                # a container may say nothing about itself
    assert licks.member_descriptions == {"left": "times of the left licks", "right": ""}
    assert entries["contacts_C0"].description == "time and location of contacts made by whisker C0"


# -- explaining ---------------------------------------------------------------------------------------------
def test_an_explanation_is_the_description_then_the_projects_note_and_either_may_be_missing():
    glossary = {"stimulus": "How to read it."}
    assert explain(glossary, "stimulus", "What it is.") == "What it is.\n\nHow to read it."
    assert explain(glossary, "stimulus") == "How to read it."
    assert explain(glossary, "other", "What it is.") == "What it is."
    assert explain(glossary, "other") == ""
    assert explain({}, "x", "   ") == ""


# -- where it shows -----------------------------------------------------------------------------------------
@pytest.fixture
def window(tmp_path, qapp):
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text("""
name: described
sources:
  session: {type: nwb, path: session.nwb}
glossary:
  stimulus: "Concave and convex are the two shapes the mouse learns to tell apart."
  Lick left: "The tongue touched the left spout."
  Licks: "Tongue contacts with the spouts."
segmentations:
  trials: {label: Trial, from: "session:intervals/trials", filters: [stimulus, plain]}
events:
  Licks:
    Lick left: {from: "session:processing/behavior/licks", member: left}
    Lick right: {from: "session:processing/behavior/licks", member: right}
views:
  - type: events
    title: Tracker
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml")
    w.show()
    yield w
    w.close()


def test_a_filter_explains_its_field_with_the_files_description_and_the_projects_note(window):
    bar = window.filter_bar
    tip = bar._filters["stimulus"].toolTip()
    assert tip == ("(str) the shape shown, concave or convex\n\nConcave and convex are the two shapes the mouse learns to tell apart.")
    assert bar._filters["plain"].toolTip() == ""                  # nothing to say: no empty tooltip


def test_the_add_view_dialog_explains_what_each_candidate_is(window):
    dialog = AddViewDialog(window.source_catalog())
    tips = {}
    for g in range(dialog.tree.topLevelItemCount()):
        group = dialog.tree.topLevelItem(g)
        for c in range(group.childCount()):
            child = group.child(c)
            tips[child.text(0).split("   ")[0]] = child.toolTip(0)
    assert tips["licks"] == ""                                    # nothing described: no tooltip
    assert tips["contacts_C0"] == "time and location of contacts made by whisker C0"


def test_the_events_in_the_condition_dialog_and_on_the_trackers_tiles_explain_themselves_from_the_glossary(window):
    from syncviz_app.events_panel import ConditionDialog
    dialog = ConditionDialog(window.context, None)
    group = dialog.tree.topLevelItem(0)
    tips = {group.child(i).text(0): group.child(i).toolTip(0) for i in range(group.childCount())}
    assert tips == {"Lick left": "The tongue touched the left spout.", "Lick right": ""}      # nothing to say: no empty tooltip
    tracker = next(v for v in window.views if v.title == "Tracker")
    tracker.resize(400, 300)
    window.context.events.track("Lick left")
    tracker.canvas.relayout()
    tile = tracker.canvas.tiles[0].rect.center().toPoint()
    text = tracker.hover_text(tracker.canvas.mapTo(tracker, tile))
    assert "The tongue touched the left spout." in text and "left spout" in text
