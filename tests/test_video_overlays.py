"""Event badges over the video picture."""

import os
import time
from datetime import datetime, timezone

import numpy as np
import pytest
from PySide6.QtCore import QRectF, Qt
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
    return raw[:, : image.width(), 3].copy()                     # a copy: the buffer belongs to the image


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
    assert [s.key for s in settings] == ["overlay.enabled", "overlay.corner", "overlay.show.Lick", "overlay.show.Contact"]
    assert settings[0].kind == "toggle" and settings[0].value is True            # one switch for all overlays
    corner = settings[1]
    assert corner.kind == "choice" and corner.value == "top-right"
    assert [v for _l, v in corner.choices] == ["off", "top-left", "top-right", "bottom-left", "bottom-right"]
    assert all(s.kind == "toggle" and s.value is True for s in settings[2:])


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
    assert len(combos) == 1 and [c.text() for c in checks] == ["Show overlays", "Lick", "Contact"]
    combos[0].setCurrentIndex(combos[0].findData("off"))
    assert _video(window).badges.corner == "off"
    checks[2].setChecked(False)
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


# -- tracked lines and contact markers ---------------------------------------------------------------------------------
from syncviz_video.overlays import ContactMarkers, TrackedLines


def _line_item(**kw):
    times = np.array([1.00, 1.01, 1.02, 1.05])               # a gap after 1.02
    item = {"name": "Whisker", "times": times, "base_x": np.array([100.0, 101, 102, 105]), "base_y": np.array([200.0, 201, 202, 205]),
            "tip_x": np.array([10.0, 11, np.nan, 15]), "tip_y": np.array([20.0, 21, 22, 25]), "scale": 1.0,
            "color": QColor(255, 0, 0), "max_gap": 0.015}
    item.update(kw)
    return item


def test_a_tracked_line_is_placed_from_the_sample_nearest_the_frame_and_not_drawn_when_there_is_none_close_enough(qapp):
    lines = TrackedLines([_line_item()])
    lines.set_time(1.012)
    assert lines.points[0] == (101.0, 201.0, 11.0, 21.0)          # the nearest sample is 1.01
    lines.set_time(1.035)                                          # in the gap: 15 ms from both neighbours is too far
    assert lines.points[0] is None
    lines.set_time(0.5)
    assert lines.points[0] is None
    lines.set_time(1.02)                                           # the sample here has no tip: nothing is drawn, not a half line
    assert lines.points[0] is None


def test_stored_units_are_scaled_to_picture_pixels(qapp):
    lines = TrackedLines([_line_item(scale=20.0)])
    lines.set_time(1.0)
    assert lines.points[0] == (2000.0, 4000.0, 200.0, 400.0)


def _drawn_alpha(layer, size=(400, 300), rect=QRectF(0, 0, 400, 300), image_size=(400, 300)):
    image = QImage(*size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    layer.paint(painter, rect, image_size)
    painter.end()
    return _alpha(image)


def test_a_line_is_drawn_between_its_two_points_in_the_scaled_picture_position(qapp):
    item = _line_item(times=np.array([1.0]), base_x=np.array([300.0]), base_y=np.array([200.0]), tip_x=np.array([100.0]),
                      tip_y=np.array([100.0]))
    lines = TrackedLines([item])
    lines.set_time(1.0)
    alpha = _drawn_alpha(lines)
    assert alpha[200, 300] > 0 and alpha[100, 100] > 0 and alpha[150, 200] > 0         # both ends and the middle
    assert alpha[10, 10] == 0 and alpha[250, 50] == 0
    # the picture shown at half size and offset: points land accordingly
    half = _drawn_alpha(lines, rect=QRectF(50, 20, 200, 150), image_size=(400, 300))
    assert half[20 + 100, 50 + 150] > 0 and half[20 + 50, 50 + 50] > 0 and half[200, 300] == 0


def test_hidden_lines_are_not_drawn(qapp):
    lines = TrackedLines([_line_item(times=np.array([1.0]), base_x=np.array([300.0]), base_y=np.array([200.0]),
                                     tip_x=np.array([100.0]), tip_y=np.array([100.0]))], hidden={"Whisker"})
    lines.set_time(1.0)
    assert not _drawn_alpha(lines).any()


def _marker_item():
    return {"name": "Touch", "starts": np.array([2.0, 5.0]), "stops": np.array([2.5, 5.2]), "x": np.array([100.0, 300.0]),
            "y": np.array([120.0, 80.0]), "scale": 1.0, "color": QColor(0, 255, 0)}


def test_a_contact_ring_is_at_that_contacts_own_position_while_it_lasts_then_fades(qapp):
    markers = ContactMarkers([_marker_item()], decay=0.2)
    markers.set_time(1.0)
    assert markers.state[0] is None
    markers.set_time(2.2)
    assert markers.state[0] == (100.0, 120.0, 1.0)
    markers.set_time(5.1)
    assert markers.state[0] == (300.0, 80.0, 1.0)                    # the second contact, at its own position
    markers.set_time(5.3)
    assert 0 < markers.state[0][2] < 1.0
    markers.set_time(6.0)
    assert markers.state[0] is None


def test_the_ring_is_drawn_around_the_position_and_not_at_it(qapp):
    markers = ContactMarkers([_marker_item()])
    markers.set_time(2.2)
    alpha = _drawn_alpha(markers)
    assert alpha[120, 100 + 16] > 0 and alpha[120 + 16, 100] > 0       # on the ring
    assert alpha[120, 100] == 0                                          # empty inside it


def test_nwb_keeps_the_unit_conversion_so_pixels_can_be_recovered(tmp_path):
    from pynwb.behavior import BehavioralTimeSeries
    from syncviz_nwb import NWBSource

    nwb = NWBFile(session_description="s", identifier="c", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    behavior = nwb.create_processing_module("behavior", "b")
    ts = BehavioralTimeSeries(name="pos")
    ts.create_timeseries(name="x", data=np.array([600.0, 610.0]), unit="mm", conversion=0.05, timestamps=[0.0, 1.0])
    ts.create_timeseries(name="plain", data=np.array([1.0, 2.0]), unit="s", timestamps=[0.0, 1.0])
    behavior.add(ts)
    with NWBHDF5IO(str(tmp_path / "c.nwb"), "w") as io:
        io.write(nwb)
    members = NWBSource(tmp_path / "c.nwb").read_timeseries("processing/behavior/pos")
    assert members["x"].values == pytest.approx([30.0, 30.5]) and members["x"].metadata["conversion"] == 0.05
    assert members["plain"].metadata == {}


@pytest.fixture
def tracked_window(tmp_path, qapp):
    from pynwb.behavior import BehavioralTimeSeries

    _write_video(tmp_path / "clip.mkv")
    nwb = NWBFile(session_description="s", identifier="t", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial(start_time=0.0, stop_time=11.0)
    behavior = nwb.create_processing_module("behavior", "b")
    t = np.arange(0, 11.0, 1 / FPS)
    pos = BehavioralTimeSeries(name="pos_C0")
    for name, base in (("base_x", 60.0), ("base_y", 40.0), ("tip_x", 10.0), ("tip_y", 20.0)):
        pos.create_timeseries(name=name, data=base + t, unit="mm", conversion=0.05, timestamps=t)   # stored in pixels
    behavior.add(pos)
    contacts = TimeIntervals(name="contacts_C0", description="c")
    contacts.add_column(name="tip_x", description="x")
    contacts.add_column(name="tip_y", description="y")
    contacts.add_interval(start_time=3.0, stop_time=3.5, tip_x=33.0, tip_y=22.0)
    behavior.add(contacts)
    with NWBHDF5IO(str(tmp_path / "session.nwb"), "w") as io:
        io.write(nwb)
    (tmp_path / "project.yaml").write_text(f"""
name: tracked
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
      lines:
        - {{name: Whisker, from: "session:processing/behavior/pos_C0", base: [base_x, base_y], tip: [tip_x, tip_y]}}
        - {{name: Ghost, from: "session:processing/behavior/absent", base: [base_x, base_y], tip: [tip_x, tip_y]}}
      markers:
        - {{name: Touch, from: "session:processing/behavior/contacts_C0", x: tip_x, y: tip_y, color_of: Whisker}}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml", use_workspace=False)
    w.show()
    yield w
    w.close()


def test_the_view_places_tracked_lines_in_picture_pixels_even_though_the_series_is_in_other_units(tracked_window):
    video = next(v for v in tracked_window.views if v.title == "Clip")
    assert [type(layer).__name__ for layer in video.widget.layers] == ["TrackedLines", "ContactMarkers"]
    assert video.lines.names == ["Whisker"] and any("'Ghost' left out" in n for n in tracked_window.context.notes)
    video._shown = 60                                                # frame 60 is 2.0 s
    video._update_layers()
    bx, by, tx, ty = video.lines.points[0]
    assert (bx, by, tx, ty) == pytest.approx((62.0, 42.0, 12.0, 22.0), abs=0.6)       # stored pixels, not the mm the series reports


def test_the_marker_takes_the_colour_of_the_line_it_names_and_is_drawn_at_the_contact(tracked_window):
    video = next(v for v in tracked_window.views if v.title == "Clip")
    assert video.markers.items[0]["color"] == video.lines.items[0]["color"]
    video._shown = round(3.2 * FPS)
    video._update_layers()
    assert video.markers.state[0][:2] == (33.0, 22.0)


def test_each_tracked_thing_can_be_switched_off_and_the_projects_choice_comes_back_on_reset(tracked_window):
    video = next(v for v in tracked_window.views if v.title == "Clip")
    keys = [s.key for s in video.settings()]
    assert keys == ["overlay.enabled", "overlay.track.Whisker", "overlay.track.Touch"]
    video.apply_setting("overlay.track.Whisker", False)
    video.apply_setting("overlay.track.Touch", False)
    assert video.lines.hidden == {"Whisker"} and video.markers.hidden == {"Touch"}
    video.reset_settings()
    assert video.lines.hidden == set() and video.markers.hidden == set()


# -- groups and the master switch ---------------------------------------------------------------------------------------
@pytest.fixture
def grouped_window(tmp_path, qapp):
    """Badges and drawings, some grouped (a group can mix badges and drawings), one ungrouped."""
    from pynwb.behavior import BehavioralTimeSeries

    _write_video(tmp_path / "clip.mkv")
    nwb = NWBFile(session_description="s", identifier="g", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial(start_time=0.0, stop_time=11.0)
    behavior = nwb.create_processing_module("behavior", "b")
    t = np.arange(0, 11.0, 1 / FPS)
    for w in ("A", "B"):
        pos = BehavioralTimeSeries(name=f"pos_{w}")
        for name, base in (("base_x", 60.0), ("base_y", 40.0), ("tip_x", 10.0), ("tip_y", 20.0)):
            pos.create_timeseries(name=name, data=base + t, unit="px", timestamps=t)
        behavior.add(pos)
    licks = BehavioralEvents(name="licks")
    licks.create_timeseries(name="left", data=[1.0, 1.0], unit="n/a", timestamps=LICKS)
    behavior.add(licks)
    with NWBHDF5IO(str(tmp_path / "session.nwb"), "w") as io:
        io.write(nwb)
    lines = "\n".join(f'        - {{name: Whisker {w}, group: Whiskers, from: "session:processing/behavior/pos_{w}", base: [base_x, base_y], tip: [tip_x, tip_y]}}' for w in "AB")
    (tmp_path / "project.yaml").write_text(f"""
name: grouped
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
      rows:
        - {{name: Lick, group: Events, kind: events, from: "session:processing/behavior/licks", member: left}}
      lines:
{lines}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml")
    w.show()
    yield w
    w.close()


def _checks(panel):
    return {c.text(): c for c in panel.findChildren(QCheckBox) if c.property("workspace")}


def _select_clip(window):
    panel = window.views_panel
    panel.list.setCurrentRow([v.title for v in window.views].index("Clip"))
    return panel


def test_settings_carry_their_group(grouped_window):
    groups = {s.label: s.group for s in next(v for v in grouped_window.views).settings() if s.kind == "toggle"}
    assert groups == {"Show overlays": None, "Lick": "Events", "Draw Whisker A": "Whiskers", "Draw Whisker B": "Whiskers"}


def test_a_group_has_one_switch_above_its_members_and_it_reflects_them(grouped_window):
    panel = _select_clip(grouped_window)
    checks = _checks(panel)
    assert {"Whiskers", "Events", "Show overlays", "Draw Whisker A", "Draw Whisker B", "Lick"} <= set(checks)
    group = checks["Whiskers"]
    assert group.checkState() == Qt.CheckState.Checked
    checks["Draw Whisker A"].setChecked(False)
    assert group.checkState() == Qt.CheckState.PartiallyChecked
    checks["Draw Whisker B"].setChecked(False)
    assert group.checkState() == Qt.CheckState.Unchecked
    checks["Draw Whisker A"].setChecked(True)
    checks["Draw Whisker B"].setChecked(True)
    assert group.checkState() == Qt.CheckState.Checked


def test_the_group_switch_turns_all_its_members_off_and_on_and_the_others_are_untouched(grouped_window):
    panel = _select_clip(grouped_window)
    video = _video(grouped_window)
    group = _checks(panel)["Whiskers"]
    group.click()                                                      # all on: so off
    assert video.lines.hidden == {"Whisker A", "Whisker B"} and video.badges.hidden == set()
    assert all(not _checks(panel)[n].isChecked() for n in ("Draw Whisker A", "Draw Whisker B")) and _checks(panel)["Lick"].isChecked()
    _checks(panel)["Whiskers"].click()
    assert video.lines.hidden == set()
    _checks(panel)["Draw Whisker A"].setChecked(False)                 # mixed: a click turns everything on
    _checks(panel)["Whiskers"].click()
    assert video.lines.hidden == set()


def test_the_master_switch_hides_every_drawing_without_forgetting_the_individual_choices(grouped_window, qapp):
    video = _video(grouped_window)
    video.apply_setting("overlay.track.Whisker A", False)
    video.apply_setting("overlay.enabled", False)
    assert video.widget.layers_visible is False
    assert video.lines.hidden == {"Whisker A"}                         # unchanged underneath
    video.apply_setting("overlay.enabled", True)
    assert video.widget.layers_visible and video.lines.hidden == {"Whisker A"}


def test_with_the_master_switch_off_nothing_is_painted_over_the_picture(grouped_window, qapp):
    video = _video(grouped_window)
    video.resize(480, 360)
    video._wanted = 30
    video._on_frame(30, np.full((48, 64), 120, dtype=np.uint8))       # a frame, with a lick on it and tracked lines
    on = video.widget.grab().toImage()
    video.apply_setting("overlay.enabled", False)
    off = video.widget.grab().toImage()
    video.apply_setting("overlay.enabled", True)
    again = video.widget.grab().toImage()
    assert on != off and on == again


def test_the_group_switch_is_not_saved_but_its_members_and_the_master_switch_are(grouped_window):
    panel = _select_clip(grouped_window)
    checks = _checks(panel)
    assert checks["Whiskers"].property("workspace").startswith("not saved")
    assert all(checks[n].property("workspace") == "saved" for n in ("Show overlays", "Lick", "Draw Whisker A"))


def test_group_choices_are_saved_with_the_workspace_and_reset_with_it(grouped_window, qapp):
    window = grouped_window
    panel = _select_clip(window)
    _checks(panel)["Whiskers"].click()
    window.set_view_setting(_video(window), "overlay.enabled", False)
    window.save_workspace_as("Hidden")
    window.reset_workspace()
    assert _video(window).lines.hidden == set() and _video(window).widget.layers_visible
    window.switch_workspace("Hidden")
    assert _video(window).lines.hidden == {"Whisker A", "Whisker B"} and not _video(window).widget.layers_visible


def test_nothing_is_drawn_on_a_blank_frame_and_the_overlays_come_back_with_the_picture(window, qapp):
    video = _video(window)
    video.resize(480, 360)
    video.show()
    painted = []

    class Spy:
        def set_time(self, _t):
            pass

        def paint(self, _p, _target, _size):
            painted.append(1)

    video.widget.layers.append(Spy())
    video._wanted = 30
    video._on_frame(30, np.zeros((48, 64), dtype=np.uint8))          # a blackout: there is no picture to annotate
    video.widget.grab()
    assert video.widget.blank and not painted
    video._wanted = 31
    video._on_frame(31, np.full((48, 64), 100, dtype=np.uint8))
    video.widget.grab()
    assert not video.widget.blank and painted
    video._wanted = 32
    video._on_frame(32, np.full((48, 64), 40, dtype=np.uint8))       # a dim picture is still a picture
    assert not video.widget.blank
