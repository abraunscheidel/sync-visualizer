"""The loading screen shown while another session opens, so the window never looks frozen."""

import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from syncviz_app.loading import run_in_background

from test_collections import _index, project_path, qapp, window  # noqa: F401  (fixtures)


def test_work_runs_off_the_interface_thread_while_events_keep_being_handled(qapp):
    main = threading.get_ident()
    ticks = []

    def work():
        time.sleep(0.15)
        return threading.get_ident()

    from PySide6.QtCore import QTimer
    timer = QTimer()
    timer.timeout.connect(lambda: ticks.append(1))
    timer.start(10)
    other = run_in_background(work)
    timer.stop()
    assert other != main and len(ticks) >= 3                        # the interface was alive during the wait


def test_an_error_in_the_background_work_reaches_the_caller(qapp):
    def work():
        raise ValueError("no such file")

    with pytest.raises(ValueError, match="no such file"):
        run_in_background(work)


def test_switching_session_shows_the_screen_with_the_name_and_each_step_then_hides_it(window):
    seen = []
    original = window.loading.progress

    def spy(detail, done=None, total=None):
        seen.append((window.loading.isVisible(), window.loading.heading.text(), detail))
        original(detail, done, total)

    window.loading.progress = spy
    assert window.switch_collection(_index(window, "sub-B_ses-1"))
    assert seen and all(visible for visible, _, _ in seen)                         # up the whole time
    assert all("sub-B_ses-1" in heading for _, heading, _ in seen)
    details = [d for _, _, d in seen]
    assert any(d.startswith("Closing") for d in details) and any(d.startswith("Building") for d in details)
    assert not window.loading.isVisible()                                         # and gone afterwards


def test_a_session_that_cannot_open_still_takes_the_screen_down_and_changes_nothing(window, monkeypatch):
    before = window.project.active

    def broken(index):
        raise OSError("disk unplugged")

    monkeypatch.setattr(window.project, "open_collection", broken)
    assert not window.switch_collection(_index(window, "sub-B_ses-1"))
    assert not window.loading.isVisible() and window.project.active == before


def test_a_second_switch_while_one_is_loading_is_refused(window):
    window.loading.begin("Opening something", "")
    try:
        assert not window.switch_collection(_index(window, "sub-B_ses-1"))
    finally:
        window.loading.end()


def test_the_screen_covers_the_whole_window_and_follows_its_size(window):
    window.loading.begin("Opening", "")
    try:
        assert window.loading.geometry() == window.rect()
        window.resize(1100, 700)
        QApplication.instance().processEvents()
        assert window.loading.geometry() == window.rect()
    finally:
        window.loading.end()
