"""A project with no segmentation (continuous behaviour, no trials) is one segment, the whole recording, so clips still work."""

import os

import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from syncviz.conditions import Condition
from syncviz.inspection import Target
from syncviz_app.app import build_window

from test_descriptions import _write_nwb


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, qapp):
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text("""
name: continuous
sources:
  session: {type: nwb, path: session.nwb}
events:
  Licks:
    Lick left: {from: "session:processing/behavior/licks", member: left}
    Lick right: {from: "session:processing/behavior/licks", member: right}
views:
  - type: tracks
    title: Behaviour
    rows:
      - {name: Lick left, kind: events, from: "session:processing/behavior/licks", member: left}
      - {name: Contact, kind: intervals, from: "session:processing/behavior/contacts_C0"}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml", use_workspace=False)
    w.show()
    yield w
    w.close()


def test_with_no_segmentation_the_recording_is_one_segment_and_nothing_is_hidden(window):
    nav = window.context.navigator
    assert nav is not None and nav.label == "Recording" and nav.count == 1
    assert nav.restricting is False and window.context.timeline.allows(0.0) and window.context.timeline.allows(9.0)
    window.timeline_bar.grab()                                              # an unbounded segment must not break the strip


def test_statistics_are_over_the_whole_recording_not_a_huge_segment(window):
    assert window.context.inspector.scope().label == "whole recording"
    details = window.context.inspector.details(Target("session", "processing/behavior/licks", "events", "left", "Lick left"))
    values = {f.name: f.value for f in details.fields}
    assert values["Events (whole recording)"] == "2" and values["Rate (whole recording)"] != "0 per second"


def test_clips_around_an_event_work_without_trials_and_removing_them_goes_back(window):
    events, nav = window.context.events, window.context.navigator
    assert events.add(Condition(("Lick left",), mode="clip"))
    assert nav.label == "Lick left clip" and nav.bounds == pytest.approx((0.5, 2.5)) and nav.count == 1     # two licks, merged
    assert window.context.timeline.allows(1.0) and not window.context.timeline.allows(6.0)
    window.timeline_bar.grab()
    assert not events.add(Condition(("Lick right",)))                       # the right lick (3.0) is outside these clips
    assert len(events.items) == 1
    events.clear()
    assert nav.label == "Recording" and window.context.timeline.allows(6.0)


def test_a_condition_on_the_one_segment_keeps_it_or_refuses(window):
    events = window.context.events
    assert events.add(Condition(("Lick left",)))                            # the recording has left licks
    assert not events.add(Condition(("Lick left",), answer=False))          # ... so "none" leaves nothing
