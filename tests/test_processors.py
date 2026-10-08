"""Processors derive new series from existing ones; the population rate turns spikes into activity over time."""

import numpy as np
import pytest

from syncviz import processors
from syncviz.core import Seek
from syncviz.resources import EventSeries, TimeSeries
from syncviz.sources import DataEntry
from syncviz_app.views.timeseries import TimeSeriesView

from test_units_and_indicators import nwb_path, qapp, window          # noqa: F401  (fixtures)


def _events(*times):
    return EventSeries(times=np.array(times, dtype=float))


# -- the computation ------------------------------------------------------------------------------
def test_without_smoothing_each_bin_is_its_count_over_the_bin_length_and_the_number_of_members():
    a, b = _events(0.005, 0.006, 0.025), _events(0.015)
    out = processors.PopulationRate().run([a, b], bin_ms=10, smooth_ms=0)
    assert isinstance(out, TimeSeries) and out.unit == "events/s per member"
    by_bin = dict(zip(np.round(out.times, 3), out.values))
    assert by_bin[0.005] == pytest.approx(2 / 0.010 / 2)          # two spikes in the first 10 ms bin, two members
    assert by_bin[0.015] == pytest.approx(1 / 0.010 / 2)
    assert by_bin[0.025] == pytest.approx(1 / 0.010 / 2)


def test_the_rate_is_per_member_unless_asked_not_to_be():
    a, b = _events(0.005), _events(0.005)
    per = processors.PopulationRate().run([a, b], bin_ms=10, smooth_ms=0)
    total = processors.PopulationRate().run([a, b], bin_ms=10, smooth_ms=0, per_member=False)
    assert per.values.max() == pytest.approx(total.values.max() / 2) and total.unit == "events/s"


@pytest.mark.parametrize("smoothing", ["trailing", "centered"])
@pytest.mark.parametrize("smooth_ms", [0, 20, 50, 200])
def test_smoothing_keeps_the_total_number_of_events(smooth_ms, smoothing):
    rng = np.random.default_rng(1)
    spikes = [_events(*np.sort(rng.uniform(5, 15, 400))) for _ in range(5)]
    out = processors.PopulationRate().run(spikes, bin_ms=10, smooth_ms=smooth_ms, smoothing=smoothing, per_member=False)
    assert out.values.sum() * 0.010 == pytest.approx(2000, rel=1e-9)


def test_a_burst_shows_as_a_peak_at_the_burst_and_smoothing_spreads_it():
    burst = _events(*np.linspace(10.0, 10.02, 50))
    sharp = processors.PopulationRate().run([burst, _events(0.0, 20.0)], bin_ms=5, smooth_ms=0)
    soft = processors.PopulationRate().run([burst, _events(0.0, 20.0)], bin_ms=5, smooth_ms=40, smoothing="centered")
    assert abs(sharp.times[np.argmax(sharp.values)] - 10.01) < 0.01
    assert abs(soft.times[np.argmax(soft.values)] - 10.01) < 0.02
    assert soft.values.max() < sharp.values.max()


def test_trailing_smoothing_never_lets_the_rate_rise_before_the_event_that_causes_it():
    out = processors.PopulationRate().run([_events(10.0)], bin_ms=5, smooth_ms=30, smoothing="trailing")
    before = out.values[out.times < 10.0 - 1e-9]
    assert (before == 0).all()                                            # nothing at all before the spike
    peak = out.times[np.argmax(out.values)]
    assert 10.0 <= peak < 10.005 + 1e-9                                   # the peak is in the spike's own bin
    after = out.values[out.times > peak]
    assert after[0] > after[5] > after[10] > 0                            # then it decays smoothly


def test_centered_smoothing_does_spread_backwards_which_is_why_it_is_not_the_default():
    out = processors.PopulationRate().run([_events(10.0)], bin_ms=5, smooth_ms=30, smoothing="centered")
    assert out.values[out.times < 9.95].max() > 0


def test_trailing_is_the_default_and_a_step_is_seen_at_the_step_not_before_it():
    steady = _events(*np.arange(0.0, 10.0, 0.1))
    burst = _events(*np.arange(5.0, 10.0, 0.01))
    out = processors.PopulationRate().run([steady, burst], bin_ms=10, smooth_ms=20, per_member=False)
    early = out.values[(out.times > 1) & (out.times < 4.5)].mean()
    just_before = out.values[(out.times > 4.5) & (out.times < 4.995)].mean()
    assert just_before == pytest.approx(early, rel=0.3)                   # no early rise
    assert out.values[(out.times > 5.1) & (out.times < 9)].mean() > 5 * early


def test_an_unknown_smoothing_mode_is_refused():
    with pytest.raises(ValueError, match="smoothing"):
        processors.PopulationRate().run([_events(1.0)], smoothing="sideways")


def test_the_series_has_regular_bins_and_room_for_the_smoothing():
    out = processors.PopulationRate().run([_events(1.0, 2.0)], bin_ms=10, smooth_ms=50)
    assert np.allclose(np.diff(out.times), 0.010)
    assert out.times[0] <= 1.0 + 0.005 and out.times[-1] > 2.0 + 0.05


def test_bad_parameters_and_no_events_are_refused_with_a_reason():
    with pytest.raises(ValueError, match="no events"):
        processors.PopulationRate().run([_events()])
    with pytest.raises(ValueError, match="bin_ms"):
        processors.PopulationRate().run([_events(1.0)], bin_ms=0)
    with pytest.raises(ValueError, match="smooth_ms"):
        processors.PopulationRate().run([_events(1.0)], smooth_ms=-1)


def test_processors_are_found_by_name_and_an_unknown_one_lists_the_choices():
    assert processors.get("population_rate") is processors.PopulationRate
    with pytest.raises(KeyError, match="population_rate"):
        processors.get("nope")


# -- offered in Add view ----------------------------------------------------------------------------------
def test_a_group_of_event_rows_offers_a_combined_rate_and_a_single_row_does_not():
    catalog = {"s": [DataEntry("units", "events", ("1", "2", "3")), DataEntry("lone", "events", ("only",)),
                     DataEntry("sig", "timeseries", ("x", "y"))]}
    offered = processors.PopulationRate.candidates(catalog)
    assert [(title, spec["inputs"]) for _label, title, spec in offered] == [("Units rate", ["s:units"])]
    candidates = TimeSeriesView.candidates(catalog)
    assert any(c.spec["series"].get("process") == "population_rate" for c in candidates)
    assert any(c.spec["series"].get("member") == "x" for c in candidates)            # ordinary series still offered


# -- in the application -------------------------------------------------------------------------------------
def _add_rate(window, **params):
    candidate = next(c for c in TimeSeriesView.candidates(window.source_catalog())
                     if c.spec["series"].get("process") == "population_rate")
    spec = {**candidate.spec, "series": {**candidate.spec["series"], **params}}
    return window.add_view(spec)


def test_the_rate_view_plots_the_units_combined_activity(window, qapp):
    view = _add_rate(window)
    qapp.processEvents()
    assert view.type_name == "timeseries" and view.title == "Units rate"
    assert view.series.unit == "events/s per member"
    assert view.extent()[0] <= 0.51 and view.extent()[1] > 5.0                    # starts at the first spike (0.5) and runs a little past the last (5.0)
    window.context.bus.publish(Seek(2.0))
    window.refresh_now()
    x, y = view.curve.getData()
    assert len(x) > 0 and np.isfinite(y).all()


def test_the_series_equals_the_hand_count_of_the_synthetic_units(window):
    view = _add_rate(window, smooth_ms=0, bin_ms=10)
    series = view.series
    # units: 4 + 1 + 2 spikes over 3 members = 7 spikes in total
    assert series.values.sum() * 0.010 * 3 == pytest.approx(7)


def test_parameters_in_the_spec_reach_the_processor(window):
    fine = _add_rate(window, bin_ms=5, smooth_ms=0)
    assert np.allclose(np.diff(fine.series.times), 0.005)


def test_the_same_derived_series_is_computed_once_and_shared(window):
    first = _add_rate(window)
    second = window.add_view({"type": "timeseries", "title": "Again", "series": dict(first.spec["series"])})
    assert second.series is first.series


def test_a_view_whose_inputs_are_missing_keeps_its_panel_and_says_so(window):
    view = window.add_view({"type": "timeseries", "title": "Nothing",
                            "series": {"process": "population_rate", "inputs": ["session:processing/behavior/nothing"]}})
    assert view.type_name == "placeholder"


def test_a_view_naming_an_unknown_processor_is_skipped_with_a_note(window):
    before = len(window.views)
    assert window.add_view({"type": "timeseries", "title": "Odd", "series": {"process": "nope", "inputs": []}}) is None
    assert len(window.views) == before and any("nope" in n for n in window.context.notes)
