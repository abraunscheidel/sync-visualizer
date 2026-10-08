"""Series too big to load are read a window at a time, and never in full."""

import os
import tracemalloc
from datetime import datetime, timezone

import numpy as np
import pytest

from syncviz.core import LazySampleTimes, RegularGrid, SampleTimes
from syncviz.resources import LazyTimeSeries, TimeSeries
from syncviz.resources.timeseries import bisect_array, minmax_indices


class Virtual:
    """An array of `n` samples that exists only as a formula, so a recording of any size can be
    tested without storing it. Records the largest single read."""

    def __init__(self, n, fn=lambda i: (i % 1000).astype(np.int16)):
        self.n, self.fn, self.largest_read, self.reads = n, fn, 0, 0

    def __len__(self):
        return self.n

    def __getitem__(self, key):
        if isinstance(key, slice):
            idx = np.arange(*key.indices(self.n), dtype=np.int64)
        else:
            idx = np.array([key if key >= 0 else key + self.n], dtype=np.int64)
        self.largest_read = max(self.largest_read, len(idx))
        self.reads += 1
        out = self.fn(idx)
        return out if isinstance(key, slice) else out[0]


# -- the resource ----------------------------------------------------------------------------
def test_a_window_of_a_huge_regular_series_reads_only_that_window():
    n = 3_400_000_000                                    # about 6.8 GB of int16: 31 hours at 30 kHz
    data = Virtual(n)
    series = LazyTimeSeries(data, start=100.0, rate=30_000.0)
    window = series.window(200.0, 200.01)
    assert len(window) == 300 and data.largest_read == 300
    assert window.times[0] == pytest.approx(200.0) and window.times[-1] == pytest.approx(200.01 - 1 / 30_000)
    assert series.first_time == 100.0 and series.last_time == pytest.approx(100.0 + (n - 1) / 30_000)
    assert series.count_between(200.0, 210.0) == 300_000


def test_a_lazy_window_equals_the_same_window_of_the_series_loaded_in_full():
    t = 5.0 + np.arange(20_000) / 1000.0
    v = np.sin(t)
    lazy, eager = LazyTimeSeries(v, start=5.0, rate=1000.0), TimeSeries(t, v)
    for lo, hi in [(5.0, 6.0), (7.3, 7.3004), (-10.0, 5.5), (24.0, 99.0), (30.0, 40.0)]:
        a, b = lazy.window(lo, hi), eager.window(lo, hi)
        np.testing.assert_allclose(a.times, b.times)
        np.testing.assert_allclose(a.values, b.values)
        assert lazy.count_between(lo, hi) == eager.count_between(lo, hi)


def test_an_explicit_time_axis_is_searched_without_being_loaded():
    times = Virtual(1_000_000_000, lambda i: 10.0 + i * 0.001)       # sorted, 1e9 timestamps
    series = LazyTimeSeries(Virtual(1_000_000_000), times=times)
    window = series.window(5000.0, 5000.005)
    assert len(window) == 5 and times.largest_read <= 5
    assert bisect_array(times, 10.0) == 0 and bisect_array(times, 1e12) == 1_000_000_000


def test_coverage_of_an_explicit_axis_finds_the_same_gaps_as_loading_it():
    t = np.concatenate([np.arange(0, 10, 0.01), np.arange(15, 30, 0.01), np.arange(31, 40, 0.01)])
    v = np.zeros(len(t))
    lazy = LazyTimeSeries(v, times=t)
    np.testing.assert_allclose(lazy.coverage(), TimeSeries(t, v).coverage())
    assert len(lazy.coverage()) == 3


def test_coverage_over_several_chunks_does_not_lose_a_gap_at_a_chunk_edge(monkeypatch):
    import syncviz.resources.timeseries as module

    monkeypatch.setattr(module, "COVERAGE_CHUNK", 100)
    t = np.concatenate([np.arange(0, 1.0, 0.01), np.arange(5, 6.0, 0.01)])      # the gap sits exactly at sample 100
    np.testing.assert_allclose(LazyTimeSeries(np.zeros(len(t)), times=t).coverage(), TimeSeries(t, np.zeros(len(t))).coverage())


def test_a_regular_series_has_one_run_and_no_gaps():
    series = LazyTimeSeries(Virtual(10_000), start=2.0, rate=100.0)
    np.testing.assert_allclose(series.coverage(), [[2.0, 2.0 + 9999 / 100.0]])


def test_thinning_keeps_the_extremes_of_a_dense_signal():
    values = np.random.default_rng(0).normal(0, 1, 1_000_000)
    values[123_456], values[654_321] = 50.0, -50.0                   # spikes that must not vanish
    series = LazyTimeSeries(values, start=0.0, rate=1000.0)
    window = series.window(0.0, 1000.0, max_points=2000)
    assert len(window) <= 2010
    assert window.values.max() == 50.0 and window.values.min() == -50.0
    assert np.all(np.diff(window.times) >= 0)


def test_thinning_applies_to_series_in_memory_too_and_leaves_small_windows_alone():
    t = np.arange(100_000) / 100.0
    series = TimeSeries(t, np.sin(t))
    assert len(series.window(0, 1000, max_points=500)) <= 510
    assert len(series.window(0, 1.0, max_points=500)) == 100


def test_minmax_indices_handles_a_ragged_tail():
    values = np.arange(1005, dtype=float)
    picks = minmax_indices(values, 100)
    assert picks.max() == 1004 and np.all(np.diff(picks) > 0)


def test_a_window_too_big_to_read_in_full_is_read_thinned(monkeypatch):
    import syncviz.resources.timeseries as module

    monkeypatch.setattr(module, "MAX_BLOCK_READ", 1000)
    data = Virtual(100_000)
    window = LazyTimeSeries(data, start=0.0, rate=1000.0).window(0.0, 100.0)
    assert data.largest_read <= 1000 and 0 < len(window) <= 1000


def test_sampling_values_for_an_axis_range_reads_a_few_small_blocks_not_the_series():
    data = Virtual(3_400_000_000)
    sample = LazyTimeSeries(data, start=0.0, rate=30_000.0).sample_values(100_000)
    assert data.largest_read <= 2000 and data.reads <= 60 and len(sample) <= 100_000


def test_scale_and_offset_turn_stored_numbers_into_units():
    raw = np.array([0, 10, 20], dtype=np.int16)
    window = LazyTimeSeries(raw, start=0.0, rate=1.0, scale=0.5, offset=1.0, unit="V").window(0.0, 3.0)
    np.testing.assert_allclose(window.values, [1.0, 6.0, 11.0])
    assert window.unit == "V"


def test_it_must_have_exactly_one_kind_of_time_axis():
    with pytest.raises(ValueError):
        LazyTimeSeries(np.zeros(3))
    with pytest.raises(ValueError):
        LazyTimeSeries(np.zeros(3), times=np.arange(3.0), rate=1.0)
    with pytest.raises(ValueError):
        LazyTimeSeries(np.zeros(3), times=np.arange(4.0))


def test_the_time_base_of_a_regular_series_is_a_grid_and_of_an_explicit_one_matches_the_loaded_base():
    regular = LazyTimeSeries(Virtual(1000), start=1.0, rate=100.0).time_base()
    assert isinstance(regular, RegularGrid) and regular.neighbor(1.0, +1) == pytest.approx(1.01)
    t = np.array([0.0, 0.5, 0.7, 2.0])
    lazy, loaded = LazySampleTimes(t), SampleTimes(t)
    for time in [-1.0, 0.0, 0.3, 0.5, 0.7, 1.0, 2.0, 3.0]:
        for direction in (-1, +1):
            assert lazy.neighbor(time, direction) == loaded.neighbor(time, direction)


# -- from an NWB file ------------------------------------------------------------------------
pynwb = pytest.importorskip("pynwb")
from pynwb import NWBFile, NWBHDF5IO, TimeSeries as NWBTimeSeries
from pynwb.behavior import BehavioralTimeSeries
from hdmf.backends.hdf5 import H5DataIO

from syncviz_nwb import NWBSource

RATE = 2000.0
SAMPLES = 20_000_000                    # 40 MB of int16: ten thousand seconds at 2 kHz


@pytest.fixture(scope="module")
def big_nwb(tmp_path_factory):
    path = tmp_path_factory.mktemp("big") / "ephys.nwb"
    nwb = NWBFile(session_description="s", identifier="big", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    raw = (np.arange(SAMPLES) % 2000).astype(np.int16)
    nwb.add_acquisition(NWBTimeSeries(name="lfp", data=H5DataIO(raw, compression="gzip", chunks=(100_000,)),
                                      unit="volts", conversion=0.5, starting_time=10.0, rate=RATE))
    behavior = nwb.create_processing_module("behavior", "b")
    series = BehavioralTimeSeries(name="small")
    series.create_timeseries(name="angle", data=np.arange(100.0), unit="deg", conversion=2.0, starting_time=0.0, rate=10.0)
    behavior.add(series)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)
    return path


def test_a_big_series_in_a_file_stays_in_the_file_and_a_small_one_is_loaded(big_nwb):
    source = NWBSource(big_nwb, lazy_min_samples=1_000_000)
    try:
        big = source.read_timeseries("acquisition/lfp")["lfp"]
        small = source.read_timeseries("processing/behavior/small")["angle"]
        assert isinstance(big, LazyTimeSeries) and isinstance(small, TimeSeries)
        assert len(big) == SAMPLES and big.first_time == 10.0 and big.unit == "volts"
    finally:
        source.close()


def test_a_window_from_a_big_series_has_the_right_values_in_units_and_costs_little_memory(big_nwb):
    source = NWBSource(big_nwb, lazy_min_samples=1_000_000)
    try:
        series = source.read_timeseries("acquisition/lfp")["lfp"]
        tracemalloc.start()
        window = series.window(5010.0, 5015.0, max_points=1000)
        _, peak = tracemalloc.get_traced_memory()
        tracemalloc.stop()
        assert peak < 5_000_000, f"reading a 5 s window used {peak / 1e6:.1f} MB"
        full = series.window(5010.0, 5010.01)                           # 20 samples, unthinned
        first = int(round((5010.0 - 10.0) * RATE))
        np.testing.assert_allclose(full.values, ((np.arange(first, first + 20) % 2000) * 0.5))
        assert 0 < len(window) <= 1010
        assert window.values.max() == pytest.approx(999.5) and window.values.min() == 0.0     # extremes survive thinning
    finally:
        source.close()


def test_conversion_is_applied_to_series_loaded_in_full_too(big_nwb):
    source = NWBSource(big_nwb)                                           # default threshold: small series are eager
    small = source.read_timeseries("processing/behavior/small")["angle"]
    assert isinstance(small, TimeSeries)
    np.testing.assert_allclose(small.values[:3], [0.0, 2.0, 4.0])


def test_closing_the_source_releases_the_file(big_nwb):
    source = NWBSource(big_nwb, lazy_min_samples=1_000_000)
    source.read_timeseries("acquisition/lfp")
    assert source._h5 is not None
    source.close()
    source.close()                                                        # harmless twice
    assert source._h5 is None


# -- in the application ----------------------------------------------------------------------
@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_a_plot_of_a_big_series_draws_a_bounded_number_of_points_and_can_step(big_nwb, tmp_path, qapp):
    from syncviz.core import Seek, StepTime
    from syncviz_app.app import build_window

    (tmp_path / "project.yaml").write_text(f"""
name: ephys
sources:
  session: {{type: nwb, path: "{big_nwb.as_posix()}", lazy_min_samples: 1000000}}
views:
  - type: timeseries
    title: LFP
    window: 10
    series: {{from: "session:acquisition/lfp", member: lfp}}
""", encoding="utf-8")
    window = build_window(tmp_path / "project.yaml", use_workspace=False)
    window.show()
    try:
        view = window.views[0]
        assert isinstance(view.series, LazyTimeSeries)
        assert window.context.extents["LFP"] == (10.0, pytest.approx(10.0 + (SAMPLES - 1) / RATE))
        window.context.bus.publish(Seek(500.0))
        window.refresh_now()
        x, _y = view.curve.getData()
        assert 0 < len(x) <= max(2 * view.plot.width(), 2000) + 10         # not the 20,000 samples in the window
        before = window.context.timeline.time
        window.context.stepper.reference = "LFP"
        window.context.bus.publish(StepTime(+1))
        assert window.context.timeline.time == pytest.approx(before + 1 / RATE)
    finally:
        window.close()
