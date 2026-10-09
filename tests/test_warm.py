"""Slow, once-only work is done when a session opens, not at the first click (the first open of the 'Other events' list froze the
application for seconds on a large file)."""

import os

import pytest

pytest.importorskip("pynwb")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from syncviz_nwb import NWBSource

from test_descriptions import _write_nwb
from test_epochs import qapp, window  # noqa: F401  (fixtures)


def test_the_nwb_file_is_parsed_once_however_many_reads_follow(tmp_path):
    _write_nwb(tmp_path / "s.nwb")
    source = NWBSource(tmp_path / "s.nwb")
    opened = []
    original = source._open
    source._open = lambda: (opened.append(1), original())[1]
    source.catalog()
    source.read_events("processing/behavior/licks")
    source.read_intervals("intervals/trials")
    source.read_intervals("processing/behavior/contacts_C0")
    source.catalog()
    assert len(opened) == 1
    source.close()
    source.read_intervals("intervals/trials")                                   # still works after a close: it is simply opened again
    assert len(opened) == 2
    source.close()


def test_reads_from_two_threads_at_once_are_safe(tmp_path):
    import threading
    _write_nwb(tmp_path / "s.nwb")
    source = NWBSource(tmp_path / "s.nwb")
    errors = []

    def work():
        try:
            for _ in range(20):
                assert set(source.read_events("processing/behavior/licks")) == {"left", "right"}
                source.catalog()
        except Exception as exc:                                                 # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    source.close()
    assert not errors


def test_the_projects_named_events_are_loaded_when_the_window_is_built(window):
    source = window.context.resources.sources["session"]
    calls = []
    for name in ("read_events", "read_intervals", "catalog"):
        original = getattr(source, name)
        setattr(source, name, lambda *a, _o=original, _n=name, **k: (calls.append(_n), _o(*a, **k))[1])
    for name in window.context.events.names():                                  # what the tracker, hover and conditions ask for
        window.context.events.find(name)
        window.context.events.target_of(name)
    assert calls == []                                                            # all of it was already loaded


def test_opening_the_other_events_list_reads_nothing_from_the_file(window):
    tracker = window.add_view({"type": "events", "title": "Tracker"})
    tracker.resize(500, 400)
    source = window.context.resources.sources["session"]
    calls = []
    for name in ("read_events", "read_intervals", "catalog"):
        original = getattr(source, name)
        setattr(source, name, lambda *a, _o=original, _n=name, **k: (calls.append(_n), _o(*a, **k))[1])
    window.set_view_setting(tracker, "others", True)
    tracker.canvas.relayout()
    tracker.canvas.grab()
    assert calls == []
