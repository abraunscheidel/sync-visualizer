import numpy as np
import pytest

from syncviz.core import (
    ActionBus,
    SegmentNavigator,
    Seek,
    SelectSegment,
    SelectTimeRange,
    SetPlaying,
    StepSegment,
    Timeline,
)
from syncviz.resources import IntervalSeries, TimeSeries


def make_intervals():
    return IntervalSeries(
        starts=[0.0, 10.0, 20.0, 30.0],
        stops=[9.0, 19.0, 29.0, 39.0],
        attributes={
            "stimulus": np.array(["convex", "concave", "convex", "concave"]),
            "number": np.array([5, 6, 7, 8]),
        },
        name="test",
    )


# --- IntervalSeries --------------------------------------------------------------------

def test_select_by_value_and_by_collection():
    iv = make_intervals()

    assert iv.select(stimulus="convex").tolist() == [0, 2]
    assert iv.select(number=[6, 8]).tolist() == [1, 3]
    assert iv.select(stimulus="concave", number=8).tolist() == [3]


def test_select_unknown_attribute_names_the_options():
    with pytest.raises(KeyError, match="stimulus"):
        make_intervals().select(colour="red")


def test_index_at_and_gaps():
    iv = make_intervals()

    assert iv.index_at(0.0) == 0
    assert iv.index_at(15.0) == 1
    assert iv.index_at(9.5) is None        # in the gap between intervals
    assert iv.index_at(39.0) is None       # stop is exclusive
    assert iv.index_at(-1.0) is None


def test_overlapping_handles_overlapping_sets():
    iv = IntervalSeries([0.0, 1.0], [5.0, 2.0])

    assert iv.overlapping(1.5, 1.6).tolist() == [0, 1]
    assert iv.overlapping(3.0, 4.0).tolist() == [0]


@pytest.mark.parametrize(
    "starts, stops, attrs",
    [
        ([0.0, 1.0], [1.0], {}),                      # length mismatch
        ([2.0], [1.0], {}),                           # stop before start
        ([5.0, 1.0], [6.0, 2.0], {}),                 # not sorted
        ([0.0, 1.0], [1.0, 2.0], {"a": [1]}),         # attribute wrong length
    ],
)
def test_invalid_intervals_rejected(starts, stops, attrs):
    with pytest.raises(ValueError):
        IntervalSeries(starts, stops, attrs)


def test_timeseries_window_is_half_open():
    ts = TimeSeries(times=np.arange(10.0), values=np.arange(10.0) * 2)

    w = ts.window(2.0, 5.0)

    assert w.times.tolist() == [2.0, 3.0, 4.0]
    assert w.values.tolist() == [4.0, 6.0, 8.0]


# --- Timeline ----------------------------------------------------------------------------

def make_timeline():
    bus = ActionBus()
    return bus, Timeline(bus, start=0.0, stop=100.0)


def test_seek_is_clamped_and_notifies_once():
    bus, tl = make_timeline()
    seen = []
    tl.subscribe(lambda t: seen.append(t.time))

    bus.publish(Seek(50.0))
    bus.publish(Seek(50.0))        # no change, no notification
    bus.publish(Seek(500.0))
    bus.publish(Seek(-5.0))

    assert seen == [50.0, 100.0, 0.0]


def test_playback_advances_and_stops_at_the_end():
    bus, tl = make_timeline()
    tl.seek(95.0)
    bus.publish(SetPlaying(True))

    tl.advance(2.0)
    assert tl.time == 97.0 and tl.playing
    tl.advance(10.0)
    assert tl.time == 100.0 and not tl.playing


def test_advance_does_nothing_while_paused():
    _, tl = make_timeline()

    tl.advance(5.0)

    assert tl.time == 0.0


def test_playback_rate_scales_time():
    bus, tl = make_timeline()
    tl.rate = 0.5
    bus.publish(SetPlaying(True))

    tl.advance(4.0)

    assert tl.time == 2.0


def test_playing_from_the_end_restarts():
    bus, tl = make_timeline()
    tl.seek(100.0)

    bus.publish(SetPlaying(True))

    assert tl.time == 0.0 and tl.playing


def test_selection_is_ordered_and_clamped():
    bus, tl = make_timeline()

    bus.publish(SelectTimeRange(60.0, -10.0))

    assert tl.selection == (0.0, 60.0)


# --- SegmentNavigator --------------------------------------------------------------------

def make_navigator():
    bus = ActionBus()
    tl = Timeline(bus, 0.0, 100.0)
    nav = SegmentNavigator(bus, make_intervals(), label="Trial", index_attribute="number")
    return bus, tl, nav


def test_stepping_moves_the_playhead_and_selection():
    bus, tl, nav = make_navigator()

    bus.publish(StepSegment(+1))

    assert nav.index == 1 and nav.number == 6
    assert tl.time == 10.0 and tl.selection == (10.0, 19.0)


def test_stepping_stops_at_the_ends():
    bus, tl, nav = make_navigator()

    bus.publish(StepSegment(-1))
    assert nav.index == 0
    for _ in range(10):
        bus.publish(StepSegment(+1))
    assert nav.index == 3


def test_filter_limits_navigation_and_keeps_current_if_still_visible():
    bus, tl, nav = make_navigator()
    nav.select(2)

    nav.filter(stimulus="convex")
    assert nav.count == 2 and nav.index == 2

    bus.publish(StepSegment(-1))
    assert nav.index == 0
    bus.publish(StepSegment(+1))
    bus.publish(StepSegment(+1))
    assert nav.index == 2            # skipped the filtered-out concave trials


def test_filter_moves_to_first_match_when_current_is_hidden():
    _, tl, nav = make_navigator()
    nav.select(1)                    # concave

    nav.filter(stimulus="convex")

    assert nav.index == 0 and tl.time == 0.0


def test_selecting_a_hidden_segment_is_rejected():
    _, _, nav = make_navigator()
    nav.filter(stimulus="convex")

    with pytest.raises(IndexError):
        nav.select(1)


def test_filter_with_no_matches_is_rejected_and_changes_nothing():
    _, _, nav = make_navigator()

    with pytest.raises(ValueError):
        nav.filter(stimulus="triangle")

    assert nav.count == 4


def test_clear_filter_keeps_current_segment():
    _, _, nav = make_navigator()
    nav.filter(stimulus="concave")
    nav.select(3)

    nav.clear_filter()

    assert nav.count == 4 and nav.index == 3


def test_label_is_display_only_and_numbers_default_to_position():
    bus = ActionBus()
    Timeline(bus, 0.0, 100.0)
    nav = SegmentNavigator(bus, make_intervals(), label="Epoch")

    bus.publish(SelectSegment(2))

    assert nav.label == "Epoch" and nav.number == 3


# --- following the playhead and skipping filtered segments ---------------------------------

def make_following_navigator():
    bus = ActionBus()
    tl = Timeline(bus, 0.0, 40.0)
    nav = SegmentNavigator(bus, make_intervals(), label="Trial", index_attribute="number")
    nav.follow(tl)
    return bus, tl, nav


def test_current_segment_follows_the_playhead_without_a_filter():
    bus, tl, nav = make_following_navigator()

    bus.publish(Seek(22.0))                    # inside the third segment

    assert nav.index == 2 and nav.number == 7
    assert tl.selection == (20.0, 29.0)


def test_unfiltered_playback_plays_straight_through_gaps():
    bus, tl, nav = make_following_navigator()
    tl.seek(8.0)
    bus.publish(SetPlaying(True))

    tl.advance(1.5)                            # 9.5 s: in the gap between segments 0 and 1

    assert tl.time == 9.5 and tl.playing


def test_playback_skips_to_the_next_matching_segment_when_filtered():
    bus, tl, nav = make_following_navigator()
    nav.filter(stimulus="convex")              # segments 0 and 2 match; 1 and 3 do not
    tl.seek(8.0)
    bus.publish(SetPlaying(True))

    tl.advance(1.5)                            # 9.5 s is in a gap, with a match ahead

    assert tl.time == 20.0 and tl.playing
    assert nav.index == 2 and tl.selection == (20.0, 29.0)


def test_playback_crossing_into_a_hidden_segment_skips_it():
    bus, tl, nav = make_following_navigator()
    nav.filter(stimulus="convex")
    tl.seek(8.9)
    bus.publish(SetPlaying(True))

    tl.advance(1.2)                            # crosses into segment 1 (concave, hidden)

    assert tl.time == 20.0 and nav.index == 2


def test_playback_pauses_at_the_end_of_the_last_matching_segment():
    bus, tl, nav = make_following_navigator()
    nav.filter(stimulus="convex")
    nav.select(2)
    tl.seek(28.0)
    bus.publish(SetPlaying(True))

    tl.advance(2.0)                            # past segment 2 into hidden segment 3

    assert not tl.playing
    assert nav.index == 2 and tl.time < 29.0


def test_skipping_can_be_turned_off():
    bus, tl, nav = make_following_navigator()
    nav.filter(stimulus="convex")
    nav.skip_hidden = False
    tl.seek(8.0)
    bus.publish(SetPlaying(True))

    tl.advance(3.0)                            # plays on through the hidden segment

    assert tl.time == 11.0 and tl.playing


def test_seeking_by_hand_into_a_hidden_segment_is_allowed_while_paused():
    bus, tl, nav = make_following_navigator()
    nav.filter(stimulus="convex")

    bus.publish(Seek(15.0))                    # a hidden (concave) segment

    assert tl.time == 15.0 and not tl.playing
