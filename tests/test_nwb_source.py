from datetime import datetime, timezone

import numpy as np
import pytest

pynwb = pytest.importorskip("pynwb")

from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralEvents, BehavioralTimeSeries

from syncviz_nwb import NWBSource


@pytest.fixture(scope="module")
def nwb_path(tmp_path_factory):
    path = tmp_path_factory.mktemp("nwb") / "session.nwb"
    nwb = NWBFile(
        session_description="synthetic",
        identifier="synthetic-1",
        session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    nwb.add_trial_column(name="stimulus", description="shape")
    nwb.add_trial_column(name="correct", description="was correct")
    for i, (a, b) in enumerate([(0.0, 5.0), (5.0, 12.0), (12.0, 20.0)]):
        nwb.add_trial(start_time=a, stop_time=b, stimulus=["convex", "concave", "convex"][i],
                      correct=bool(i % 2 == 0))

    behavior = nwb.create_processing_module("behavior", "behavior")
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0, 1.0], unit="n/a", timestamps=[1.0, 2.5])
    licks.create_timeseries(name="right", data=[1.0], unit="n/a", timestamps=[7.0])
    behavior.add(licks)

    whisker = BehavioralTimeSeries(name="whisker")
    whisker.create_timeseries(name="angle", data=np.linspace(0, 10, 11), unit="degrees",
                              timestamps=np.arange(11.0))
    whisker.create_timeseries(name="bend", data=np.zeros(11), unit="1/mm", starting_time=0.0, rate=1.0)
    behavior.add(whisker)

    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)
    return path


def test_describe_lists_paths_without_reading_data(nwb_path):
    names = NWBSource(nwb_path).describe()

    assert "intervals/trials" in names
    assert "processing/behavior/licks" in names


def test_trials_become_a_generic_interval_series(nwb_path):
    iv = NWBSource(nwb_path).read_intervals("intervals/trials")

    assert len(iv) == 3
    assert iv.starts.tolist() == [0.0, 5.0, 12.0]
    assert iv.stops.tolist() == [5.0, 12.0, 20.0]
    assert iv.attributes["stimulus"].tolist() == ["convex", "concave", "convex"]
    assert iv.select(stimulus="convex", correct=True).tolist() == [0, 2]
    assert "start_time" not in iv.attributes


def test_events_split_by_series_name(nwb_path):
    events = NWBSource(nwb_path).read_events("processing/behavior/licks")

    assert set(events) == {"left", "right"}
    assert events["left"].times.tolist() == [1.0, 2.5]


def test_timeseries_reads_only_requested_members(nwb_path):
    series = NWBSource(nwb_path).read_timeseries("processing/behavior/whisker", only=["angle"])

    assert list(series) == ["angle"]
    assert series["angle"].unit == "degrees"
    assert len(series["angle"]) == 11


def test_timeseries_with_rate_gets_computed_times(nwb_path):
    series = NWBSource(nwb_path).read_timeseries("processing/behavior/whisker", only=["bend"])

    assert series["bend"].times.tolist() == list(np.arange(11.0))


def test_unknown_member_and_path_are_clear_errors(nwb_path):
    source = NWBSource(nwb_path)

    with pytest.raises(KeyError, match="nope"):
        source.read_timeseries("processing/behavior/whisker", only=["nope"])
    with pytest.raises(KeyError, match="no object"):
        source.read_intervals("intervals/missing")
