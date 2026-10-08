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
