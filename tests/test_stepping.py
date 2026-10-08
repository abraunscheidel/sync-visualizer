import numpy as np
import pytest

from syncviz.core import (
    ActionBus,
    FixedStep,
    RegularGrid,
    SampleTimes,
    Seek,
    SetPlaying,
    StepTime,
    Stepper,
    Timeline,
)


# --- time bases ----------------------------------------------------------------------------

def test_regular_grid_steps_to_the_next_tick_from_on_a_tick():
    grid = RegularGrid(rate=200.0, count=1000)

    assert grid.neighbor(1.000, +1) == pytest.approx(1.005)
    assert grid.neighbor(1.000, -1) == pytest.approx(0.995)


def test_regular_grid_snaps_when_the_playhead_is_between_ticks():
    grid = RegularGrid(rate=200.0, count=1000)           # ticks every 5 ms

    assert grid.neighbor(1.0021, +1) == pytest.approx(1.005)     # forward: the next tick ahead
    assert grid.neighbor(1.0021, -1) == pytest.approx(1.000)     # back: the tick just behind


def test_regular_grid_ends():
    grid = RegularGrid(rate=10.0, count=5)               # ticks at 0.0 .. 0.4

    assert grid.neighbor(0.4, +1) is None
    assert grid.neighbor(0.0, -1) is None
    assert grid.neighbor(9.0, -1) == pytest.approx(0.4)  # from far past the end, back lands on the last tick
    assert grid.neighbor(-3.0, +1) == pytest.approx(0.0)  # from before the start, forward lands on the first


def test_regular_grid_survives_floating_point_noise():
    grid = RegularGrid(rate=200.0, count=100000)
    t = 0.0
    for _ in range(1000):
        t = grid.neighbor(t, +1)

    assert t == pytest.approx(5.0)                       # exactly 1000 ticks, none skipped or repeated


def test_sample_times_handle_irregular_spacing_and_gaps():
    times = SampleTimes(np.array([0.0, 0.1, 0.2, 5.0, 5.1]))      # a dropout between 0.2 and 5.0

    assert times.neighbor(0.2, +1) == 5.0
    assert times.neighbor(5.0, -1) == 0.2
    assert times.neighbor(0.15, +1) == 0.2
    assert times.neighbor(5.1, +1) is None
    assert times.neighbor(0.0, -1) is None


def test_fixed_step_moves_by_exactly_the_interval():
    assert FixedStep(0.25).neighbor(1.1, +1) == pytest.approx(1.35)
    assert FixedStep(0.25).neighbor(1.1, -1) == pytest.approx(0.85)


# --- Stepper ---------------------------------------------------------------------------------

def make_stepper(**bases):
    bus = ActionBus()
    tl = Timeline(bus, 0.0, 100.0)
    stepper = Stepper(bus, tl, bases or {"video": RegularGrid(10.0, 1000), "signal": SampleTimes(np.array([0.0, 0.5, 1.0]))})
    return bus, tl, stepper


def test_the_first_base_is_only_the_starting_choice():
    _, _, stepper = make_stepper()

    assert stepper.reference == "video"
    stepper.reference = "signal"
    assert stepper.base is stepper.bases["signal"]


def test_step_moves_one_tick_of_the_chosen_base():
    bus, tl, stepper = make_stepper()
    tl.seek(10.0)

    bus.publish(StepTime(+1))
    assert tl.time == pytest.approx(10.1)

    stepper.reference = "signal"
    tl.seek(0.0)
    bus.publish(StepTime(+1))
    assert tl.time == 0.5                                # the signal's next sample, not the video's


def test_the_count_repeats_the_step():
    bus, tl, stepper = make_stepper()
    stepper.count = 10
    tl.seek(10.0)

    bus.publish(StepTime(+1))

    assert tl.time == pytest.approx(11.0)


def test_a_count_larger_than_whats_left_goes_as_far_as_it_can():
    bus, tl, stepper = make_stepper()
    stepper.reference = "signal"
    stepper.count = 10
    tl.seek(0.0)

    bus.publish(StepTime(+1))

    assert tl.time == 1.0                                # the last sample


def test_stepping_pauses_playback():
    bus, tl, stepper = make_stepper()
    tl.seek(10.0)
    bus.publish(SetPlaying(True))

    bus.publish(StepTime(+1))

    assert not tl.playing and tl.time == pytest.approx(10.1)


def test_stepping_with_no_time_bases_does_nothing():
    bus = ActionBus()
    tl = Timeline(bus, 0.0, 10.0)
    stepper = Stepper(bus, tl, {})
    tl.seek(3.0)

    bus.publish(StepTime(+1))

    assert tl.time == 3.0 and stepper.base is None
