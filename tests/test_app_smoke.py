"""Build the real window from a small synthetic project and drive it, offscreen."""

import os
import time
from datetime import datetime, timezone

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")      # before any Qt application exists

import av
import numpy as np
import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pynwb")

from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralEvents, BehavioralTimeSeries
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from syncviz.core import Seek, SelectSegment, SetPlaying, StepSegment
from syncviz_app.app import build_window

FPS = 30
N_FRAMES = 150                      # 5 seconds of video


def _write_video(path):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=FPS)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        stream.options = {"g": "15", "crf": "10"}
        for i in range(N_FRAMES):
            img = np.full((48, 64), 40 + (i * 3) % 180, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="gray").reformat(format="yuv420p")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _write_nwb(path):
    nwb = NWBFile(session_description="s", identifier="x", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial_column(name="stimulus", description="shape")
    nwb.add_trial_column(name="number", description="trial number")
    for i, (a, b) in enumerate([(0.0, 1.5), (1.5, 3.0), (3.0, 5.0)]):
        nwb.add_trial(start_time=a, stop_time=b, stimulus=["convex", "concave", "convex"][i], number=10 + i)
    behavior = nwb.create_processing_module("behavior", "b")
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0, 1.0], unit="n/a", timestamps=[-2.0, 2.0])   # one before time 0
    behavior.add(licks)
    ts = BehavioralTimeSeries(name="whisker")
    t = np.arange(0, 5, 1 / 50)
    ts.create_timeseries(name="angle", data=np.sin(t), unit="degrees", timestamps=t)
    behavior.add(ts)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(tmp_path, qapp):
    _write_video(tmp_path / "clip.mkv")
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text(
        f"""
name: smoke
cache: cache
sources:
  session: {{type: nwb, path: session.nwb}}
  video: {{type: video, path: clip.mkv, fps: {FPS}}}
segmentations:
  groups:
    label: Block
    from: session:intervals/trials
    number_attribute: number
    filters: [stimulus]
views:
  - {{type: video, title: Clip, source: video}}
  - type: timeseries
    title: Angle
    series: {{from: "session:processing/behavior/whisker", member: angle}}
  - type: tracks
    title: Events
    rows:
      - {{name: Licks, kind: events, from: "session:processing/behavior/licks", member: left}}
""",
        encoding="utf-8",
    )
    w = build_window(tmp_path / "project.yaml")
    w.show()
    yield w
    w.close()
    qapp.processEvents()


def _pump(qapp, seconds=0.0, until=None):
    end = time.time() + max(seconds, 0.0 if until is None else 10.0)
    while time.time() < end:
        qapp.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.005)
    return until() if until else True


def test_views_come_from_the_config_and_the_timeline_spans_all_sources(window):
    assert [v.title for v in window.views] == ["Clip", "Angle", "Events"]
    tl = window.context.timeline
    assert tl.start == -2.0                           # the lick before time zero extends the timeline
    assert tl.stop == pytest.approx(5.0, abs=0.05)    # the video, 150 frames at 30 fps
    assert "Clip" in window.context.extents and "Events" in window.context.extents


def test_core_vocabulary_is_generic_and_the_label_comes_from_config(window):
    nav = window.context.navigator
    assert nav.label == "Block" and nav.number == 10
    assert type(nav).__module__.startswith("syncviz.core")


def test_stepping_segments_moves_the_playhead_and_filters_limit_navigation(window, qapp):
    bus, nav, tl = window.context.bus, window.context.navigator, window.context.timeline
    bus.publish(StepSegment(+1))
    assert nav.number == 11 and tl.time == 1.5
    nav.filter(stimulus="convex")
    assert nav.count == 2
    bus.publish(SelectSegment(2))
    assert nav.number == 12 and tl.time == 3.0
    window.refresh_now()                              # redraws every view without error


def test_video_shows_a_frame_and_a_calm_placeholder_outside_its_extent(window, qapp):
    video = next(v for v in window.views if v.type_name == "video")
    shown = []
    original = video.widget.show_frame
    video.widget.show_frame = lambda image: (shown.append(image), original(image))

    window.context.bus.publish(Seek(2.0))
    window.refresh_now()
    assert _pump(qapp, until=lambda: bool(shown)), "no video frame was displayed"
    assert shown[-1].width() == 64 and shown[-1].height() == 48

    window.context.bus.publish(Seek(-1.0))            # a time the events cover but the video does not
    window.refresh_now()
    assert video.widget._target_mix == 1.0 and video.widget._message == "No video at this time"


def test_playback_advances_and_keeps_showing_frames(window, qapp):
    video = next(v for v in window.views if v.type_name == "video")
    shown = []
    original = video.widget.show_frame
    video.widget.show_frame = lambda image: (shown.append(image), original(image))
    tl = window.context.timeline
    window.context.bus.publish(Seek(0.0))
    window.context.bus.publish(SetPlaying(True))
    _pump(qapp, seconds=1.0)
    window.context.bus.publish(SetPlaying(False))
    assert 0.5 < tl.time < 1.6                        # moved roughly real time
    assert len(shown) >= 5, f"video froze during playback ({len(shown)} frames shown)"


def test_closing_stops_the_decoder_thread(tmp_path, qapp, window):
    video = next(v for v in window.views if v.type_name == "video")
    thread = video.decoder._thread
    assert thread.is_alive()
    window.close()
    assert not thread.is_alive()


def test_playback_shows_frames_even_when_decoding_is_slower_than_the_playhead(window, qapp, monkeypatch):
    """Regression: frames that finish after the playhead has moved on must still be shown.

    Real video decodes slower than the redraw interval, so every frame arrives 'stale'.
    Discarding stale frames froze the picture completely. A tiny test clip decodes too fast
    to expose this, so decoding is slowed here on purpose.
    """
    from syncviz_video.frame_reader import PlaybackReader

    original = PlaybackReader.frame

    def slow(self, n):
        time.sleep(0.05)                                  # several redraw intervals
        return original(self, n)

    monkeypatch.setattr(PlaybackReader, "frame", slow)
    video = next(v for v in window.views if v.type_name == "video")
    shown = []
    shown_original = video.widget.show_frame
    video.widget.show_frame = lambda image: (shown.append(image), shown_original(image))

    window.context.bus.publish(Seek(0.0))
    window.context.bus.publish(SetPlaying(True))
    _pump(qapp, seconds=1.5)
    window.context.bus.publish(SetPlaying(False))
    assert len(shown) >= 8, f"video froze while decoding was slow ({len(shown)} frames shown)"


def test_each_view_has_its_own_colour_and_coverage_for_the_timeline(window):
    ctx = window.context
    assert set(ctx.colors) == {"Clip", "Angle", "Events"}
    assert len(set(ctx.colors.values())) == 3                      # all different
    assert all(len(runs) >= 1 for runs in ctx.coverage.values())


def test_timeline_hover_names_the_view_and_says_whether_it_has_data_there(window):
    bar = window.timeline_bar
    from syncviz_app import timeline_bar as tb

    y_of = lambda name: tb.ROWS_TOP + bar._names.index(name) * tb.ROW_PITCH + 2
    mid = bar.width() / 2

    tip = bar.tooltip_at(mid, y_of("Clip"))
    assert tip.startswith("Clip") and "Data from 0.00" in tip and "has data" in tip

    # the events line begins at -2 s, before the video does
    x_early = bar._x_of(-1.5)
    assert "no data" in bar.tooltip_at(x_early, y_of("Clip"))
    assert "has data" in bar.tooltip_at(x_early, y_of("Events"))
    assert bar.tooltip_at(mid, 5) is None                          # over the grey bar: no tooltip


def test_gaps_smaller_than_a_pixel_are_closed_up_but_visible_ones_are_kept(window):
    bar = window.timeline_bar
    tl = window.context.timeline
    px = (tl.stop - tl.start) / max(bar.width() - 28, 1)          # seconds per pixel

    runs = [(0.0, 1.0), (1.0 + px * 0.3, 2.0), (2.0 + px * 5, 3.0)]   # a sub-pixel gap, then a 5 px gap
    merged = bar._pixel_runs(runs)

    assert len(merged) == 2
    assert merged[0][1] == pytest.approx(bar._x_of(2.0))
    assert merged[1][0] == pytest.approx(bar._x_of(2.0 + px * 5))


# --- stepping --------------------------------------------------------------------------------

def test_stepping_defaults_to_the_first_view_with_a_grid_and_lists_the_others(window):
    stepper = window.context.stepper
    assert stepper.reference == "Clip"                       # the video: first view with a time grid
    assert list(stepper.bases) == ["Clip", "Angle", "Fixed interval"]
    assert [window.navigation.base.itemText(i) for i in range(window.navigation.base.count())] == list(stepper.bases)


def test_step_moves_by_one_video_frame_and_the_user_can_choose_another_definition(window):
    from syncviz.core import StepTime
    tl, bus, stepper = window.context.timeline, window.context.bus, window.context.stepper
    bus.publish(Seek(1.0))

    bus.publish(StepTime(+1))
    assert tl.time == pytest.approx(1.0 + 1 / FPS)           # one frame of the 30 fps clip

    window.navigation.base.setCurrentText("Angle")             # the plot samples every 20 ms
    bus.publish(StepTime(+1))
    assert tl.time == pytest.approx(1.04)                    # the next sample ahead of 1.0333 s
    assert stepper.reference == "Angle"


def test_fixed_interval_and_count_are_adjustable_from_the_toolbar(window):
    from syncviz.core import StepTime
    tl, bus = window.context.timeline, window.context.bus
    bar = window.navigation
    bar.base.setCurrentText("Fixed interval")
    bar.interval.setValue(250.0)
    bar.count.setValue(4)
    bus.publish(Seek(2.0))

    bus.publish(StepTime(+1))

    assert tl.time == pytest.approx(3.0)                     # 4 steps of 250 ms


def test_the_interval_box_only_shows_for_the_fixed_interval(window):
    bar = window.navigation
    bar.base.setCurrentText("Clip")
    assert not bar._interval_action.isVisible()
    bar.base.setCurrentText("Fixed interval")
    assert bar._interval_action.isVisible()


def test_arrow_keys_stay_segment_navigation_and_shift_arrows_step(window):
    nav = window.navigation
    assert nav.next_segment.shortcut().toString() == "Right"
    assert nav.previous_segment.shortcut().toString() == "Left"
    assert nav.step_forward.shortcut().toString() == "Shift+Right"
    assert nav.step_back.shortcut().toString() == "Shift+Left"


def test_a_frame_is_always_called_a_frame_whichever_view_defines_it(window):
    bar = window.navigation
    for choice in ("Clip", "Angle", "Fixed interval"):
        bar.base.setCurrentText(choice)
        assert bar.count.suffix() == " frames"


def test_stepping_many_frames_moves_by_that_many_frames_and_not_segments(window):
    from syncviz.core import StepTime
    bus, tl, nav = window.context.bus, window.context.timeline, window.context.navigator
    window.navigation.base.setCurrentText("Clip")
    window.navigation.count.setValue(5)
    bus.publish(Seek(1.0))
    segment_before = nav.index

    bus.publish(StepTime(+1))

    assert tl.time == pytest.approx(1.0 + 5 / FPS)           # five video frames ahead
    assert nav.index == segment_before                        # the trial did not change


def test_the_navigation_sections_are_named_generically_and_the_items_use_the_configured_label(window):
    from PySide6.QtWidgets import QLabel
    nav_bar = window.navigation
    captions = [w.text() for w in nav_bar.findChildren(QLabel) if w.styleSheet().startswith("font-weight")]

    assert "Segment" in captions and "Frame" in captions
    assert "Block" not in captions                    # the configured label is for items, not section headings
    assert nav_bar.segment_label.text().strip().startswith("Block 10")


# --- pointer gestures on disabled regions -----------------------------------------------------

def _restrict_to_convex(window):
    box = window.filter_bar._filters["stimulus"]
    box.setCurrentIndex(next(i for i in range(box.count()) if box.itemData(i) == "convex"))
    assert window.context.navigator.restricting


def test_clicking_a_hidden_segment_does_nothing_and_a_matching_one_goes_exactly_there(window):
    _restrict_to_convex(window)                    # matches: 0-1.5 s and 3-5 s; hidden: 1.5-3 s
    bar, tl = window.timeline_bar, window.context.timeline
    window.context.bus.publish(Seek(0.5))

    assert bar.seek_from_x(bar._x_of(2.0)) is False            # hidden
    assert tl.time == 0.5

    assert bar.seek_from_x(bar._x_of(4.0)) is True             # matching
    assert tl.time == pytest.approx(4.0)


def test_dragging_across_a_hidden_segment_leaves_the_playhead_where_it_was_until_a_match_is_reached(window):
    _restrict_to_convex(window)
    bar, tl = window.timeline_bar, window.context.timeline
    window.context.bus.publish(Seek(0.5))
    seen = []

    for t in (0.8, 1.2, 1.7, 2.2, 2.8, 3.4, 4.2):               # a drag from left to right
        bar.seek_from_x(bar._x_of(t))
        seen.append(round(tl.time, 2))

    assert seen == [0.8, 1.2, 1.2, 1.2, 1.2, 3.4, 4.2]          # stuck at the last allowed point, then follows


def test_the_cursor_shows_whether_a_click_would_work(window):
    from PySide6.QtCore import Qt
    from syncviz_app import timeline_bar as tb
    _restrict_to_convex(window)
    bar = window.timeline_bar
    y = tb.GROOVE_TOP + tb.GROOVE_HEIGHT / 2

    assert bar.cursor_at(bar._x_of(2.0), y) == Qt.CursorShape.ForbiddenCursor       # hidden by the filter
    assert bar.cursor_at(bar._x_of(4.0), y) == Qt.CursorShape.PointingHandCursor    # a match
    assert bar.cursor_at(bar._x_of(2.0), tb.ROWS_TOP + 2) == Qt.CursorShape.PointingHandCursor  # not over the bar itself

    window.filter_bar.skip.setChecked(False)                                         # not restricting any more
    assert bar.cursor_at(bar._x_of(2.0), y) == Qt.CursorShape.PointingHandCursor
    assert bar.seek_from_x(bar._x_of(2.0)) is True


def test_no_tooltip_appears_over_disabled_parts_of_the_bar(window):
    from syncviz_app import timeline_bar as tb
    _restrict_to_convex(window)
    bar = window.timeline_bar

    assert bar.tooltip_at(bar._x_of(2.0), tb.GROOVE_TOP + tb.GROOVE_HEIGHT / 2) is None


def test_clicking_in_a_plot_follows_the_same_rule(window):
    _restrict_to_convex(window)
    plot = next(v for v in window.views if v.type_name == "timeseries")
    window.context.bus.publish(Seek(0.5))

    assert plot.seek_from_time(2.0) is False
    assert window.context.timeline.time == 0.5
    assert plot.seek_from_time(4.0) is True
    assert window.context.timeline.time == 4.0


def test_playback_waits_for_a_stalled_video_and_resumes_by_itself(window, qapp, monkeypatch):
    from syncviz_video.frame_reader import PlaybackReader

    original = PlaybackReader.frame
    slow = {"on": False}

    def frame(self, n):
        if slow["on"]:
            time.sleep(1.2)                               # far longer than the stall threshold
        return original(self, n)

    monkeypatch.setattr(PlaybackReader, "frame", frame)
    tl = window.context.timeline
    window.context.bus.publish(Seek(0.0))
    _pump(qapp, seconds=0.3)
    slow["on"] = True
    window.context.bus.publish(SetPlaying(True))
    assert _pump(qapp, until=lambda: tl.holding), "playback never waited for the stalled video"
    assert tl.playing
    video = next(v for v in window.views if v.type_name == "video")
    assert _pump(qapp, until=lambda: video.widget._cue == "Buffering…"), "the video should say it is buffering"
    held_at = tl.time
    _pump(qapp, seconds=0.2)
    assert tl.time == held_at, "the playhead kept running while the video was stalled"
    slow["on"] = False
    assert _pump(qapp, until=lambda: not tl.holding), "playback did not resume once the video caught up"
    assert _pump(qapp, until=lambda: tl.time > held_at)
    assert _pump(qapp, until=lambda: video.widget._cue == "")


def test_scrubbing_while_paused_is_never_held(window, qapp, monkeypatch):
    from syncviz_video.frame_reader import PlaybackReader

    original = PlaybackReader.frame
    monkeypatch.setattr(PlaybackReader, "frame", lambda self, n: (time.sleep(0.8), original(self, n))[1])
    window.context.bus.publish(Seek(0.5))
    _pump(qapp, seconds=0.7)
    assert window.context.timeline.holding is None and not window.context.timeline.playing


def test_debug_menu_can_slow_the_video_and_stall_it_once(window, qapp):
    from syncviz_app.debug import DebugTools

    assert window.debug is None and "Debug" not in [a.text().replace("&", "") for a in window.menuBar().actions()]
    debug = DebugTools(window)
    video = next(v for v in window.views if v.type_name == "video")
    debug.set_delay(0.2)
    assert video.decoder.delay_s == 0.2
    debug.set_delay(0.0)
    debug.stall_once()
    assert video.decoder.delay_once_s > 0
    window.context.bus.publish(Seek(0.5))
    assert _pump(qapp, until=lambda: video.decoder.delay_once_s == 0, seconds=0)
    assert "paused" in debug.text() and "Clip" in debug.text()


# -- adding, removing and switching views from the sidebar ---------------------------------
def test_the_catalog_lists_what_each_source_can_show(window):
    catalog = window.source_catalog()
    kinds = {e.kind for e in catalog["session"]}
    assert {"intervals", "events", "timeseries"} <= kinds
    assert [e.kind for e in catalog["video"]] == ["video"]


def test_the_add_dialog_offers_each_kind_of_view_the_data_can_feed(window):
    from syncviz_app.add_view_dialog import AddViewDialog

    dialog = AddViewDialog(window.source_catalog())
    assert {"Video", "Time series plot", "Events and intervals"} <= set(dialog.groups)
    assert dialog.spec() is None and not dialog.ok.isEnabled()
    group = dialog.tree.topLevelItem(0)
    dialog.tree.setCurrentItem(group.child(0))
    assert dialog.ok.isEnabled() and dialog.spec()["title"]


def test_adding_a_view_from_a_candidate_shows_it_everywhere_it_belongs(window, qapp):
    from syncviz_app.add_view_dialog import collect_candidates

    spec = next(c.spec for c in collect_candidates(window.source_catalog())["Time series plot"])
    before = len(window.views)
    view = window.add_view(spec)
    assert view is not None and len(window.views) == len(window.docks) == before + 1
    assert view.title in window.context.colors and view.title in window.context.extents
    assert view.title in window.timeline_bar._names
    bases = [window.navigation.base.itemText(i) for i in range(window.navigation.base.count())]
    assert view.title in bases
    assert window.views_panel.list.count() == before + 1
    _pump(qapp, seconds=0.2)
    assert view.isVisible()


def test_a_second_view_of_the_same_data_gets_its_own_title_and_colour(window):
    spec = {"type": "video", "title": "Clip", "source": "video"}
    view = window.add_view(spec)
    assert view.title != "Clip" and view.title.startswith("Clip")
    assert window.context.colors[view.title] != window.context.colors["Clip"]


def test_a_view_that_cannot_be_created_leaves_a_note_and_changes_nothing(window):
    before = len(window.views)
    assert window.add_view({"type": "timeseries", "title": "Broken", "series": {"from": "session:nope", "member": "x"}}) is None
    assert len(window.views) == before and any("Broken" in n for n in window.context.notes)


def test_removing_a_view_removes_it_from_the_window_and_the_context(window, qapp):
    video = next(v for v in window.views if v.type_name == "video")
    title = video.title
    window.remove_view(video)
    _pump(qapp, seconds=0.1)
    assert video not in window.views and title not in window.context.colors and title not in window.context.extents
    assert title not in window.context.stepper.bases
    assert window.context.stepper.reference in window.context.stepper.bases
    assert title not in window.timeline_bar._names
    window.context.bus.publish(Seek(1.0))                 # the remaining views keep working
    window.refresh_now()


def test_views_can_be_switched_off_and_on_from_the_sidebar_without_being_removed(window, qapp):
    panel = window.views_panel
    item = panel.list.item(1)
    view = item.data(Qt.ItemDataRole.UserRole)
    item.setCheckState(Qt.CheckState.Unchecked)
    _pump(qapp, seconds=0.1)
    assert not view.isVisible() and view in window.views
    item.setCheckState(Qt.CheckState.Checked)
    _pump(qapp, seconds=0.1)
    assert view.isVisible()


def test_closing_a_panel_unticks_it_in_the_sidebar(window, qapp):
    window.docks[1].close()
    _pump(qapp, seconds=0.1)
    assert window.views_panel.list.item(1).checkState() == Qt.CheckState.Unchecked


def test_the_views_menu_is_gone_because_the_sidebar_replaces_it(window):
    assert "Views" not in [a.text().replace("&", "") for a in window.menuBar().actions()]


# -- the layout is kept beside the project and applied next time ---------------------------
def _reopen(window, qapp):
    """Close the window (which saves its layout) and open the same project again."""
    path = window.project.path
    window.close()
    qapp.processEvents()
    again = build_window(path)
    again.show()
    return again


def test_added_views_come_back_the_next_time_the_project_opens(window, qapp):
    from syncviz_app.add_view_dialog import collect_candidates

    spec = next(c.spec for c in collect_candidates(window.source_catalog())["Time series plot"])
    added = window.add_view(spec)
    again = _reopen(window, qapp)
    try:
        assert added.title in [v.title for v in again.views]
        assert again.views_panel.list.count() == len(again.views)
    finally:
        again.close()


def test_a_removed_project_view_stays_removed_and_can_be_brought_back_by_resetting(window, qapp):
    video = next(v for v in window.views if v.type_name == "video")
    title = video.title
    window.remove_view(video)
    again = _reopen(window, qapp)
    try:
        assert title not in [v.title for v in again.views]
        again.reset_layout()
    finally:
        again.close()
    third = build_window(window.project.path)
    try:
        assert title in [v.title for v in third.views]
    finally:
        third.close()


def test_hidden_panels_stay_hidden_after_reopening(window, qapp):
    qapp.processEvents()
    window.docks[1].close()
    _pump(qapp, seconds=0.1)
    again = _reopen(window, qapp)
    try:
        _pump(qapp, seconds=0.1)
        assert not again.docks[1].isVisible() and again.docks[0].isVisible()
        assert again.views_panel.list.item(1).checkState() == Qt.CheckState.Unchecked
    finally:
        again.close()


def test_a_corrupt_layout_file_is_ignored(window, qapp):
    from syncviz_app.layout import layout_path

    path = window.project.path
    window.close()
    layout_path(path).write_text("{not json", encoding="utf-8")
    again = build_window(path)
    try:
        assert len(again.views) == 3
    finally:
        again.close()


def test_screenshot_mode_neither_reads_nor_writes_a_layout(window, qapp):
    from syncviz_app.layout import layout_path

    path = window.project.path
    window.close()
    layout_path(path).unlink(missing_ok=True)
    plain = build_window(path, use_layout=False)
    plain.close()
    assert not layout_path(path).exists()


# -- several named layouts per project, and saving on demand -------------------------------
def test_the_save_button_writes_the_layout_without_closing(window):
    from syncviz_app.layout import layout_path, load_store

    path = layout_path(window.project.path)
    path.unlink(missing_ok=True)
    window.views_panel.save_button.click()
    assert path.exists() and "Default" in load_store(path).layouts
    assert "Saved layout" in window.statusBar().currentMessage()


def test_layouts_are_named_and_switching_changes_the_views_shown(window, qapp):
    from syncviz_app.add_view_dialog import collect_candidates

    full = len(window.views)
    window.save_layout_as("Overview")                      # a second layout, starting as a copy
    assert window.layouts.current == "Overview" and set(window.layouts.names) == {"Default", "Overview"}
    window.remove_view(next(v for v in window.views if v.type_name == "video"))
    assert len(window.views) == full - 1
    window.switch_layout("Default")
    assert len(window.views) == full                       # Default still has the video
    assert window.views_panel.list.count() == full
    window.switch_layout("Overview")
    assert len(window.views) == full - 1                   # and Overview remembers it was removed
    spec = next(c.spec for c in collect_candidates(window.source_catalog())["Time series plot"])
    window.add_view(spec)
    window.switch_layout("Default")
    assert len(window.views) == full                       # the added view belongs to Overview only


def test_layouts_and_the_one_in_use_survive_reopening(window, qapp):
    window.save_layout_as("Overview")
    window.remove_view(window.views[0])
    again = _reopen(window, qapp)
    try:
        assert again.layouts.current == "Overview" and "Default" in again.layouts.names
        assert len(again.views) == 2
    finally:
        again.close()


def test_the_last_layout_cannot_be_deleted_and_deleting_the_current_one_switches(window):
    assert not window.delete_layout("Default")
    window.save_layout_as("Other")
    assert window.delete_layout("Other")
    assert window.layouts.current == "Default" and window.layouts.names == ["Default"]


def test_a_layout_file_from_before_names_existed_becomes_the_default_layout(tmp_path):
    from syncviz_app.layout import load_store

    old = tmp_path / "p.layout.json"
    old.write_text('{"version": 1, "added": [], "removed": ["Clip"]}', encoding="utf-8")
    store = load_store(old)
    assert store.current == "Default" and store.active.removed == ["Clip"]


def test_each_project_keeps_its_own_layouts(window):
    from syncviz_app.layout import layout_path

    other = window.project.path.with_name("other.yaml")
    assert layout_path(other) != layout_path(window.project.path)
