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
    assert [window.step_bar.base.itemText(i) for i in range(window.step_bar.base.count())] == list(stepper.bases)


def test_step_moves_by_one_video_frame_and_the_user_can_choose_another_definition(window):
    from syncviz.core import StepTime
    tl, bus, stepper = window.context.timeline, window.context.bus, window.context.stepper
    bus.publish(Seek(1.0))

    bus.publish(StepTime(+1))
    assert tl.time == pytest.approx(1.0 + 1 / FPS)           # one frame of the 30 fps clip

    window.step_bar.base.setCurrentText("Angle")             # the plot samples every 20 ms
    bus.publish(StepTime(+1))
    assert tl.time == pytest.approx(1.04)                    # the next sample ahead of 1.0333 s
    assert stepper.reference == "Angle"


def test_fixed_interval_and_count_are_adjustable_from_the_toolbar(window):
    from syncviz.core import StepTime
    tl, bus = window.context.timeline, window.context.bus
    bar = window.step_bar
    bar.base.setCurrentText("Fixed interval")
    bar.interval.setValue(250.0)
    bar.count.setValue(4)
    bus.publish(Seek(2.0))

    bus.publish(StepTime(+1))

    assert tl.time == pytest.approx(3.0)                     # 4 steps of 250 ms


def test_the_interval_box_only_shows_for_the_fixed_interval(window):
    bar = window.step_bar
    bar.base.setCurrentText("Clip")
    assert not bar._interval_action.isVisible()
    bar.base.setCurrentText("Fixed interval")
    assert bar._interval_action.isVisible()


def test_arrow_keys_stay_segment_navigation_and_shift_arrows_step(window):
    from PySide6.QtGui import QKeySequence
    shortcuts = {a.text(): a.shortcut().toString() for a in window.controls.actions() + window.step_bar.actions() if a.shortcut()}
    assert shortcuts["Next block ▶"] == QKeySequence("Right").toString()
    assert shortcuts["◀ Previous block"] == QKeySequence("Left").toString()
    assert shortcuts["Step ▶"] == QKeySequence("Shift+Right").toString()
    assert shortcuts["◀ Step"] == QKeySequence("Shift+Left").toString()
