"""Many recordings in one project: finding them, switching between them, and what stays the same."""

import os
import time
from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pynwb")
pytest.importorskip("av")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralEvents, BehavioralTimeSeries
from PySide6.QtWidgets import QApplication

from syncviz.catalog import discover, fill, has_unfilled
from syncviz.core import Seek
from syncviz_app.app import build_window
from syncviz_app.project import load_project

from test_app_smoke import FPS, _write_video


def _write_session(path, trials, seconds=5.0):
    nwb = NWBFile(session_description="s", identifier=path.stem, session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    if trials:
        nwb.add_trial_column(name="stimulus", description="shape")
        nwb.add_trial_column(name="number", description="trial number")
        for i, (a, b, stim) in enumerate(trials):
            nwb.add_trial(start_time=float(a), stop_time=float(b), stimulus=stim, number=i + 1)
    behavior = nwb.create_processing_module("behavior", "b")
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0, 1.0], unit="n/a", timestamps=[0.5, 1.0])
    behavior.add(licks)
    series = BehavioralTimeSeries(name="whisker")
    t = np.arange(0, seconds, 1 / 50)
    series.create_timeseries(name="angle", data=np.sin(t), unit="degrees", timestamps=t)
    behavior.add(series)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def project_path(tmp_path):
    """Four sessions: A1 and A2 (mouse A, A1 has video), B1 (mouse B, 8 s, no video) and C1 (no trials at all)."""
    data = tmp_path / "data"
    for sub in ("sub-A", "sub-B", "sub-C"):
        (data / sub).mkdir(parents=True)
    _write_session(data / "sub-A" / "sub-A_ses-1.nwb", [(0, 1.5, "convex"), (1.5, 3.0, "concave"), (3.0, 5.0, "convex")])
    _write_session(data / "sub-A" / "sub-A_ses-2.nwb", [(0, 2.0, "concave"), (2.0, 5.0, "concave")])
    _write_session(data / "sub-B" / "sub-B_ses-1.nwb", [(0, 4.0, "convex"), (4.0, 8.0, "concave")], seconds=8.0)
    _write_session(data / "sub-C" / "sub-C_ses-1.nwb", [])
    (data / "sub-A" / "sub-A_ses-1").mkdir()
    _write_video(data / "sub-A" / "sub-A_ses-1" / "clip.mkv")
    path = tmp_path / "project.yaml"
    path.write_text(f"""
name: multi
cache: cache
sources:
  session: {{type: nwb, path: "{{path}}"}}
  video: {{type: video, path: "{{dir}}/{{stem}}/*.mkv", fps: {FPS}}}
collections:
  label: Session
  from: {{glob: "data/*/*.nwb"}}
  attributes: {{mouse: 'sub-([A-Z])_', day: 'ses-(\\d+)'}}
segmentations:
  groups:
    label: Block
    from: session:intervals/trials
    number_attribute: number
    filters: [stimulus]
views:
  - {{type: video, title: Clip, source: video}}
  - type: timeseries
    title: Angle
    series: {{from: "session:processing/behavior/whisker", member: angle}}
  - type: tracks
    title: Events
    rows:
      - {{name: Licks, kind: events, from: "session:processing/behavior/licks", member: left}}
""", encoding="utf-8")
    return path


def _pump(qapp, seconds=0.2):
    end = time.time() + seconds
    while time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)


@pytest.fixture
def window(project_path, qapp):
    w = build_window(project_path)
    w.show()
    yield w
    w.close()
    qapp.processEvents()


def _index(window, key):
    return [c.key for c in window.project.collections].index(key)


# -- finding collections ----------------------------------------------------------------------
def test_a_folder_pattern_finds_each_file_and_reads_attributes_from_the_path(project_path):
    project = load_project(project_path)
    assert [c.key for c in project.collections] == ["sub-A_ses-1", "sub-A_ses-2", "sub-B_ses-1", "sub-C_ses-1"]
    first = project.collections[0]
    assert first.attributes == {"mouse": "A", "day": "1"}
    assert first.fields["path"] == "data/sub-A/sub-A_ses-1.nwb" and first.fields["dir"] == "data/sub-A"


def test_an_explicit_list_fills_the_same_placeholders_and_may_state_attributes(tmp_path):
    spec = {"list": [{"title": "Day one", "path": "a.nwb", "video": "a.mkv", "attributes": {"mouse": "X"}},
                     {"key": "second", "path": "b.nwb"}]}
    found = discover(spec, tmp_path, {"day": r"(\w)\."})
    assert [c.key for c in found] == ["Day_one", "second"]
    assert found[0].attributes == {"day": "a", "mouse": "X"} and found[0].fields["video"] == "a.mkv"
    assert has_unfilled(fill({"path": "{video}"}, found[1].fields))        # the second has no video
    assert not has_unfilled(fill({"path": "{video}"}, found[0].fields))


def test_a_provider_must_be_named_once(tmp_path):
    with pytest.raises(ValueError, match="exactly one"):
        discover({}, tmp_path)
    with pytest.raises(ValueError, match="exactly one"):
        discover({"glob": "*", "list": []}, tmp_path)


def test_a_project_without_collections_is_one_unchanged_recording(tmp_path):
    (tmp_path / "p.yaml").write_text("name: single\nsources: {}\n", encoding="utf-8")
    project = load_project(tmp_path / "p.yaml")
    assert not project.multiple and project.collection.key == "default"


def test_an_unknown_collection_is_refused_with_the_choices(project_path):
    with pytest.raises(ValueError, match="sub-A_ses-1"):
        load_project(project_path, "nope")


def test_a_source_whose_file_is_missing_is_left_out_not_an_error(project_path):
    project = load_project(project_path, "sub-B_ses-1")
    assert "session" in project.sources and "video" not in project.sources


# -- switching --------------------------------------------------------------------------------
def test_the_window_opens_the_first_collection_with_a_picker_and_names_it(window):
    assert window.project.collection.key == "sub-A_ses-1"
    bar = window.collection_bar
    assert bar.picker.count() == 4 and "sub-A_ses-1" in window.windowTitle()
    assert window.context.navigator.count == 3


def test_switching_replaces_the_segments_the_views_and_the_timeline_range(window, qapp):
    nav, tl = window.context.navigator, window.context.timeline
    assert tl.stop == pytest.approx(5.0, abs=0.1)
    assert window.switch_collection(_index(window, "sub-B_ses-1"))
    _pump(qapp)
    assert window.project.collection.key == "sub-B_ses-1" and "sub-B_ses-1" in window.windowTitle()
    assert nav.count == 2 and nav.intervals.attributes["stimulus"].tolist() == ["convex", "concave"]
    assert tl.stop == pytest.approx(8.0, abs=0.1)
    assert len(window.views) == 3 and window.context.resources is window.project.resources


def test_a_collection_without_a_source_keeps_the_panel_and_says_there_is_no_data(window, qapp):
    window.switch_collection(_index(window, "sub-B_ses-1"))
    _pump(qapp)
    clip = next(v for v in window.views if v.title == "Clip")
    assert clip.type_name == "placeholder" and clip.isVisible()
    assert "Clip" not in window.context.extents and "Clip" not in window.context.stepper.bases
    window.switch_collection(_index(window, "sub-A_ses-1"))
    _pump(qapp)
    assert next(v for v in window.views if v.title == "Clip").type_name == "video"      # and it comes back
    assert "Clip" in window.context.extents


def test_the_filter_options_follow_the_new_collections_segments(window):
    box = window.filter_bar._filters["stimulus"]
    assert [box.itemData(i) for i in range(box.count())] == [None, "concave", "convex"]
    window.switch_collection(_index(window, "sub-A_ses-2"))
    assert [box.itemData(i) for i in range(box.count())] == [None, "concave"]
    assert not window.context.navigator.filtered


def test_returning_to_a_collection_finds_the_playhead_where_it_was(window, qapp):
    window.context.bus.publish(Seek(3.5))
    window.switch_collection(_index(window, "sub-A_ses-2"))
    window.context.bus.publish(Seek(1.0))
    window.switch_collection(_index(window, "sub-A_ses-1"))
    assert window.context.timeline.time == pytest.approx(3.5, abs=0.02)
    window.switch_collection(_index(window, "sub-A_ses-2"))
    assert window.context.timeline.time == pytest.approx(1.0, abs=0.02)


def test_playback_stops_when_another_collection_opens(window):
    window.context.bus.publish(Seek(0.2))
    window.context.timeline.set_playing(True)
    window.switch_collection(_index(window, "sub-A_ses-2"))
    assert not window.context.timeline.playing


def test_a_collection_that_cannot_be_opened_leaves_everything_as_it_was(window):
    before = (window.project.collection.key, window.context.navigator.count, len(window.views))
    assert not window.switch_collection(_index(window, "sub-C_ses-1"))          # it has no trials
    assert (window.project.collection.key, window.context.navigator.count, len(window.views)) == before
    assert "sub-C_ses-1" in window.statusBar().currentMessage()


def test_what_the_user_removed_or_added_carries_over_to_the_next_collection(window):
    window.remove_view(next(v for v in window.views if v.title == "Events"))
    window.add_view({"type": "timeseries", "title": "Another", "series": {"from": "session:processing/behavior/whisker", "member": "angle"}})
    window.switch_collection(_index(window, "sub-A_ses-2"))
    titles = [v.title for v in window.views]
    assert "Events" not in titles and "Another" in titles and "Clip" in titles


def test_the_info_panel_names_the_open_collection_and_its_attributes(window):
    window.switch_collection(_index(window, "sub-B_ses-1"))
    text = window.info.toPlainText()
    assert "Session: sub-B_ses-1" in text and "mouse: B" in text and "none in this session" in text


# -- the collection filters -------------------------------------------------------------------
def test_filters_on_collection_attributes_limit_the_picker_and_previous_next(window):
    bar = window.collection_bar
    mouse = bar._filters["mouse"]
    mouse.setCurrentIndex(mouse.findData("A"))
    assert [bar.picker.itemData(i) for i in range(bar.picker.count())] == [0, 1]
    assert bar._neighbor(+1) == 1 and bar._neighbor(-1) is None
    bar.step(+1)
    assert window.project.collection.key == "sub-A_ses-2"
    assert bar._neighbor(+1) is None                      # the next one overall is mouse B, which the filter hides


def test_a_filter_that_excludes_the_open_collection_moves_to_the_nearest_match(window):
    bar = window.collection_bar
    mouse = bar._filters["mouse"]
    mouse.setCurrentIndex(mouse.findData("B"))
    assert window.project.collection.key == "sub-B_ses-1"


def test_filter_options_show_how_many_collections_each_would_leave(window):
    mouse = window.collection_bar._filters["mouse"]
    assert [mouse.itemText(i) for i in range(mouse.count())] == ["All (4)", "A (2)", "B (1)", "C (1)"]


def test_collection_controls_are_marked_for_the_workspace(window):
    bar = window.collection_bar
    assert bar.picker.property("workspace").startswith("not saved")
    assert all(box.property("workspace") == "saved" for box in bar._filters.values())


def test_collection_filters_are_saved_in_a_workspace_and_restored(window, qapp):
    mouse = window.collection_bar._filters["mouse"]
    mouse.setCurrentIndex(mouse.findData("A"))
    window.save_workspace_as("Mouse A")
    path = window.project.path
    window.close()
    again = build_window(path, workspace_name="Mouse A")
    try:
        assert again.collection_bar._filters["mouse"].currentData() == "A"
        assert again.project.collection.key == "sub-A_ses-1"
    finally:
        again.close()


# -- remembered between runs --------------------------------------------------------------------
def test_the_playhead_in_each_collection_is_saved_with_the_workspace_and_restored(window, qapp):
    window.context.bus.publish(Seek(3.5))
    window.save_workspace_as("Mine")
    path = window.project.path
    window.close()
    again = build_window(path, workspace_name="Mine")
    try:
        assert again.context.timeline.time == pytest.approx(3.5, abs=0.02)
    finally:
        again.close()


def test_a_collection_can_be_chosen_on_opening(project_path, qapp):
    window = build_window(project_path, collection="sub-B_ses-1")
    try:
        assert window.project.collection.key == "sub-B_ses-1" and window.context.navigator.count == 2
    finally:
        window.close()


def test_the_project_file_can_name_the_collection_to_open_first(project_path, qapp):
    project_path.write_text(project_path.read_text(encoding="utf-8") + "\ncollection: sub-A_ses-2\n", encoding="utf-8")
    window = build_window(project_path)
    try:
        assert window.project.collection.key == "sub-A_ses-2"
    finally:
        window.close()


def test_every_input_control_in_the_collection_bar_is_marked(window):
    from PySide6.QtWidgets import QComboBox

    unmarked = [b for b in window.collection_bar.findChildren(QComboBox) if not b.property("workspace")]
    assert not unmarked
