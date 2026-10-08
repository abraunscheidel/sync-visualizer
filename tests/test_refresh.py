import pytest

pytest.importorskip("PySide6")        # the app package imports Qt at the top level

from syncviz_app.refresh import MAX_SCALE, PUMP_INTERVAL_S, Governor, RefreshScheduler


class FakeView:
    def __init__(self, hz, visible=True):
        self.refresh_hz = hz
        self.visible = visible
        self.drawn = []

    def isVisible(self):
        return self.visible

    def refresh(self, time):
        self.drawn.append(time)


def run(scheduler, seconds, step=PUMP_INTERVAL_S, start=0.0, late=0.0, playhead=lambda t: t):
    """Pump on a timer that fires `late` seconds behind schedule, moving the playhead each time."""
    t = start
    while t < start + seconds:
        scheduler.changed()
        scheduler.pump(t, playhead(t))
        t += step + late
    return t


# --- per-view rates ----------------------------------------------------------------------

def test_each_view_redraws_at_its_own_rate():
    fast, slow = FakeView(60), FakeView(20)
    scheduler = RefreshScheduler([fast, slow])

    run(scheduler, 2.0)

    assert 100 <= len(fast.drawn) <= 130          # about 60 per second
    assert 35 <= len(slow.drawn) <= 45            # about 20 per second


def test_a_view_that_is_not_visible_is_never_redrawn_and_catches_up_when_shown():
    view = FakeView(30, visible=False)
    scheduler = RefreshScheduler([view])

    run(scheduler, 1.0)
    assert view.drawn == []

    view.visible = True
    scheduler.pump(5.0, 42.0)
    assert view.drawn == [42.0]


def test_the_final_playhead_position_is_always_drawn():
    view = FakeView(2)                             # very slow rate
    scheduler = RefreshScheduler([view])
    scheduler.changed()
    scheduler.pump(0.0, 1.0)
    scheduler.changed()
    scheduler.pump(0.01, 2.0)                      # too soon: skipped for now
    assert view.drawn == [1.0]

    scheduler.pump(0.6, 2.0)                       # once it is allowed, the latest position is drawn
    assert view.drawn == [1.0, 2.0]
    scheduler.pump(5.0, 2.0)                       # nothing changed, so nothing more to draw
    assert view.drawn == [1.0, 2.0]


def test_force_ignores_the_rate_limit():
    view = FakeView(1)
    scheduler = RefreshScheduler([view])
    scheduler.changed(); scheduler.pump(0.0, 1.0)
    scheduler.changed(); scheduler.pump(0.001, 2.0, force=True)

    assert view.drawn == [1.0, 2.0]


# --- governor ----------------------------------------------------------------------------

def test_governor_backs_off_when_the_timer_runs_late():
    governor = Governor()
    scheduler = RefreshScheduler([FakeView(60)], governor)

    run(scheduler, 3.0, late=0.015)               # every tick arrives 15 ms late: saturated

    assert governor.scale > 1.5


def test_governor_stays_at_one_when_keeping_up():
    governor = Governor()
    scheduler = RefreshScheduler([FakeView(60)], governor)

    run(scheduler, 3.0, late=0.0)

    assert governor.scale == 1.0


def test_governor_recovers_after_the_load_passes():
    governor = Governor()
    scheduler = RefreshScheduler([FakeView(60)], governor)
    end = run(scheduler, 3.0, late=0.015)
    backed_off = governor.scale

    run(scheduler, 6.0, start=end, late=0.0)

    assert backed_off > 1.5
    assert governor.scale < backed_off
    assert governor.scale == pytest.approx(1.0, abs=0.01)


def test_governor_is_capped():
    governor = Governor()
    scheduler = RefreshScheduler([FakeView(60)], governor)

    run(scheduler, 30.0, late=0.05)

    assert governor.scale == MAX_SCALE


def test_backing_off_lowers_every_views_redraw_rate():
    view = FakeView(60)
    governor = Governor()
    scheduler = RefreshScheduler([view], governor)
    governor.scale = 3.0

    assert scheduler.interval_for(view) == pytest.approx(3.0 / 60)


def test_one_off_hiccup_does_not_trigger_back_off():
    governor = Governor()
    scheduler = RefreshScheduler([FakeView(60)], governor)
    t = run(scheduler, 1.0)
    scheduler.pump(t + 0.2, 0.0)                  # a single 200 ms stall
    run(scheduler, 1.0, start=t + 0.2 + PUMP_INTERVAL_S)

    assert governor.scale == 1.0
