"""Playback waits for a view that makes no progress, and carries on by itself afterwards."""

from syncviz.core import ActionBus, Timeline
from syncviz_app.stall import StallGuard


class FakeView:
    def __init__(self, title="Clip"):
        self.title = title
        self.stall = 0.0
        self.visible = True

    def isVisible(self):
        return self.visible

    def stalled_for(self, now):
        return self.stall


def make(hold_after=0.4):
    tl = Timeline(ActionBus(), 0.0, 100.0)
    view = FakeView()
    return tl, view, StallGuard(tl, [view], hold_after)


def test_a_held_timeline_does_not_advance_but_still_counts_as_playing():
    tl, _, _ = make()
    tl.set_playing(True)
    tl.hold("Clip")
    tl.advance(1.0)
    assert tl.time == 0.0 and tl.playing
    tl.hold(None)
    tl.advance(1.0)
    assert tl.time == 1.0


def test_pausing_during_a_hold_really_pauses():
    tl, _, _ = make()
    tl.set_playing(True)
    tl.hold("Clip")
    tl.set_playing(False)
    assert tl.holding is None and not tl.playing


def test_a_short_wait_does_not_hold_playback():
    tl, view, guard = make()
    tl.set_playing(True)
    view.stall = 0.2
    guard.check(0.0)
    assert tl.holding is None


def test_a_long_wait_holds_playback_and_names_the_view_then_releases_when_caught_up():
    tl, view, guard = make()
    tl.set_playing(True)
    view.stall = 0.5
    guard.check(0.0)
    assert tl.holding == "Clip"
    view.stall = 0.1                       # still behind, though progressing: keep waiting
    guard.check(0.0)
    assert tl.holding == "Clip"
    view.stall = 0.0
    guard.check(0.0)
    assert tl.holding is None and tl.playing


def test_nothing_is_held_while_paused_so_scrubbing_is_never_interrupted():
    tl, view, guard = make()
    view.stall = 5.0
    guard.check(0.0)
    assert tl.holding is None


def test_a_hidden_view_cannot_hold_playback():
    tl, view, guard = make()
    tl.set_playing(True)
    view.stall = 5.0
    view.visible = False
    guard.check(0.0)
    assert tl.holding is None
