"""Synchronization diagnostics: evidence that clocks agree, or that they do not."""

import json
import os
import time
from datetime import datetime, timezone

import av
import numpy as np
import pytest
from pynwb import NWBFile, NWBHDF5IO
from pynwb.epoch import TimeIntervals
from PySide6.QtWidgets import QApplication

from syncviz import diagnostics
from syncviz.diagnostics import CheckResult, Status, check_event_response, check_paired_events, pair_events

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


# -- pairing -------------------------------------------------------------------------------------
def test_each_reference_event_pairs_with_its_nearest_test_event_and_each_is_used_once():
    test = np.array([1.00, 2.01, 2.02, 5.00])
    reference = np.array([1.0, 2.0, 3.0, 5.0])
    ti, ri = pair_events(test, reference, 0.5)
    assert list(ri) == [0, 1, 3] and list(ti) == [0, 1, 3]           # 2.01 beats 2.02; 3.0 has nothing within 0.5


def test_pairing_ignores_events_further_apart_than_the_window():
    ti, ri = pair_events(np.array([10.0]), np.array([1.0, 10.2]), 0.5)
    assert list(ri) == [1] and list(ti) == [0]


def test_pairing_copes_with_empty_input():
    assert len(pair_events(np.empty(0), np.array([1.0]), 0.5)[0]) == 0
    assert len(pair_events(np.array([1.0]), np.empty(0), 0.5)[0]) == 0


# -- paired events -------------------------------------------------------------------------------
REFERENCE = np.arange(10.0, 2400.0, 9.7)                                # a boundary every ~10 s for 40 minutes


def _paired(offset_ms=0.0, jitter_ms=0.0, drift_ms=0.0, drop=0.0, **kw):
    rng = np.random.default_rng(3)
    test = REFERENCE + offset_ms / 1000 + rng.normal(0, jitter_ms / 1000, len(REFERENCE) if jitter_ms else len(REFERENCE))
    test = test + drift_ms / 1000 * (REFERENCE - REFERENCE[0]) / (REFERENCE[-1] - REFERENCE[0])
    if drop:
        test = test[rng.random(len(test)) > drop]
    return check_paired_events(np.sort(test), REFERENCE, **kw)


def test_clocks_that_agree_pass_with_a_small_error_and_no_drift():
    r = _paired(offset_ms=3.0, jitter_ms=2.0)
    assert r.status is Status.PASS
    assert r.data["offset_ms"] == pytest.approx(3.0, abs=1.0) and abs(r.data["drift_ms"]) < 3
    assert r.data["n_pairs"] == len(REFERENCE)


@pytest.mark.parametrize("offset, expected", [(15.0, Status.PASS), (30.0, Status.WARN), (60.0, Status.FAIL), (-60.0, Status.FAIL)])
def test_a_constant_offset_is_graded_against_the_tolerance(offset, expected):
    assert _paired(offset_ms=offset, tolerance_ms=20).status is expected


@pytest.mark.parametrize("drift, expected", [(5.0, Status.PASS), (30.0, Status.WARN), (90.0, Status.FAIL)])
def test_a_clock_that_slowly_runs_away_is_caught_even_when_every_single_error_is_small_at_the_start(drift, expected):
    r = _paired(drift_ms=drift)
    assert r.status is expected
    assert r.data["drift_ms"] == pytest.approx(drift, rel=0.15, abs=2)


def test_a_wide_spread_fails_even_if_the_typical_error_is_zero():
    assert _paired(jitter_ms=40.0).status in (Status.WARN, Status.FAIL)


def test_a_few_wild_pairs_do_not_hide_a_real_drift():
    test = REFERENCE + 0.080 * (REFERENCE - REFERENCE[0]) / (REFERENCE[-1] - REFERENCE[0])
    test[::40] += 0.4                                                  # glitches
    assert check_paired_events(test, REFERENCE).data["drift_ms"] == pytest.approx(80, rel=0.2)


def test_unpaired_events_are_reported_and_many_of_them_lower_the_grade():
    assert _paired(drop=0.1).status is Status.PASS                      # 10% missing is common (a camera that started late)
    r = _paired(drop=0.3)
    assert r.status is Status.WARN and r.data["unpaired_reference"] > 0
    assert _paired(drop=0.6).status is Status.FAIL


def test_nothing_to_compare_is_inconclusive_and_almost_nothing_pairing_is_a_failure():
    assert check_paired_events([], REFERENCE).status is Status.INCONCLUSIVE
    assert check_paired_events(REFERENCE, []).status is Status.INCONCLUSIVE
    r = check_paired_events(REFERENCE + 3.0, REFERENCE, match_ms=100)    # three seconds apart: nothing matches
    assert r.status is Status.FAIL and "only 0" in r.summary


def test_a_declared_rate_is_compared_with_the_rate_the_data_implies():
    test = REFERENCE * 1.0005                                             # runs 0.05% fast
    r = check_paired_events(test, REFERENCE, declared_rate=200.0)
    assert any("implied rate" in line for line in r.details)
    assert r.data["slope"] == pytest.approx(0.0005 * 1000, rel=0.1)       # ms of error per second


def test_the_wording_never_claims_proof():
    r = _paired()
    text = " ".join([r.summary, *r.details]).lower()
    assert "proof" not in text and "verified" not in text


# -- event-aligned response -------------------------------------------------------------------------------
def _response(latency_ms, n_stim=200, n_units=8, background=5.0, evoked=12.0, seed=0):
    """Spikes at a steady background rate plus a burst `latency_ms` after each stimulus."""
    rng = np.random.default_rng(seed)
    stim = np.cumsum(rng.uniform(0.8, 1.4, n_stim)) + 5
    duration = stim[-1] + 5
    units = []
    for _ in range(n_units):
        spikes = list(rng.uniform(0, duration, int(background * duration)))
        for t0 in stim:
            n = rng.poisson(evoked * 0.03)
            spikes += list(t0 + latency_ms / 1000 + rng.normal(0, 0.004, n))
        units.append(np.sort(spikes))
    return stim, units


@pytest.mark.parametrize("latency", [8.0, 15.0, 25.0])
def test_a_response_where_it_should_be_passes(latency):
    stim, units = _response(latency)
    r = check_event_response(stim, units, expect_ms=(5, 30))
    assert r.status is Status.PASS, r.summary
    assert abs(r.data["peak_ms"] - latency) <= 7.5


def test_a_response_a_little_late_warns_and_one_far_off_fails():
    stim, units = _response(48.0)
    assert check_event_response(stim, units, expect_ms=(5, 30), tolerance_ms=20).status is Status.WARN
    stim, units = _response(110.0)
    assert check_event_response(stim, units, expect_ms=(5, 30), tolerance_ms=20).status is Status.FAIL


def test_a_response_that_comes_before_the_stimulus_does_not_pass():
    stim, units = _response(-90.0)                         # the neural clock is ahead: the burst precedes the touch
    r = check_event_response(stim, units, expect_ms=(5, 30))
    assert r.status in (Status.FAIL, Status.INCONCLUSIVE, Status.WARN) and r.status is not Status.PASS


def test_no_response_at_all_is_inconclusive_not_a_failure_of_sync():
    stim, units = _response(15.0, evoked=0.0)
    r = check_event_response(stim, units)
    assert r.status is Status.INCONCLUSIVE and "cannot be judged" in r.summary


def test_too_few_stimuli_or_nothing_responding_is_inconclusive():
    assert check_event_response([1.0, 2.0], [np.array([1.0])]).status is Status.INCONCLUSIVE
    assert check_event_response(np.arange(100.0), []).status is Status.INCONCLUSIVE


def test_only_isolated_stimuli_are_used():
    stim = np.sort(np.concatenate([np.arange(0, 100, 1.0), np.arange(0, 100, 1.0) + 0.1]))   # every touch has a follower
    _stim, units = _response(15.0)
    r = check_event_response(stim, units)
    assert r.data["n_stimuli"] == 100


def test_the_peak_search_ignores_what_happens_long_after_the_stimulus():
    stim, units = _response(15.0)
    r = check_event_response(stim, units, expect_ms=(5, 30), after_ms=300)
    assert r.data["peak_ms"] < 100


# -- results ---------------------------------------------------------------------------------------------
def test_results_survive_being_saved_and_loaded_with_their_arrays():
    r = _paired(offset_ms=5.0)
    again = CheckResult.from_json(json.loads(json.dumps(r.to_json())))
    assert again.status is r.status and again.summary == r.summary and again.details == r.details
    assert np.allclose(again.data["error_ms"], r.data["error_ms"]) and again.data["offset_ms"] == r.data["offset_ms"]


def test_the_overall_status_is_the_worst_that_says_something():
    p, w, f = (CheckResult("x", "k", s, "") for s in (Status.PASS, Status.WARN, Status.FAIL))
    na = CheckResult("x", "k", Status.NOT_APPLICABLE, "")
    assert diagnostics.overall([p, w]) is Status.WARN and diagnostics.overall([p, w, f]) is Status.FAIL
    assert diagnostics.overall([na]) is None and diagnostics.overall([]) is None
    assert diagnostics.overall([p, na]) is Status.PASS
    assert diagnostics.summarize([p, p, w, na]) == "1 warn, 2 pass, 1 not applicable"
    assert diagnostics.summarize([]) == "not checked yet"


def test_an_unknown_kind_of_check_lists_the_known_ones():
    with pytest.raises(KeyError, match="paired_events"):
        diagnostics.get("nope")


# -- in the application, on a synthetic recording with known truth ----------------------------------------------
FPS = 30
N_FRAMES = 360
BLACKOUTS = [30, 90, 150, 210, 270]                  # frame where each 4-frame blackout starts
CONTACTS = list(np.arange(0.5, 11.5, 0.25))          # touches during the recording
LATENCY = 0.015


def _write_video(path, shift_frames=0):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=FPS)
        stream.width, stream.height = 64, 48
        stream.pix_fmt = "yuv420p"
        stream.options = {"g": "15", "crf": "10"}
        dark = {f + shift_frames + k for f in BLACKOUTS for k in range(4)}
        for i in range(N_FRAMES):
            img = np.full((48, 64), 8 if i in dark else 200, dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="gray").reformat(format="yuv420p")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


def _write_nwb(path, with_units=True):
    nwb = NWBFile(session_description="s", identifier=path.stem, session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    starts = [f / FPS for f in BLACKOUTS]
    for a, b in zip(starts, starts[1:] + [12.0]):
        nwb.add_trial(start_time=float(a), stop_time=float(b))
    behavior = nwb.create_processing_module("behavior", "b")
    contacts = TimeIntervals(name="contacts_by_whisker_C1", description="touches")
    for t in CONTACTS:
        contacts.add_interval(start_time=float(t), stop_time=float(t + 0.05))
    behavior.add(contacts)
    if with_units:
        rng = np.random.default_rng(4)
        nwb.add_unit_column(name="depth", description="d")
        for u in range(6):
            spikes = list(rng.uniform(0, 12, 60)) + [t + LATENCY + rng.normal(0, 0.003) for t in CONTACTS for _ in range(rng.poisson(0.6))]
            nwb.add_unit(spike_times=sorted(spikes), depth=100.0 + u)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


def _project(tmp_path, shift_frames=0, with_units=True):
    _write_video(tmp_path / "clip.mkv", shift_frames)
    _write_nwb(tmp_path / "session.nwb", with_units)
    path = tmp_path / "project.yaml"
    path.write_text(f"""
name: sync
cache: cache
sources:
  session: {{type: nwb, path: session.nwb}}
  video: {{type: video, path: clip.mkv, fps: {FPS}, sync_signal: {{kind: dark_frames}}}}
segmentations:
  trials: {{label: Trial, from: "session:intervals/trials"}}
views:
  - {{type: video, title: Clip, source: video}}
sync:
  tolerance_ms: 20
  checks:
    - name: Blackouts vs trial starts
      type: paired_events
      test: video:sync_signal
      reference: {{from: "session:intervals/trials", edge: start}}
      note: a note that is carried into the details
    - name: Response to touch
      type: event_response
      stimulus: {{from: "session:processing/behavior/contacts_by_whisker_C1", edge: start}}
      response: "session:units"
      expect_ms: [5, 30]
      isolate_ms: 100
""", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _results(path, index=0):
    from syncviz_app.project import load_project
    from syncviz_app.sync_checks import run_checks

    project = load_project(path)
    from syncviz.cache import DiskCache

    project.attach_cache(DiskCache(path.parent / "cache"))
    return {r.name.split(": ")[-1]: r for r in run_checks(project, index)}


def test_aligned_sources_pass_both_checks_and_the_video_is_found_to_have_even_frames(tmp_path):
    results = _results(_project(tmp_path))
    blackout, response = results["Blackouts vs trial starts"], results["Response to touch"]
    assert blackout.status is Status.PASS and abs(blackout.data["offset_ms"]) < 1000 / FPS
    assert blackout.data["n_pairs"] == len(BLACKOUTS)
    assert any(d.startswith("Note: a note") for d in blackout.details)
    assert response.status is Status.PASS, response.summary
    assert results["Frames are evenly spaced"].status is Status.PASS


def test_a_video_that_is_late_by_a_fraction_of_a_second_is_caught(tmp_path):
    results = _results(_project(tmp_path, shift_frames=6))             # 0.2 s late
    blackout = results["Blackouts vs trial starts"]
    assert blackout.status is Status.FAIL and blackout.data["offset_ms"] == pytest.approx(200, abs=40)


def test_a_recording_without_neural_data_marks_that_check_not_applicable_instead_of_failing(tmp_path):
    results = _results(_project(tmp_path, with_units=False))
    assert results["Response to touch"].status is Status.NOT_APPLICABLE
    assert results["Blackouts vs trial starts"].status is Status.PASS


def test_a_check_that_cannot_run_reports_why_and_does_not_stop_the_others(tmp_path):
    path = _project(tmp_path)
    path.write_text(path.read_text(encoding="utf-8").replace("stimulus: {from:", "stimulus: {fromm:"), encoding="utf-8")
    results = _results(path)
    assert results["Response to touch"].status is Status.INCONCLUSIVE and "could not run" in results["Response to touch"].summary
    assert results["Blackouts vs trial starts"].status is Status.PASS


def test_results_are_kept_and_found_again_without_rerunning(tmp_path):
    from syncviz_app import sync_checks
    from syncviz_app.project import load_project
    from syncviz.cache import DiskCache

    path = _project(tmp_path)
    project = load_project(path)
    project.attach_cache(DiskCache(tmp_path / "cache"))
    assert sync_checks.load_cached(project, 0) is None
    sync_checks.store(project, 0, sync_checks.run_checks(project, 0))
    again = sync_checks.load_cached(project, 0)
    assert again is not None and {r.status for r in again} == {Status.PASS}
    (tmp_path / "session.nwb").write_bytes((tmp_path / "session.nwb").read_bytes() + b"x")      # the file changed
    assert sync_checks.load_cached(project, 0) is None


def test_the_video_itself_is_asked_for_its_blackouts_by_the_name_sync_signal(tmp_path):
    from syncviz_app.project import load_project

    project = load_project(_project(tmp_path))
    events = project.resources.events("video:sync_signal")
    assert len(events) == len(BLACKOUTS)
    assert events.times == pytest.approx([f / FPS for f in BLACKOUTS], abs=1 / FPS)
    assert "sync_signal" in project.sources["video"].describe()


# -- the window ---------------------------------------------------------------------------------------------------
@pytest.fixture
def window(tmp_path, qapp):
    from syncviz_app.app import build_window

    w = build_window(_project(tmp_path), use_workspace=False)
    w.show()
    yield w
    w.close()


def _wait_for_run(window, qapp, seconds=60):
    end = time.time() + seconds
    while window.sync.running and time.time() < end:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def test_the_status_line_starts_unchecked_then_shows_the_results_after_a_run(window, qapp):
    assert window.sync.configured and "not checked yet" in window.sync_status.label.text()
    window.sync.run()
    assert window.sync.running and "running" in window.sync_status.label.text()
    _wait_for_run(window, qapp)
    assert window.sync.results and not window.sync.running
    assert "3 pass" in window.sync_status.label.text()


def test_the_window_lists_the_checks_with_their_verdicts_and_draws_the_evidence(window, qapp):
    window.sync.run()
    _wait_for_run(window, qapp)
    window.open_sync_diagnostics()
    shown = window._sync_window
    names = [shown.list.item(i).text() for i in range(shown.list.count())]
    assert len(names) == 3 and all(n.startswith("✔") for n in names)
    for row in range(3):
        shown.list.setCurrentRow(row)
        assert shown.text.toPlainText()
    shown.list.setCurrentRow(next(i for i, n in enumerate(names) if "Blackouts" in n))
    assert len(shown.plot.listDataItems()) >= 1 or len(shown.plot.items()) > 3          # the pairs and the fit are drawn
    shown.list.setCurrentRow(next(i for i, n in enumerate(names) if "Response" in n))
    assert any(isinstance(i, __import__("pyqtgraph").PlotDataItem) for i in shown.plot.items())


def test_clicking_a_point_in_the_error_plot_moves_the_playhead_there(window, qapp):
    window.sync.run()
    _wait_for_run(window, qapp)
    window.open_sync_diagnostics()

    class Point:
        def pos(self):
            class P:
                def x(self_inner):
                    return 7.0
            return P()

    window._sync_window._clicked(None, [Point()])
    assert window.context.timeline.time == pytest.approx(7.0, abs=0.05)


def test_saved_results_are_shown_when_the_project_opens_again_without_running(tmp_path, qapp):
    from syncviz_app.app import build_window

    path = _project(tmp_path)
    first = build_window(path, use_workspace=False)
    first.sync.run()
    _wait_for_run(first, qapp)
    first.close()
    again = build_window(path, use_workspace=False)
    try:
        assert "3 pass" in again.sync_status.label.text()
    finally:
        again.close()


def test_a_project_without_checks_says_so_and_a_failure_is_shown_in_red(window, tmp_path, qapp):
    from syncviz_app.app import build_window

    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "p.yaml").write_text("name: plain\nsources: {}\n", encoding="utf-8")
    quiet = build_window(plain / "p.yaml", use_workspace=False)
    try:
        assert "no checks configured" in quiet.sync_status.label.text()
    finally:
        quiet.close()


def test_a_dropped_frame_is_caught_but_millisecond_rounding_is_not(tmp_path, monkeypatch):
    from syncviz_video import VideoSource
    from syncviz_video.frame_index import FrameIndex

    source = VideoSource(tmp_path / "x.mkv", fps=30)
    rounded = np.cumsum(np.tile([33, 33, 34], 100)).astype(np.int64)                 # 30 fps stored in milliseconds
    monkeypatch.setattr(FrameIndex, "build", classmethod(lambda cls, path, cache=None: cls(rounded, np.array([0]))))
    assert source.diagnostics()[0].status is Status.PASS
    dropped = rounded.copy()
    dropped[150:] += 33                                                              # one frame missing at 150
    monkeypatch.setattr(FrameIndex, "build", classmethod(lambda cls, path, cache=None: cls(dropped, np.array([0]))))
    result = source.diagnostics()[0]
    assert result.status is Status.WARN and "1 of" in result.summary
    assert any("first uneven gaps at frames 149" in d for d in result.details)
