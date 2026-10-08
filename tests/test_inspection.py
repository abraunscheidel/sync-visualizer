"""Inspecting data: views point at things, the inspector says what is known, and hovering shows it (design doc 28.7)."""

import os

import numpy as np
import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication

from syncviz.inspection import (
    Scope, Target, WHOLE, event_fields, interval_fields, timeseries_fields,
)
from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries
from syncviz.resources.timeseries import TimeSeries
from syncviz_app.app import build_window
from syncviz_app.views.indicators import IndicatorsView
from syncviz_app.views.tracks import TracksView

from test_units_and_indicators import _write_nwb


def _values(fields):
    return {f.name: f.value for f in fields}


# -- statistics, by resource type -------------------------------------------------------------------------
def test_event_statistics_count_the_scope_and_say_how_much_there_is_in_all():
    series = EventSeries(times=np.array([1.0, 2.0, 2.01, 5.0]), metadata={"depth": 437.0, "layer": "4"})
    values = _values(event_fields(series, Scope("this trial", 0.0, 4.0)))
    assert values["Events (this trial)"] == "3"
    assert values["Rate (this trial)"] == "0.75 per second"
    assert values["Events (whole recording)"] == "4"
    assert values["depth"] == "437" and values["layer"] == "4"        # what the source attached is shown as given


def test_the_whole_recording_scope_is_the_default_and_adds_no_second_count():
    values = _values(event_fields(EventSeries(times=np.array([0.0, 2.0]))))
    assert values["Events (whole recording)"] == "2" and len([k for k in values if k.startswith("Events")]) == 1


def test_a_series_with_nothing_in_it_says_so():
    assert _values(event_fields(EventSeries(times=np.array([])))) == {"Events": "0"}


def test_interval_and_time_series_statistics():
    trials = IntervalSeries(np.array([0.0, 5.0]), np.array([4.0, 6.0]))
    values = _values(interval_fields(trials, Scope("this trial", 0.0, 4.5)))
    assert values["Intervals (this trial)"] == "1" and values["Intervals (whole recording)"] == "2"
    t = np.arange(0, 10, 0.1)
    series = TimeSeries(t, np.sin(t), unit="degrees")
    values = _values(timeseries_fields(series, Scope("this trial", 0.0, 1.0)))
    assert values["Highest (this trial)"].endswith("degrees") and float(values["Highest (this trial)"].split()[0]) < 0.9


# -- the application's inspector -------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, qapp):
    nwb = _write_nwb(tmp_path / "s.nwb")
    (tmp_path / "project.yaml").write_text(f"""
name: inspected
sources:
  session: {{type: nwb, path: "{nwb.as_posix()}"}}
glossary:
  Unit 12 · L5b: "A deep unit."
views:
  - type: timeseries
    title: Angle
    series: {{from: "session:processing/behavior/whisker", member: angle}}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml", use_workspace=False)
    w.show()
    yield w
    w.close()


def _units(window):
    candidate = next(c for c in IndicatorsView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    return window.add_view(candidate.spec)


def test_the_inspector_describes_a_unit_from_its_metadata_the_glossary_and_statistics(window):
    view = _units(window)
    row = next(r for r in view.rows if r["name"] == "Unit 12 · L5b")
    from syncviz_app.views.rows import row_target
    details = window.context.inspector.details(row_target(row["spec"]))
    assert details.description == "A deep unit."
    values = _values(details.fields)
    assert values["depth"] == "917" and values["layer"] == "5b" and values["Events (whole recording)"] == "1"


def test_hovering_a_tile_shows_that_units_description_and_brief_statistics(window):
    view = _units(window)
    view.resize(600, 400)
    rect = next(r for r, row in zip(view.lamps.tile_rects(), view.rows) if row["name"] == "Unit 12 · L5b")
    text = view.hover_text(view.lamps.mapTo(view, QPoint(int(rect.center().x()), int(rect.center().y()))))
    assert text.startswith("Unit 12 · L5b") and "A deep unit." in text and "Events" in text
    assert "depth" not in text                                       # only the brief figures; the rest is for the full panel


def test_the_pointer_outside_every_tile_points_at_nothing(window):
    view = _units(window)
    view.resize(600, 400)
    assert view.target_at(QPoint(-5, -5)) is None


def test_a_tracks_row_names_its_data_and_an_event_under_the_pointer_gives_its_time(window):
    candidate = next(c for c in TracksView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    view = window.add_view(candidate.spec)
    view.resize(800, 400)
    view.refresh(3.0)
    app = QApplication.instance()
    app.processEvents()
    row = view.rows[0]                                                # the shallowest unit
    viewbox = view.plot.getPlotItem().vb
    # a point in the row's band, at the time of one of its events
    event = float(row["data"][0])
    scene = viewbox.mapViewToScene(pytest.importorskip("pyqtgraph").Point(event, row["y"]))
    pos = view.plot.viewport().mapTo(view, view.plot.mapFromScene(scene))
    target = view.target_at(pos)
    assert isinstance(target, Target) and target.kind == "events" and target.time == pytest.approx(event)
    assert target.source == "session"


def test_the_time_series_view_points_at_its_series(window):
    view = next(v for v in window.views if v.title == "Angle")
    target = view.target_at(QPoint(10, 10))
    assert target.member == "angle" and target.kind == "timeseries"
    text = view.hover_text(QPoint(10, 10))
    assert "Lowest" in text and "Highest" in text and "degrees" in text


def test_statistics_are_worked_out_over_the_current_segment_when_there_are_segments(window):
    scope = window.context.inspector.scope()
    assert scope is WHOLE or scope.label == "whole recording"        # this project has no segmentation


# -- selection and the details panel (step 2) ------------------------------------------------------------------
class _Click:
    """Just enough of a pyqtgraph mouse click."""

    def __init__(self, scene, double=False):
        self._scene, self._double = scene, double

    def button(self):
        from PySide6.QtCore import Qt
        return Qt.MouseButton.LeftButton

    def scenePos(self):
        return self._scene

    def double(self):
        return self._double


def _scene_point(view, x, y):
    import pyqtgraph as pg
    return view.plot.getPlotItem().vb.mapViewToScene(pg.Point(x, y))


def _tile_centre(view, name):
    rect = next(r for r, row in zip(view.lamps.tile_rects(), view.rows) if row["name"] == name)
    return view.lamps.mapTo(view, QPoint(int(rect.center().x()), int(rect.center().y())))


def test_clicking_a_tile_selects_it_and_shows_its_details_without_moving_time(window):
    view = _units(window)
    view.resize(600, 400)
    before = window.context.timeline.time
    assert view.select_at(_tile_centre(view, "Unit 12 · L5b"))
    selected = window.context.selection.target
    assert selected.member == "12" and window.context.timeline.time == before
    panel = window.details_panel
    assert panel.title.text() == "Unit 12 · L5b" and panel.description.text() == "A deep unit."
    names = [panel.tree.topLevelItem(g).child(c).text(0) for g in range(panel.tree.topLevelItemCount())
             for c in range(panel.tree.topLevelItem(g).childCount())]
    assert "depth" in names and "layer" in names                  # everything is in the panel, not only the brief figures
    assert view.lamps.selected == view.rows.index(next(r for r in view.rows if r["name"] == "Unit 12 · L5b"))


def test_the_selected_row_is_marked_in_the_tracks_view_and_clearing_unmarks_it(window):
    candidate = next(c for c in TracksView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    tracks = window.add_view(candidate.spec)
    tracks.resize(800, 400)
    tracks.refresh(3.0)
    QApplication.instance().processEvents()
    window.context.selection.set(__import__("syncviz_app.views.rows", fromlist=["row_target"]).row_target(tracks.rows[1]["spec"]))
    assert tracks.band.isVisible() and tracks.band.getRegion() == (tracks.rows[1]["y"] - 0.5, tracks.rows[1]["y"] + 0.5)
    window.context.selection.clear()
    assert not tracks.band.isVisible() and window.details_panel.title.text().startswith("Click something")


def test_a_click_selects_where_there_is_something_and_a_double_click_seeks(window):
    view = next(v for v in window.views if v.title == "Angle")
    view.resize(800, 300)
    view.refresh(3.0)                                              # centre the window on 3 s
    QApplication.instance().processEvents()
    scene = _scene_point(view, 3.0, 0.0)
    timeline = window.context.timeline
    start = timeline.time
    view._clicked(_Click(scene))
    assert window.context.selection.target.member == "angle" and timeline.time == start
    view._clicked(_Click(scene, double=True))
    assert timeline.time == pytest.approx(3.0, abs=0.05)


def test_a_point_outside_every_row_points_at_nothing_so_a_click_there_seeks(window):
    candidate = next(c for c in TracksView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    tracks = window.add_view(candidate.spec)
    tracks.resize(800, 400)
    tracks.refresh(3.0)
    QApplication.instance().processEvents()
    far_above = _scene_point(tracks, 2.0, len(tracks.rows) + 5)
    assert tracks.target_at(tracks.plot.mapTo(tracks, tracks.plot.mapFromScene(far_above))) is None


def test_the_figures_a_hover_shows_are_the_users_choice_and_are_saved_in_the_workspace(window):
    view = _units(window)
    view.resize(600, 400)
    centre = _tile_centre(view, "Unit 12 · L5b")
    assert "depth" not in view.hover_text(centre)
    view.select_at(centre)
    panel = window.details_panel
    from PySide6.QtWidgets import QCheckBox
    boxes = panel.tree.findChildren(QCheckBox)
    depth = next(i for i, f in enumerate(window.context.inspector.details(window.context.selection.target).fields) if f.key == "file:depth")
    boxes[depth].setChecked(True)
    assert "depth: 917" in view.hover_text(centre)
    saved = window.settings()["inspection"]["hover"]
    assert "file:depth" in saved
    window.context.inspector.hover_keys = None
    window._apply_settings({"inspection": {"hover": saved}})
    assert "depth: 917" in view.hover_text(centre)


def test_a_source_can_add_facts_only_it_knows(window):
    source = window.context.resources.source("session")
    from syncviz.inspection import Field
    source.details = lambda target: [Field("Isolation", "good", "From the recording system")]
    view = _units(window)
    view.resize(600, 400)
    view.select_at(_tile_centre(view, "Unit 12 · L5b"))
    values = _values(window.context.inspector.details(window.context.selection.target).fields)
    assert values["Isolation"] == "good"


# -- actions and the context menu (step 3) -----------------------------------------------------------------------
def _tracks(window):
    candidate = next(c for c in TracksView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    view = window.add_view(candidate.spec)
    view.resize(800, 400)
    view.refresh(3.0)
    QApplication.instance().processEvents()
    return view


def _labels(actions):
    return [a.label for a in actions]


def test_a_target_is_offered_only_the_actions_that_apply_to_it(window):
    registry = window.context.actions
    row = Target("session", "units", "events", "12", "Unit 12")
    labels = _labels(registry.for_target(row))
    assert "Select" in labels and "Copy details" in labels and "Show details" in labels
    assert "Go to this time" not in labels                          # a whole row has no moment of its own
    assert "Clear selection" not in labels                           # and it is not selected
    moment = Target("session", "units", "events", "12", "Unit 12", time=3.0)
    assert "Go to this time" in _labels(registry.for_target(moment))
    window.context.selection.set(row)
    assert "Clear selection" in _labels(registry.for_target(row))


def test_open_as_view_is_a_submenu_listing_each_way_the_target_can_be_shown(window):
    registry = window.context.actions
    events = registry.get("open_as_view")
    names = _labels(events.children(Target("session", "units", "events", "12", "Unit 12")))
    assert {"Events and intervals", "Indicator lights"} <= set(names) and "Time series plot" not in names
    series = _labels(events.children(Target("session", "processing/behavior/whisker", "timeseries", "angle", "Angle")))
    assert series == ["Time series plot"]
    assert events.children(Target("session", "x", "points", None, "pose")) == []


def test_opening_a_target_as_a_view_adds_that_view(window):
    before = len(window.views)
    registry = window.context.actions
    target = Target("session", "units", "events", "12", "Unit 12")
    child = next(a for a in registry.get("open_as_view").children(target) if a.label == "Indicator lights")
    child.run(target, None)
    assert len(window.views) == before + 1 and window.views[-1].type_name == "indicators"
    assert window.views[-1].rows[0]["name"] == "Unit 12"


def test_the_menu_is_built_from_the_registry_with_a_submenu_and_its_shortcut_shown(window):
    from PySide6.QtWidgets import QMenu
    from syncviz_app.target_actions import build_menu
    registry = window.context.actions
    target = Target("session", "units", "events", "12", "Unit 12")
    window.context.selection.set(target)
    menu = build_menu(registry.for_target(target), target, None)
    texts = {a.text().split("\t")[0] for a in menu.actions()}
    assert {"Select", "Show details", "Open as view", "Copy details", "Clear selection"} <= texts
    assert next(a for a in menu.actions() if a.text().startswith("Open as view")).menu().actions()
    assert next(a for a in menu.actions() if a.text().startswith("Clear")).text().endswith("Esc")


def test_the_context_menu_of_a_view_is_for_what_is_under_the_pointer(window, monkeypatch):
    view = _units(window)
    view.resize(600, 400)
    shown = []
    import syncviz_app.views.base as base
    monkeypatch.setattr(base, "build_menu", lambda actions, target, origin, parent: type(
        "M", (), {"exec": lambda self, pos: shown.append((target.member, [a.label for a in actions]))})())
    view.show_menu(_tile_centre(view, "Unit 12 · L5b"), None)
    view.show_menu(QPoint(-5, -5), None)                              # nothing there: no menu
    assert len(shown) == 1 and shown[0][0] == "12" and "Select" in shown[0][1]


def test_clicks_run_the_actions_the_project_binds_to_them(window):
    window.context.actions.bindings["click"] = "show_details"
    window.context.actions.bindings["double_click"] = "copy_details"
    view = _units(window)
    view.resize(600, 400)
    view._pressed(view.lamps.mapFrom(view, _tile_centre(view, "Unit 12 · L5b")), False)
    assert window.context.selection.target.member == "12"
    view._pressed(view.lamps.mapFrom(view, _tile_centre(view, "Unit 12 · L5b")), True)
    assert "Unit 12" in QApplication.clipboard().text()


def test_a_view_can_add_its_own_actions_and_they_apply_only_where_it_says(window):
    from syncviz_app.target_actions import TargetAction
    ran = []
    view = _units(window)
    view.target_actions = lambda: [TargetAction("jump", "Jump to next occurrence", lambda t, o: ran.append(t.member),
                                                applies=lambda t: t.kind == "events")]
    registry = window.context.actions
    assert "Jump to next occurrence" in _labels(registry.for_target(Target("session", "units", "events", "12")))
    assert "Jump to next occurrence" not in _labels(registry.for_target(Target("session", "x", "intervals")))
    assert registry.run("jump", Target("session", "units", "events", "12")) and ran == ["12"]


def test_seeking_from_the_pointer_time_on_a_shifted_view_adds_its_lag(window):
    view = next(v for v in window.views if v.title == "Angle")
    window.set_view_lag(view, 500.0)
    target = Target("session", "p", "timeseries", "angle", "Angle", at=2.0)
    assert window.context.actions.run("seek", target, view)
    assert window.context.timeline.time == pytest.approx(2.5)


def test_escape_clears_the_selection(window):
    from PySide6.QtGui import QShortcut
    window.context.selection.set(Target("session", "units", "events", "12", "Unit 12"))
    shortcut = next(s for s in window.findChildren(QShortcut) if s.key().toString() == "Esc")
    shortcut.activated.emit()
    assert window.context.selection.target is None


def test_the_time_under_the_pointer_does_not_make_two_targets_different_items(window):
    a = Target("session", "units", "events", "12", at=1.0)
    b = Target("session", "units", "events", "12", at=2.0)
    assert a == b
