"""Event badges over the video picture."""

import os
import time
from datetime import datetime, timezone

import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox
from pynwb import NWBFile, NWBHDF5IO
from pynwb.behavior import BehavioralEvents
from pynwb.epoch import TimeIntervals

from syncviz.core import Seek
from syncviz_app.app import build_window
from syncviz_video.overlays import CORNERS, OFF, CornerBadges

from test_app_smoke import FPS, _pump, _reopen, _write_video

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

LICKS = [1.0, 2.0]
CONTACT = (3.0, 3.5)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _rows(**kinds):
    return [{"name": "Lick", "kind": "events", "data": np.array(LICKS)},
            {"name": "Contact", "kind": "intervals", "data": (np.array([CONTACT[0]]), np.array([CONTACT[1]]))}]


# -- the layer -------------------------------------------------------------------------------------
def test_an_event_badge_lights_at_the_event_and_fades_and_an_interval_stays_lit_while_it_lasts(qapp):
    badges = CornerBadges(_rows(), decay=0.2)
    badges.set_time(1.0)
    assert dict((n, round(v, 2)) for _s, n, v in badges.lit()) == {"Lick": 1.0}
    badges.set_time(1.1)
    assert dict((n, round(v, 2)) for _s, n, v in badges.lit()) == {"Lick": 0.5}
    badges.set_time(1.3)
    assert badges.lit() == []
    badges.set_time(3.2)
    assert [n for _s, n, _v in badges.lit()] == ["Contact"]
    badges.set_time(3.4999)
    assert badges.levels[1] == 1.0
    badges.set_time(3.6)
    assert 0 < badges.levels[1] < 1.0


def test_an_event_that_has_not_happened_yet_shows_no_badge(qapp):
    badges = CornerBadges(_rows())
    badges.set_time(0.5)
    assert badges.lit() == []


def test_hidden_events_are_never_shown_and_the_others_keep_their_slots(qapp):
    badges = CornerBadges(_rows(), hidden={"Lick"})
    badges.set_time(1.0)
    assert badges.lit() == []
    badges.set_time(3.2)
    assert badges.lit() == [(0, "Contact", 1.0)]                  # the first shown row takes the first slot
    shown = CornerBadges(_rows())
    shown.set_time(3.2)
    assert shown.lit() == [(1, "Contact", 1.0)]                    # with the lick row shown, contact keeps slot 1 even while the lick is dark


def test_the_corner_must_be_a_known_one_or_off(qapp):
    badges = CornerBadges(_rows())
    for corner in (*CORNERS, OFF):
        badges.set_corner(corner)
    with pytest.raises(ValueError, match="top-right"):
        badges.set_corner("middle")
    with pytest.raises(ValueError):
        CornerBadges(_rows(), decay=0)


def _alpha(image):
    """The alpha channel of an ARGB32 image as an array (rows by columns)."""
    raw = np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine() // 4, 4)
    return raw[:, : image.width(), 3]


def _painted(badges, corner, size=(400, 300)):
    badges.set_corner(corner)
    image = QImage(*size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    badges.paint(painter, QRectF(0, 0, *size))
    painter.end()
    ys, xs = np.nonzero(_alpha(image))
    return image, (xs, ys)


@pytest.mark.parametrize("corner, left, top", [("top-left", True, True), ("top-right", False, True),
                                               ("bottom-left", True, False), ("bottom-right", False, False)])
def test_badges_are_drawn_in_the_chosen_corner_and_nowhere_else(qapp, corner, left, top):
    badges = CornerBadges(_rows())
    badges.set_time(1.0)
    _image, (xs, ys) = _painted(badges, corner)
    assert len(xs) > 100
    assert (xs.max() < 200) == left and (ys.max() < 150) == top
    assert (xs < 200).all() if left else (xs >= 200).all()
    assert (ys < 150).all() if top else (ys >= 150).all()


def test_with_the_corner_off_nothing_is_drawn(qapp):
    badges = CornerBadges(_rows())
    badges.set_time(1.0)
    _image, (xs, _ys) = _painted(badges, OFF)
    assert len(xs) == 0


def test_a_fainter_badge_is_drawn_fainter(qapp):
    badges = CornerBadges(_rows(), decay=0.2)
    badges.set_time(1.0)
    bright, _ = _painted(badges, "top-right")
    badges.set_time(1.15)
    faint, _ = _painted(badges, "top-right")
    assert _alpha(bright)[:60, 250:].max() > _alpha(faint)[:60, 250:].max() > 0


# -- in the view and the window --------------------------------------------------------------------------
def _write_nwb(path):
    nwb = NWBFile(session_description="s", identifier="o", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial(start_time=0.0, stop_time=5.0)
    behavior = nwb.create_processing_module("behavior", "b")
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0] * len(LICKS), unit="n/a", timestamps=LICKS)
    behavior.add(licks)
    contacts = TimeIntervals(name="contacts_by_whisker_C0", description="c")
    contacts.add_interval(start_time=CONTACT[0], stop_time=CONTACT[1])
    behavior.add(contacts)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)


@pytest.fixture
def window(tmp_path, qapp):
    _write_video(tmp_path / "clip.mkv")
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text(f"""
name: overlays
cache: cache
sources:
  session: {{type: nwb, path: session.nwb}}
  video: {{type: video, path: clip.mkv, fps: {FPS}}}
segmentations:
  trials: {{label: Trial, from: "session:intervals/trials"}}
views:
  - type: video
    title: Clip
    source: video
    overlay:
      corner: top-right
      decay: 0.3
      rows:
        - {{name: Lick, kind: events, from: "session:processing/behavior/licks", member: left}}
        - {{name: Contact, kind: intervals, from: "session:processing/behavior/contacts_by_whisker_C0"}}
        - {{name: Missing, kind: events, from: "session:processing/behavior/nothing", member: x}}
  - type: video
    title: Plain clip
    source: video
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml")
    w.show()
    yield w
    w.close()
    qapp.processEvents()


def _video(window, title="Clip"):
    return next(v for v in window.views if v.title == title)


def _show(window, qapp, time_s):
    window.context.bus.publish(Seek(time_s))
    window.refresh_now()
    video = _video(window)
    assert _pump(qapp, until=lambda: video._shown == round(time_s * FPS))
    return video


def test_the_view_builds_its_badges_from_the_project_and_leaves_out_a_row_it_has_no_data_for(window):
    video = _video(window)
    assert video.badges is not None and video.badges.names == ["Lick", "Contact"]
    assert any("'Missing' left out" in n for n in window.context.notes)
    assert _video(window, "Plain clip").badges is None and _video(window, "Plain clip").settings() == []


def test_the_badges_follow_the_frame_on_screen_not_the_playhead(window, qapp):
    video = _video(window)
    video._wanted = 90                                           # the playhead has moved on to 3.0 s ...
    video._on_frame(30, np.full((48, 64), 100, dtype=np.uint8))  # ... but the frame that has arrived is 1.0 s (a lick)
    assert [n for _s, n, _v in video.badges.lit()] == ["Lick"]
    video._on_frame(90, np.full((48, 64), 100, dtype=np.uint8))  # now the frame at 3.0 s (inside the contact)
    assert [n for _s, n, _v in video.badges.lit()] == ["Contact"]


def test_a_badge_is_really_drawn_on_the_picture_when_its_event_is_on_screen(window, qapp):
    video = _show(window, qapp, 1.0)
    video.resize(480, 360)
    lit = video.widget.grab().toImage()
    _show(window, qapp, 0.5)
    dark = video.widget.grab().toImage()
    right = [(x, y) for x in range(lit.width() - 140, lit.width()) for y in range(0, 60) if lit.pixel(x, y) != dark.pixel(x, y)]
    assert right, "the lick badge should appear in the top-right of the picture"


def test_the_settings_offer_the_corner_and_a_switch_for_each_event(window):
    settings = _video(window).settings()
    assert [s.key for s in settings] == ["overlay.corner", "overlay.show.Lick", "overlay.show.Contact"]
    corner = settings[0]
    assert corner.kind == "choice" and corner.value == "top-right"
    assert [v for _l, v in corner.choices] == ["off", "top-left", "top-right", "bottom-left", "bottom-right"]
    assert all(s.kind == "toggle" and s.value is True for s in settings[1:])


def test_changing_a_setting_changes_the_badges_and_reset_returns_to_the_projects_defaults(window):
    video = _video(window)
    video.apply_setting("overlay.corner", "bottom-left")
    video.apply_setting("overlay.show.Lick", False)
    assert video.badges.corner == "bottom-left" and video.badges.hidden == {"Lick"}
    video.reset_settings()
    assert video.badges.corner == "top-right" and video.badges.hidden == set()


def test_the_views_list_shows_the_selected_views_settings_and_changing_them_applies_them(window):
    panel = window.views_panel
    panel.list.setCurrentRow([v.title for v in window.views].index("Clip"))
    combos = [c for c in panel.findChildren(QComboBox) if c.property("workspace") == "saved"]
    checks = [c for c in panel.findChildren(QCheckBox) if c.property("workspace") == "saved"]
    assert len(combos) == 1 and [c.text() for c in checks] == ["Lick", "Contact"]
    combos[0].setCurrentIndex(combos[0].findData("off"))
    assert _video(window).badges.corner == "off"
    checks[1].setChecked(False)
    assert _video(window).badges.hidden == {"Contact"}
    panel.list.setCurrentRow([v.title for v in window.views].index("Plain clip"))
    assert not [c for c in panel.findChildren(QCheckBox) if c.property("workspace") == "saved"]       # nothing to set here


def test_the_choices_are_saved_in_the_workspace_and_come_back(window, qapp):
    video = _video(window)
    window.set_view_setting(video, "overlay.corner", "bottom-right")
    window.set_view_setting(video, "overlay.show.Contact", False)
    window.save_workspace_as("Mine")
    again = _reopen(window, qapp, workspace_name="Mine")
    try:
        badges = _video(again).badges
        assert badges.corner == "bottom-right" and badges.hidden == {"Contact"}
    finally:
        again.close()


def test_switching_workspaces_switches_the_badge_settings_and_reset_restores_the_projects(window):
    video = _video(window)
    window.save_workspace_as("Defaults")
    window.set_view_setting(video, "overlay.corner", "off")
    window.save_workspace_as("Off")
    window.switch_workspace("Defaults")
    assert video.badges.corner == "top-right"
    window.switch_workspace("Off")
    assert video.badges.corner == "off"
    window.reset_workspace()
    assert video.badges.corner == "top-right"


def test_the_choices_are_kept_when_another_collection_is_opened(tmp_path, qapp):
    # one collection here, so the same views are rebuilt: the choice must survive a rebuild of the view
    _write_video(tmp_path / "clip.mkv")
    _write_nwb(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text(f"""
name: o
sources:
  session: {{type: nwb, path: session.nwb}}
  video: {{type: video, path: clip.mkv, fps: {FPS}}}
segmentations:
  trials: {{label: Trial, from: "session:intervals/trials"}}
views:
  - type: video
    title: Clip
    source: video
    overlay:
      rows: [{{name: Lick, kind: events, from: "session:processing/behavior/licks", member: left}}]
""", encoding="utf-8")
    window = build_window(tmp_path / "project.yaml", use_workspace=False)
    try:
        video = _video(window)
        window.set_view_setting(video, "overlay.corner", "top-left")
        window.remove_view(video, track=False)
        again = window.add_view({"type": "video", "title": "Clip", "source": "video",
                                 "overlay": {"rows": [{"name": "Lick", "kind": "events",
                                                       "from": "session:processing/behavior/licks", "member": "left"}]}})
        assert again.badges.corner == "top-left"
    finally:
        window.close()
