"""A view can be shifted in time for exploring (display lag): it draws another moment than the playhead."""

import pytest
from PySide6.QtCore import QPointF, Qt

from syncviz.core import Seek
from syncviz_app.app import build_window
from syncviz_app.refresh import RefreshScheduler

from test_app_smoke import FPS, _pump, _reopen, qapp, window          # noqa: F401  (fixtures)


def _view(window, title):
    return next(v for v in window.views if v.title == title)


# -- the scheduler hands each view its own time ---------------------------------------------------
def test_each_view_is_drawn_at_the_playhead_minus_its_own_lag():
    class Fake:
        refresh_hz = 1000.0

        def __init__(self, lag):
            self.lag, self.drawn = lag, []

        def isVisible(self):
            return True

        def refresh(self, time):
            self.drawn.append(time)

    plain, behind, ahead = Fake(0.0), Fake(0.25), Fake(-0.5)
    scheduler = RefreshScheduler([plain, behind, ahead])
    scheduler.changed()
    scheduler.pump(0.0, 10.0, force=True)
    assert (plain.drawn, behind.drawn, ahead.drawn) == ([10.0], [9.75], [10.5])


# -- in the window --------------------------------------------------------------------------------
def test_a_lagged_video_shows_the_frame_from_that_much_earlier(window, qapp):
    video = _view(window, "Clip")
    window.context.bus.publish(Seek(3.0))
    window.refresh_now()
    assert video._wanted == round(3.0 * FPS)
    window.set_view_lag(video, 100.0)                 # runs 100 ms behind
    window.refresh_now()
    assert video._wanted == round(2.9 * FPS)
    window.set_view_lag(video, -100.0)                # runs 100 ms ahead
    window.refresh_now()
    assert video._wanted == round(3.1 * FPS)


def test_a_plots_window_is_centred_on_the_shifted_time(window):
    angle = _view(window, "Angle")
    window.context.bus.publish(Seek(3.0))
    window.set_view_lag(angle, 500.0)
    window.refresh_now()
    lo, hi = angle.plot.getViewBox().viewRange()[0]
    assert (lo + hi) / 2 == pytest.approx(2.5)


def test_changing_the_lag_redraws_even_while_paused(window):
    angle = _view(window, "Angle")
    window.context.bus.publish(Seek(3.0))
    window.refresh_now()
    before = angle.plot.getViewBox().viewRange()[0]
    window.set_view_lag(angle, 1000.0)
    window.scheduler.pump(1e9, window.context.timeline.time, force=False)
    assert angle.plot.getViewBox().viewRange()[0] != before


def test_clicking_a_shifted_plot_seeks_to_the_playhead_time_not_the_views_own(window):
    angle = _view(window, "Angle")
    window.context.bus.publish(Seek(3.0))
    window.set_view_lag(angle, 500.0)
    window.refresh_now()
    viewbox = angle.plot.getPlotItem().vb
    point = viewbox.mapViewToScene(QPointF(2.0, 0.0))                 # the view's own time 2.0 s

    class Click:
        def button(self):
            return Qt.MouseButton.LeftButton

        def scenePos(self):
            return point

        def double(self):
            return True                      # a double click seeks; a single click selects (design doc 28.7)

        def modifiers(self):
            return Qt.KeyboardModifier.NoModifier

    angle._clicked(Click())
    assert window.context.timeline.time == pytest.approx(2.5, abs=0.05)   # 2.0 + the 0.5 s lag


def test_stepping_by_a_shifted_view_steps_through_its_samples_in_playhead_time(window):
    angle = _view(window, "Angle")
    base = window.context.stepper.bases["Angle"]
    assert base.neighbor(1.0, +1) == pytest.approx(1.02)               # samples every 20 ms
    window.set_view_lag(angle, 5.0)
    assert base.neighbor(1.0, +1) == pytest.approx(1.005)              # the sample at 1.0 now shows at 1.005
    assert base.neighbor(1.005, -1) == pytest.approx(0.985)            # and the one before it at 0.985


def test_the_data_coverage_stays_at_true_times(window):
    angle = _view(window, "Angle")
    extent, coverage = window.context.extents["Angle"], list(window.context.coverage["Angle"])
    window.set_view_lag(angle, 750.0)
    assert window.context.extents["Angle"] == extent and list(window.context.coverage["Angle"]) == coverage


def test_a_shifted_panel_says_so_in_its_title_and_a_plain_one_does_not(window):
    angle = _view(window, "Angle")
    dock = window.docks[window.views.index(angle)]
    assert dock.windowTitle() == "Angle"
    window.set_view_lag(angle, 15.0)
    assert dock.windowTitle() == "Angle   [delayed 15 ms]"
    window.set_view_lag(angle, -2.5)
    assert dock.windowTitle() == "Angle   [ahead 2.5 ms]"
    window.set_view_lag(angle, 0.0)
    assert dock.windowTitle() == "Angle"


# -- the field in the views list ----------------------------------------------------------------------
def _select(window, title):
    panel = window.views_panel
    for i in range(panel.list.count()):
        if panel.list.item(i).text() == title:
            panel.list.setCurrentRow(i)
            return panel
    raise AssertionError(title)


def test_the_field_shows_and_sets_the_selected_views_shift_and_reset_clears_it(window):
    panel = _select(window, "Angle")
    assert panel.lag_spin.value() == 0.0 and panel.lag_spin.isEnabled()
    panel.lag_spin.setValue(15.0)
    assert _view(window, "Angle").lag == pytest.approx(0.015)
    _select(window, "Events")
    assert panel.lag_spin.value() == 0.0 and _view(window, "Events").lag == 0.0       # per view
    _select(window, "Angle")
    assert panel.lag_spin.value() == pytest.approx(15.0)
    panel.lag_reset.click()
    assert _view(window, "Angle").lag == 0.0 and panel.lag_spin.value() == 0.0


def test_the_delay_is_described_in_words_so_the_sign_never_has_to_be_remembered(window):
    from syncviz_app.views.base import describe_delay

    assert describe_delay(15.0) == "delayed 15 ms" and describe_delay(-15.0) == "ahead 15 ms" and describe_delay(0.0) == ""
    assert describe_delay(15.0, sentence=True) == "This view runs 15 ms behind the playhead."
    assert describe_delay(-2.5, sentence=True) == "This view runs 2.5 ms ahead of the playhead."
    assert describe_delay(0.0, sentence=True) == "No delay"
    panel = _select(window, "Angle")
    assert panel.lag_words.text() == "No delay"
    panel.lag_spin.setValue(15.0)
    assert "15 ms behind" in panel.lag_words.text()
    panel.lag_spin.setValue(-15.0)
    assert "15 ms ahead" in panel.lag_words.text()
    panel.list.setCurrentRow(-1)
    assert panel.lag_words.text() == ""


def test_a_positive_delay_makes_the_view_show_the_earlier_moment(window):
    video = _view(window, "Clip")
    window.context.bus.publish(Seek(3.0))
    window.set_view_lag(video, 100.0)
    window.refresh_now()
    assert video._wanted < round(3.0 * FPS)              # delayed: it shows what the playhead showed before


def test_the_field_is_off_with_nothing_selected(window):
    panel = window.views_panel
    panel.list.setCurrentRow(-1)
    assert not panel.lag_spin.isEnabled() and not panel.lag_reset.isEnabled()


def test_the_delay_field_is_marked_for_the_workspace(window):
    assert window.views_panel.lag_spin.property("workspace") == "saved"


# -- saved with the workspace ---------------------------------------------------------------------------------
def test_shifts_are_saved_in_the_workspace_and_come_back(window, qapp):
    window.set_view_lag(_view(window, "Angle"), 15.0)
    window.set_view_lag(_view(window, "Clip"), -40.0)
    window.save_workspace_as("Aligned")
    again = _reopen(window, qapp, workspace_name="Aligned")
    try:
        assert _view(again, "Angle").lag == pytest.approx(0.015) and _view(again, "Clip").lag == pytest.approx(-0.040)
        assert _view(again, "Events").lag == 0.0
        assert "delayed 15 ms" in again.docks[again.views.index(_view(again, "Angle"))].windowTitle()
    finally:
        again.close()


def test_switching_workspaces_switches_the_shifts_and_reset_removes_them(window):
    window.save_workspace_as("Plain")
    window.set_view_lag(_view(window, "Angle"), 15.0)
    window.save_workspace_as("Aligned")
    window.switch_workspace("Plain")
    assert _view(window, "Angle").lag == 0.0
    window.switch_workspace("Aligned")
    assert _view(window, "Angle").lag == pytest.approx(0.015)
    window.reset_workspace()
    assert _view(window, "Angle").lag == 0.0


def test_a_project_can_give_a_view_a_starting_shift_and_reset_returns_to_it(window):
    view = window.add_view({"type": "timeseries", "title": "Late",
                            "series": {"from": "session:processing/behavior/whisker", "member": "angle"}, "lag_ms": 12.0})
    assert view.lag == pytest.approx(0.012)
    window.set_view_lag(view, 99.0)
    window.reset_workspace()
    assert _view(window, "Angle").lag == 0.0


def test_a_view_added_after_a_shift_was_chosen_for_its_title_keeps_it(window):
    angle = _view(window, "Angle")
    window.set_view_lag(angle, 20.0)
    window.remove_view(angle, track=False)
    again = window.add_view({"type": "timeseries", "title": "Angle",
                             "series": {"from": "session:processing/behavior/whisker", "member": "angle"}})
    assert again.lag == pytest.approx(0.020)


def test_every_input_control_in_the_views_list_is_marked(window):
    from PySide6.QtWidgets import QAbstractSpinBox, QComboBox

    for kind in (QAbstractSpinBox, QComboBox):
        assert all(w.property("workspace") for w in window.views_panel.findChildren(kind) if w.parent() is window.views_panel)
