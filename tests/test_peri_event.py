"""Peri-event analysis: the rate of items around the moments of an event, and the view that shows it (design doc 28.17)."""

import os

import numpy as np
import pytest

from syncviz.peri_event import peri_event_rate, anchors_from, item_row, within_segments
from syncviz.resources.events import EventSeries
from syncviz.resources.intervals import IntervalSeries


# -- the pure part ----------------------------------------------------------------------------------------------------
def test_the_rate_is_per_item_and_averaged_over_the_moments():
    # moment 1.0: unit A fires twice in the first bin after it; moment 3.0: once. Bins are 0.5 s over 0 to 1 s.
    profile = peri_event_rate([np.array([1.1, 1.2, 3.1])], [1.0, 3.0], before=0.0, after=1.0, bin_size=0.5)
    assert profile.mean.tolist() == [3.0, 0.0] and profile.count == 2
    assert profile.per_moment.tolist() == [[4.0, 0.0], [2.0, 0.0]]
    assert profile.sem[0] == pytest.approx(1.0)                     # std 1.414 / sqrt(2)


def test_a_group_reads_as_the_average_unit_not_the_sum():
    one = peri_event_rate([np.array([1.1])], [1.0], 0.0, 0.5, 0.5)
    two = peri_event_rate([np.array([1.1]), np.array([5.0])], [1.0], 0.0, 0.5, 0.5)
    assert one.mean[0] == pytest.approx(2.0) and two.mean[0] == pytest.approx(1.0) and two.members == 2


def test_the_window_reaches_before_the_moment_and_the_delay_of_a_bin_is_its_centre():
    profile = peri_event_rate([np.array([0.95])], [1.0], before=0.5, after=0.5, bin_size=0.25)
    assert profile.centres.tolist() == [-0.375, -0.125, 0.125, 0.375]
    assert profile.mean.tolist() == [0.0, 4.0, 0.0, 0.0]
    assert profile.peak() == (4.0, -0.125) and profile.mean_rate(-0.5, 0.0) == 2.0


def test_no_moments_gives_an_empty_profile_and_bad_windows_are_refused():
    assert peri_event_rate([np.array([1.0])], [], 0.5, 0.5, 0.1).count == 0
    with pytest.raises(ValueError):
        peri_event_rate([np.array([1.0])], [1.0], 0.5, 0.5, 0)
    with pytest.raises(ValueError):
        peri_event_rate([np.array([1.0])], [1.0], -0.1, 0.5, 0.1)
    with pytest.raises(ValueError):
        peri_event_rate([np.array([1.0])], [1.0], 0.0, 0.0, 0.1)


def test_moments_come_from_event_times_or_either_edge_of_intervals_and_can_be_limited_to_segments():
    assert anchors_from(EventSeries(times=np.array([1.0, 2.0]))).tolist() == [1.0, 2.0]
    touches = IntervalSeries(np.array([1.0, 4.0]), np.array([1.5, 4.2]))
    assert anchors_from(touches).tolist() == [1.0, 4.0] and anchors_from(touches, "stop").tolist() == [1.5, 4.2]
    with pytest.raises(ValueError):
        anchors_from(touches, "middle")
    kept = within_segments(np.array([0.5, 2.5, 3.0, 6.0, 9.0]), np.array([0.0, 3.0]), np.array([1.0, 7.0]))
    assert kept.tolist() == [0.5, 3.0, 6.0]
    assert within_segments(np.array([1.0]), np.array([]), np.array([])).size == 0


def test_a_profile_keeps_the_moments_it_came_from_so_a_feature_leads_back_to_them():
    profile = peri_event_rate([np.array([1.1, 1.2, 5.1])], [1.0, 3.0, 5.0], 0.0, 0.5, 0.5)
    assert profile.moments.tolist() == [1.0, 3.0, 5.0]
    assert profile.moments_in(0.0, 0.5, rate_low=3.0).tolist() == [1.0]            # the moment with two spikes (4 Hz; one spike is 2 Hz)
    assert profile.moments_in(0.0, 0.5).tolist() == [1.0, 3.0, 5.0]


def test_the_table_row_compares_after_with_before():
    profile = peri_event_rate([np.array([0.9, 1.1, 1.2, 1.3])], [1.0], before=0.5, after=0.5, bin_size=0.25)
    row = item_row("u", profile, 0.5)
    assert (row.before, row.after, row.change) == (pytest.approx(2.0), pytest.approx(6.0), pytest.approx(4.0))
    assert row.moments == 1 and row.peak == pytest.approx(8.0) and row.peak_delay == pytest.approx(0.125)


# -- in a project ----------------------------------------------------------------------------------------------------
pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from syncviz.inspection import Target

from test_groups import window, qapp  # noqa: F401  (fixtures)


def _view(window, **spec):
    spec.setdefault("align", "Whole trial")
    spec.setdefault("before_ms", 0)
    spec.setdefault("after_ms", 2000)
    spec.setdefault("bin_ms", 500)
    return window.add_view({"type": "event_average", "title": "EventAverage", **spec})


def test_a_group_is_averaged_around_the_start_of_every_trial(window):
    view = _view(window, items=[{"group": "Layer 4", "name": "Layer 4"}])
    view.refresh(0.0)
    (item, profile), = view.profiles
    assert profile.moments.tolist() == [0.0, 3.0]                       # the starts of the two trials
    assert profile.mean.tolist() == [0.0, 0.0, 1.0, 0.0]               # unit 7 fires at 1.0 after the first start (2 Hz) and nothing within 2 s of the second
    assert "2 moments" in view.status.text()


def test_the_moments_are_only_those_in_the_shown_segments(window):
    view = _view(window, items=[{"group": "Layer 4", "name": "Layer 4"}])
    window.context.navigator.set_mask(np.array([False, True]))
    view.refresh(0.0)
    assert view.profiles[0][1].moments.tolist() == [3.0]
    view.apply_setting("inside", False)
    view.refresh(0.0)
    assert view.profiles[0][1].moments.tolist() == [0.0, 3.0]


def test_the_view_follows_the_selection_when_asked(window):
    view = _view(window, follow_selection=True)
    view.refresh(0.0)
    assert view.profiles == [] and "Select" in view.status.text()
    window.context.selection.set_all([Target("session", "units", "events", "7", "Unit 7"),
                                      Target("session", "units", "events", "130", "Unit 130")])
    view.refresh(0.0)
    assert [i["name"] for i, _ in view.profiles] == ["Unit 7", "Unit 130"] and view.table.rowCount() == 2
    window.context.selection.set(Target("", "Deep", "group", None, "Deep"))
    view.refresh(0.0)


def test_open_as_view_offers_the_profile_for_a_unit_and_for_a_group_but_not_for_other_data(window):
    from syncviz_app.views.event_average import EventAverageView

    unit = EventAverageView.spec_for(Target("session", "units", "events", "7", "Unit 7"))
    group = EventAverageView.spec_for(Target("", "Deep", "group", None, "Deep"))
    assert unit["items"] == [{"from": "session:units", "member": "7", "name": "Unit 7"}] and group["items"][0]["group"] == "Deep"
    assert EventAverageView.spec_for(Target("session", "x", "timeseries", "a", "a")) is None


def test_the_choices_are_kept_with_the_workspace_and_can_be_reset(window):
    view = _view(window, items=[{"group": "Deep", "name": "Deep"}])
    window.set_view_setting(view, "bin_ms", 100.0)
    window.set_view_setting(view, "align", "Whole trial")
    assert view.bin_ms == 100.0
    assert window.settings()["view_settings"]["EventAverage"]["bin_ms"] == 100.0
    view.reset_settings()
    assert view.bin_ms == 500.0


def test_a_table_row_is_the_item_and_clicking_it_selects_it(window):
    view = _view(window, items=[{"from": "session:units", "member": "7", "name": "Unit 7"}])
    view.refresh(0.0)
    assert view.table.item(0, 0).text() == "Unit 7" and view.table.item(0, 1).text() == "2"
    view.resize(500, 400)
    view.click_at(view.selectable_targets()[0])
    assert window.context.selection.target.member == "7"
