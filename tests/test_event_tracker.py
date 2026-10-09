"""The event tracker: tiles that light when the events the viewer tracks happen, and double-click to track (design doc 28.11)."""

import os

import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt

from syncviz.conditions import Condition
from syncviz.inspection import Target

from test_epochs import qapp, window  # noqa: F401  (fixtures)

NONE = Qt.KeyboardModifier.NoModifier
CTRL = Qt.KeyboardModifier.ControlModifier
SHIFT = Qt.KeyboardModifier.ShiftModifier


@pytest.fixture
def tracker(window):
    view = window.add_view({"type": "events", "title": "Tracker"})
    view.resize(520, 420)
    view.canvas.relayout()
    return view


def _centre(view, name):
    tile = next(t for t in view.canvas.tiles if t.name == name)
    return tile.rect.center().toPoint()


def _press(view, name, modifiers=NONE, double=False):
    view.pressed(_centre(view, name), double, modifiers)


def _open_others(window, tracker):
    window.set_view_setting(tracker, "others", True)
    tracker.canvas.relayout()


# -- what is shown ---------------------------------------------------------------------------------------------------
def test_the_tracker_starts_empty_with_the_other_events_collapsed(window, tracker):
    assert window.context.events.tracked == [] and tracker.canvas.tiles == []
    assert [h[0] for h in tracker.canvas.headings] == ["▸ Other events (3)"]
    assert not tracker.show_others


def test_tracking_an_event_shows_its_tile_under_its_scope(window, tracker):
    window.context.events.track("Lick left", "Contact C0")
    tracker.canvas.relayout()
    assert [t.name for t in tracker.canvas.tiles] == ["Contact C0", "Lick left"]          # grouped by the project's scopes
    assert [h[0] for h in tracker.canvas.headings][:2] == ["Contacts", "Licks"]
    assert [h[0] for h in tracker.canvas.headings][2] == "▸ Other events (1)"


def test_the_other_events_are_grayed_tiles_that_can_be_shown_and_hidden(window, tracker):
    _open_others(window, tracker)
    assert sorted(t.name for t in tracker.canvas.tiles) == ["Contact C0", "Lick left", "Lick right"]
    assert not any(t.tracked for t in tracker.canvas.tiles)
    assert window.settings()["view_settings"]["Tracker"]["others"] is True                  # kept with the workspace
    tracker.pressed(tracker.canvas.headings[-1][1].center().toPoint(), False, NONE)         # click the heading to close
    assert tracker.canvas.tiles == [] and not tracker.show_others


def test_tiles_light_when_their_event_happens_and_fade_after(window, tracker):
    window.context.events.track("Lick left", "Contact C0")
    assert tracker.levels_at(1.0)["Lick left"] == pytest.approx(1.0) and tracker.levels_at(1.0)["Contact C0"] == 0.0
    assert tracker.levels_at(1.125)["Lick left"] == pytest.approx(0.5)                       # halfway through the 0.25 s fade
    assert tracker.levels_at(5.0)["Lick left"] == 0.0
    assert tracker.levels_at(3.2)["Contact C0"] == 1.0                                        # an interval stays lit while it lasts
    tracker.refresh(3.2)
    assert tracker.level_of("Contact C0") == 1.0
    tracker.canvas.grab()                                                                     # painting does not fail


def test_a_tile_for_an_event_the_recording_lacks_is_dim_and_never_lights(window, tracker, monkeypatch):
    window.context.events.track("Lick left")
    monkeypatch.setattr(window.context.events, "find", lambda name: (_ for _ in ()).throw(KeyError(name)))
    tracker._data.clear()
    assert not tracker.has_data("Lick left") and tracker.levels_at(1.0) == {}


def test_what_is_tracked_is_saved_in_the_workspace_and_the_projects_list_is_the_default(window, tracker):
    events = window.context.events
    events.track_default = ["Lick right"]
    events.apply_state({})                                                                    # nothing saved: the project's list
    assert events.tracked == ["Lick right"]
    events.track("Contact C0")
    saved = window.settings()["events"]
    assert saved["tracked"] == ["Lick right", "Contact C0"]
    events.apply_state({"tracked": ["Lick left", "not an event"]})
    assert events.tracked == ["Lick left"]


# -- pointing and clicking ------------------------------------------------------------------------------------------------
def test_double_clicking_a_tile_tracks_or_untracks_its_event(window, tracker):
    _open_others(window, tracker)
    _press(tracker, "Lick left", double=True)
    assert window.context.events.tracked == ["Lick left"]
    tracker.canvas.relayout()
    _press(tracker, "Lick left", double=True)
    assert window.context.events.tracked == []


def test_a_double_click_still_goes_to_the_time_where_the_event_has_one(window):
    registry = window.context.commands
    assert registry.bindings["double_click"] == ["seek", "toggle_tracking"]
    window.context.bus.publish(__import__("syncviz.core", fromlist=["Seek"]).Seek(0.0))
    timed = Target("session", "processing/behavior/licks", "events", "left", "Lick left", time=2.0)
    assert registry.trigger("double_click", timed) and window.context.timeline.time == pytest.approx(2.0)
    assert window.context.events.tracked == []                                                # it sought; it did not track
    untimed = Target("session", "processing/behavior/licks", "events", "left", "Lick left")
    assert registry.trigger("double_click", untimed) and window.context.events.tracked == ["Lick left"]
    other = Target("session", "units", "events", "7", "Unit 7")
    assert not registry.trigger("double_click", other)                                        # neither applies


def test_clicking_selects_ctrl_adds_and_shift_takes_the_run_in_display_order(window, tracker):
    window.context.events.track("Lick left", "Lick right", "Contact C0")
    tracker.canvas.relayout()
    order = [t.name for t in tracker.canvas.tiles]
    _press(tracker, order[0])
    _press(tracker, order[2], SHIFT)
    assert [t.label for t in window.context.selection.targets] == order
    _press(tracker, order[1], CTRL)
    assert [t.label for t in window.context.selection.targets] == [order[0], order[2]]
    assert [t.label for t in tracker.selectable_targets()] == order


def test_hovering_a_tile_gives_the_events_description_and_figures(window, tracker):
    window.context.events.track("Lick left")
    tracker.canvas.relayout()
    pos = tracker.canvas.mapTo(tracker, _centre(tracker, "Lick left"))
    text = tracker.hover_text(pos)
    assert text.startswith("Lick left") and "Events" in text


# -- the filter on a tile -----------------------------------------------------------------------------------------------------
def test_a_tile_says_how_its_event_is_used_as_a_filter(window):
    events = window.context.events
    assert events.filter_state("Lick left") is None
    events.add(Condition(("Lick left", "Lick right")))
    assert events.filter_state("Lick left") == ("yes", True) and events.filter_state("Contact C0") is None
    events.set_enabled(0, False)
    assert events.filter_state("Lick left") == ("yes", False)                                 # off: shown faded
    events.clear()
    events.add(Condition(("Lick left",), answer=False))
    assert events.filter_state("Lick left") == ("no", True)
    events.add(Condition(("Contact C0",), mode="clip"))
    assert events.filter_state("Contact C0") == ("clips", True)


def test_a_condition_that_is_on_wins_over_one_that_is_off_and_clips_over_the_rest(window):
    events = window.context.events
    events.add(Condition(("Lick right",), answer=False, enabled=False))
    events.add(Condition(("Lick left", "Lick right"), answer=False))
    assert events.filter_state("Lick right") == ("no", True)
    events.clear()
    events.add(Condition(("Contact C0",)))
    assert events.filter_state("Contact C0") == ("yes", True)
    events.add(Condition(("Contact C0",), mode="clip"))
    assert events.filter_state("Contact C0") == ("clips", True)


def test_a_tile_with_a_filter_paints(window, tracker):
    window.context.events.track("Lick left", "Contact C0")
    window.context.events.add(Condition(("Lick left",)))
    window.context.events.add(Condition(("Contact C0",), mode="clip", enabled=False))
    tracker.canvas.relayout()
    tracker.canvas.grab()
    window.context.selection.set(window.context.events.target_of("Lick left"))
    tracker.canvas.grab()


# -- the commands -------------------------------------------------------------------------------------------------------------
def test_the_menu_offers_track_or_remove_by_state_and_never_the_double_click_helper(window):
    registry, events = window.context.commands, window.context.events
    target = events.target_of("Lick left")
    labels = lambda: [c.label for c in registry.for_target(target)]
    assert "Track this event" in labels() and "Remove from tracker" not in labels()
    events.track("Lick left")
    assert "Remove from tracker" in labels() and "Track this event" not in labels()
    assert "Track or untrack this event" not in labels()
    assert registry.get("toggle_tracking") is not None                                         # but it exists to be bound


def test_the_commands_for_several_events_track_or_untrack_them_together(window):
    registry, events = window.context.commands, window.context.events
    targets = [events.target_of(n) for n in ("Lick left", "Lick right")]
    assert registry.run_many("track_event", targets) and events.tracked == ["Lick left", "Lick right"]
    assert not registry.run_many("track_event", targets)                                       # all already tracked: not offered
    assert registry.run_many("untrack_event", targets[:2]) and events.tracked == []


def test_the_tracker_can_be_added_from_the_add_view_dialog(window):
    from syncviz_app.add_view_dialog import collect_candidates
    groups = collect_candidates(window.source_catalog())
    assert any(c.spec["type"] == "events" for found in groups.values() for c in found)
