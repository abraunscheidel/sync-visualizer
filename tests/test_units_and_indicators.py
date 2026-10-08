"""Spike units read from NWB, and the indicator lights that show them at the playhead."""

import os
from datetime import datetime, timezone

import numpy as np
import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralTimeSeries
from PySide6.QtWidgets import QApplication

from syncviz.sources import MissingDataError
from syncviz_app.app import build_window
from syncviz_app.views.indicators import IndicatorsView
from syncviz_app.views.rows import glow_after_events, glow_during_intervals
from syncviz_app.views.tracks import TracksView
from syncviz_nwb import NWBSource

# unit id, depth, layer, spike times  (ids and depths are deliberately not in the same order)
UNITS = [(7, 437.0, "4", [1.0, 2.0, 2.01, 5.0]), (12, 917.0, "5b", [3.0]), (130, 357.0, "2/3", [0.5, 4.0])]


def _write_nwb(path, units=True):
    nwb = NWBFile(session_description="s", identifier="u", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    if units:
        nwb.add_unit_column(name="depth", description="microns")
        nwb.add_unit_column(name="layer", description="layer")
        nwb.add_unit_column(name="inhibitory", description="guess")
        for uid, depth, layer, spikes in UNITS:
            nwb.add_unit(id=uid, spike_times=spikes, depth=depth, layer=layer, inhibitory=uid == 12)
    behavior = nwb.create_processing_module("behavior", "b")
    series = BehavioralTimeSeries(name="whisker")
    t = np.arange(0, 6, 1 / 50)
    series.create_timeseries(name="angle", data=np.sin(t), unit="degrees", timestamps=t)
    behavior.add(series)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)
    return path


@pytest.fixture
def nwb_path(tmp_path):
    return _write_nwb(tmp_path / "s.nwb")


# -- reading units -------------------------------------------------------------------------------
def test_each_unit_becomes_an_event_series_named_by_its_id_with_its_columns_as_metadata(nwb_path):
    units = NWBSource(nwb_path).read_events("units")
    assert set(units) == {"7", "12", "130"}
    np.testing.assert_allclose(units["7"].times, [1.0, 2.0, 2.01, 5.0])
    assert units["7"].metadata == {"depth": 437.0, "layer": "4", "inhibitory": False}
    assert units["12"].metadata["inhibitory"] is True


def test_units_are_listed_and_offered_shallowest_first_with_readable_labels(nwb_path):
    source = NWBSource(nwb_path)
    assert "units" in source.describe()
    entry = next(e for e in source.catalog() if e.path == "units")
    assert entry.kind == "events" and entry.members == ("130", "7", "12")
    assert entry.labels == {"130": "Unit 130 · L2/3", "7": "Unit 7 · L4", "12": "Unit 12 · L5b"}


def test_a_file_without_units_says_so_calmly(tmp_path):
    source = NWBSource(_write_nwb(tmp_path / "none.nwb", units=False))
    assert "units" not in source.describe() and all(e.path != "units" for e in source.catalog())
    with pytest.raises(MissingDataError):
        source.read_events("units")


# -- the lights ---------------------------------------------------------------------------------
def test_an_event_lights_fully_and_fades_over_the_decay_time():
    times = np.array([1.0, 2.0])
    assert glow_after_events(times, 1.0, 0.2) == 1.0
    assert glow_after_events(times, 1.1, 0.2) == pytest.approx(0.5)
    assert glow_after_events(times, 1.2, 0.2) == pytest.approx(0.0, abs=1e-9)
    assert glow_after_events(times, 1.5, 0.2) == 0.0


def test_an_event_that_has_not_happened_yet_shows_nothing_so_scrubbing_back_unlights_it():
    times = np.array([1.0])
    assert glow_after_events(times, 0.99, 0.2) == 0.0
    assert glow_after_events(times, 1.05, 0.2) > 0.0 and glow_after_events(times, 0.5, 0.2) == 0.0


def test_the_brightness_depends_only_on_the_playhead_not_on_how_it_got_there():
    times = np.array([1.0, 2.0, 2.01])
    forward = [glow_after_events(times, t, 0.15) for t in (0.5, 1.05, 2.005, 2.05)]
    backward = [glow_after_events(times, t, 0.15) for t in (2.05, 2.005, 1.05, 0.5)][::-1]
    assert forward == backward


def test_an_interval_is_lit_while_inside_it_and_fades_after_it_ends():
    starts, stops = np.array([1.0, 5.0]), np.array([2.0, 6.0])
    assert glow_during_intervals(starts, stops, 0.5, 0.2) == 0.0
    assert glow_during_intervals(starts, stops, 1.5, 0.2) == 1.0
    assert glow_during_intervals(starts, stops, 2.1, 0.2) == pytest.approx(0.5)
    assert glow_during_intervals(starts, stops, 3.0, 0.2) == 0.0
    assert glow_during_intervals(starts, stops, 5.5, 0.2) == 1.0


# -- offered in Add view and shown ---------------------------------------------------------------
def test_both_row_views_offer_the_units_in_depth_order_named_by_their_labels(nwb_path):
    catalog = {"session": NWBSource(nwb_path).catalog()}
    for view in (IndicatorsView, TracksView):
        candidate = next(c for c in view.candidates(catalog) if c.spec["title"] == "Units")
        assert [r["name"] for r in candidate.spec["rows"]] == ["Unit 130 · L2/3", "Unit 7 · L4", "Unit 12 · L5b"]
        assert all(r["from"] == "session:units" and r["kind"] == "events" for r in candidate.spec["rows"])


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(nwb_path, tmp_path, qapp):
    (tmp_path / "project.yaml").write_text(f"""
name: units
sources:
  session: {{type: nwb, path: "{nwb_path.as_posix()}"}}
views:
  - type: timeseries
    title: Angle
    series: {{from: "session:processing/behavior/whisker", member: angle}}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml", use_workspace=False)
    w.show()
    yield w
    w.close()


def _add_units(window, **extra):
    candidate = next(c for c in IndicatorsView.candidates(window.source_catalog()) if c.spec["title"] == "Units")
    return window.add_view({**candidate.spec, **extra})


def test_the_units_view_lights_the_unit_that_just_fired_and_not_the_others(window):
    view = _add_units(window)
    assert view.type_name == "indicators" and view.extent() == (0.5, 5.0)
    levels = dict(zip([r["name"] for r in view.rows], view.levels_at(3.0)))      # unit 12 fires at 3.0
    assert levels["Unit 12 · L5b"] == 1.0 and levels["Unit 7 · L4"] == 0.0 and levels["Unit 130 · L2/3"] == 0.0
    later = dict(zip([r["name"] for r in view.rows], view.levels_at(3.075)))      # halfway through the 0.15 s fade
    assert later["Unit 12 · L5b"] == pytest.approx(0.5)


def test_a_spike_between_two_redraws_still_shows_as_a_glow(window):
    view = _add_units(window)
    view.refresh(1.9)
    assert not view.lamps.levels.any()
    view.refresh(2.012)                          # redraws skipped the spikes at 2.0 and 2.01; both are recent
    assert view.lamps.levels.max() > 0.8


def test_the_decay_and_the_columns_come_from_the_spec(window):
    view = _add_units(window, decay=1.0, columns=2)
    assert view.decay == 1.0 and view.lamps.columns == 2
    assert dict(zip([r["name"] for r in view.rows], view.levels_at(3.5)))["Unit 12 · L5b"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        IndicatorsView(window.context, {"type": "indicators", "decay": 0, "rows": []})


def test_with_no_column_count_the_lamps_flow_into_more_columns_when_the_panel_is_short(window):
    view = _add_units(window)
    lamps = view.lamps
    assert lamps.columns is None
    assert lamps.effective_columns(width=400, height=400) == 1             # 3 lamps fit comfortably in one column
    assert lamps.effective_columns(width=400, height=40) == 2             # too short: split
    assert lamps.effective_columns(width=150, height=40) == 1             # too narrow to split
    forced = _add_units(window, columns=3)
    assert forced.lamps.effective_columns(width=400, height=400) == 3      # the project's choice wins


def test_the_lamps_really_draw_brighter_when_lit(window, qapp):
    view = _add_units(window)
    view.resize(300, 240)
    view.show()
    view.refresh(0.2)
    dark = view.grab().toImage()
    view.refresh(3.0)
    lit = view.grab().toImage()
    assert dark != lit


def test_it_appears_in_the_timeline_coverage_and_the_views_panel(window):
    view = _add_units(window)
    assert view.title in window.context.extents and window.context.colors[view.title]
    assert any(window.views_panel.list.item(i).text() == view.title for i in range(window.views_panel.list.count()))
