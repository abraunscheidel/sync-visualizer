"""Tracked points (pose): the resource, reading it from NWB, and drawing it on the video."""

import os
from datetime import datetime, timezone

import h5py
import numpy as np
import pytest
from PySide6.QtCore import QRectF
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QApplication
from pynwb import NWBFile, NWBHDF5IO

from syncviz.resources import PointTracks
from syncviz.sources import MissingDataError
from syncviz_app.app import build_window
from syncviz_nwb import NWBSource
from syncviz_video.overlays import SKELETON_STYLES, TrackedSkeletons

from test_app_smoke import FPS, _write_video
from test_video_overlays import _alpha

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _tracks(n=5, k=4, edges=((0, 1), (1, 2), (2, 3)), step=0.01):
    times = np.arange(n) * step
    xy = np.zeros((n, k, 2), dtype=np.float32)
    for i in range(k):
        xy[:, i, 0] = 100 + 50 * i                 # points spread along x, y = 200
        xy[:, i, 1] = 200
    return PointTracks(times, xy, tuple(f"marker_{i}" for i in range(k)), tuple(edges))


# -- the resource -------------------------------------------------------------------------------------
def test_the_positions_at_a_time_are_those_of_the_nearest_sample_and_none_when_tracking_is_absent():
    tracks = _tracks()
    assert tracks.at(0.021).shape == (4, 2) and np.allclose(tracks.at(0.021)[:, 0], [100, 150, 200, 250])
    assert tracks.at(0.5) is None and tracks.at(-0.5) is None
    assert tracks.at(0.0449) is not None                          # within one and a half intervals of the last sample (0.04)
    assert PointTracks(np.empty(0), np.empty((0, 4, 2)), ("a", "b", "c", "d")).at(0.0) is None


def test_inconsistent_shapes_are_refused():
    with pytest.raises(ValueError):
        PointTracks(np.arange(3.0), np.zeros((4, 2, 2)), ("a", "b"))
    with pytest.raises(ValueError):
        PointTracks(np.arange(3.0), np.zeros((3, 2, 2)), ("a", "b", "c"))
    with pytest.raises(ValueError):
        PointTracks(np.array([1.0, 0.0]), np.zeros((2, 1, 2)), ("a",))


def test_the_chain_orders_points_along_a_skeleton_whichever_way_the_edges_are_listed():
    assert _tracks(edges=((0, 1), (1, 2), (2, 3))).chain() == [0, 1, 2, 3]
    assert _tracks(edges=((3, 2), (2, 1), (1, 0))).chain() == [0, 1, 2, 3]
    assert _tracks(edges=((1, 2), (0, 1), (2, 3))).chain() == [0, 1, 2, 3]
    assert _tracks(edges=((0, 1), (0, 2), (0, 3))).chain() == [0, 1, 2, 3]       # a star is not a chain: natural order
    assert _tracks(edges=()).chain() == [0, 1, 2, 3]


# -- reading from NWB ----------------------------------------------------------------------------------
def _write_with_pose(path):
    nwb = NWBFile(session_description="s", identifier="p", session_start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    nwb.add_trial(start_time=0.0, stop_time=10.0)
    with NWBHDF5IO(str(path), "w") as io:
        io.write(nwb)
    n = 400
    t = np.arange(n) / 100.0
    with h5py.File(path, "a") as f:
        pose = f.create_group("extra/pose_A")
        pose.attrs["neurodata_type"] = "PoseEstimation"
        nodes = [f"marker_{i}" for i in range(4)]
        pose.create_dataset("nodes", data=np.array(nodes, dtype="S"))
        pose.create_dataset("edges", data=np.array([[0, 1], [1, 2], [2, 3]]))
        pose.create_dataset("description", data="4 markers, 0 the tip")
        for i, name in enumerate(nodes):
            series = pose.create_group(name)
            xy = np.stack([300 - 50 * i + 0 * t + t * 10, 200 + 20 * i + 0 * t], axis=1)         # x moves 10 px per second
            series.create_dataset("data", data=xy).attrs["conversion"] = 0.05
            series.create_dataset("timestamps", data=t)
        f["extra"].create_group("not_pose").attrs["neurodata_type"] = "Other"


def test_pose_estimation_is_read_as_point_tracks_in_the_order_the_file_lists_the_nodes(tmp_path):
    _write_with_pose(tmp_path / "p.nwb")
    tracks = NWBSource(tmp_path / "p.nwb").read_points("extra/pose_A")
    assert tracks.names == ("marker_0", "marker_1", "marker_2", "marker_3") and tracks.edges == ((0, 1), (1, 2), (2, 3))
    assert tracks.xy.shape == (400, 4, 2) and tracks.xy.dtype == np.float32
    assert np.allclose(tracks.xy[100, :, 0], [300 + 10, 250 + 10, 200 + 10, 150 + 10])          # stored numbers: no unit conversion applied
    assert tracks.times[-1] == pytest.approx(3.99) and "tip" in tracks.metadata["description"]
    assert tracks.metadata["stored_conversion"] == 0.05


def test_a_path_that_is_not_pose_estimation_says_so_calmly(tmp_path):
    _write_with_pose(tmp_path / "p.nwb")
    source = NWBSource(tmp_path / "p.nwb")
    for path in ("extra/not_pose", "extra/missing"):
        with pytest.raises(MissingDataError):
            source.read_points(path)


def test_sources_without_points_say_so():
    from syncviz.sources import Source

    class Plain(Source):
        def describe(self):
            return []

    with pytest.raises(MissingDataError):
        Plain().read_points("x")


# -- drawing -----------------------------------------------------------------------------------------------
def _item(order=None, **kw):
    tracks = _tracks()
    item = {"name": "Whisker", "group": None, "tracks": tracks, "scale": 1.0, "order": order or tracks.chain(),
            "color": QColor(255, 0, 0)}
    item.update(kw)
    return item


def _drawn(layer, size=(400, 300)):
    image = QImage(*size, QImage.Format.Format_ARGB32)
    image.fill(QColor(0, 0, 0, 0))
    painter = QPainter(image)
    layer.paint(painter, QRectF(0, 0, *size), size)
    painter.end()
    return _alpha(image)


def test_the_curve_runs_through_the_region_between_the_points_and_the_dots_do_not(qapp):
    layer = TrackedSkeletons([_item()], style="curve")
    layer.set_time(0.02)
    curve = _drawn(layer)
    assert curve[200, 125] > 0 and curve[200, 175] > 0 and curve[200, 100] > 0 and curve[200, 250] > 0     # along the whole whisker
    layer.set_style("points")
    dots = _drawn(layer)
    assert dots[200, 100] > 0 and dots[200, 150] > 0 and dots[200, 250] > 0                                  # at each marker
    assert dots[200, 125] == 0 and dots[200, 175] == 0                                                        # not between them
    layer.set_style("both")
    both = _drawn(layer)
    assert both[200, 125] > 0 and both[200, 150] > 0


def test_nothing_is_drawn_when_tracking_is_absent_or_the_item_is_hidden(qapp):
    layer = TrackedSkeletons([_item()], style="both")
    layer.set_time(5.0)                                            # far from any sample
    assert layer.points == [None] and not _drawn(layer).any()
    layer.set_time(0.02)
    layer.set_hidden({"Whisker"})
    assert not _drawn(layer).any()


def test_a_point_that_is_missing_in_a_frame_is_skipped_not_drawn_at_the_origin(qapp):
    tracks = _tracks()
    xy = np.array(tracks.xy)
    xy[2, 1, :] = np.nan
    layer = TrackedSkeletons([_item(tracks=PointTracks(tracks.times, xy, tracks.names, tracks.edges))], style="points")
    layer.set_time(0.02)
    drawn = _drawn(layer)
    assert drawn[200, 100] > 0 and drawn[200, 200] > 0 and drawn[200, 150] == 0 and drawn[0:20, 0:20].sum() == 0


def test_stored_units_are_scaled_by_the_items_scale(qapp):
    layer = TrackedSkeletons([_item(scale=0.5)], style="points")
    layer.set_time(0.02)
    drawn = _drawn(layer)
    assert drawn[100, 50] > 0 and drawn[100, 125] > 0              # x and y halved


def test_the_style_must_be_a_known_one(qapp):
    layer = TrackedSkeletons([_item()])
    for style in SKELETON_STYLES:
        layer.set_style(style)
    with pytest.raises(ValueError, match="curve"):
        layer.set_style("zigzag")


# -- in the view -----------------------------------------------------------------------------------------------
@pytest.fixture
def window(tmp_path, qapp):
    _write_video(tmp_path / "clip.mkv")
    _write_with_pose(tmp_path / "session.nwb")
    (tmp_path / "project.yaml").write_text(f"""
name: pose
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
      skeleton_style: points
      skeletons:
        - {{name: Whisker A, group: Whiskers, from: "session:extra/pose_A"}}
        - {{name: Whisker B, from: "session:extra/absent"}}
""", encoding="utf-8")
    w = build_window(tmp_path / "project.yaml")
    w.show()
    yield w
    w.close()


def _video(window):
    return next(v for v in window.views if v.title == "Clip")


def test_the_view_builds_skeletons_from_the_project_and_leaves_out_one_it_has_no_data_for(window):
    video = _video(window)
    assert video.skeletons.names == ["Whisker A"] and video.skeletons.style == "points"
    assert any("'Whisker B' left out" in n for n in window.context.notes)


def test_the_style_and_each_skeleton_are_settings_that_reset_to_the_projects_choice(window):
    video = _video(window)
    settings = {s.key: s for s in video.settings()}
    style = settings["overlay.skeleton_style"]
    assert style.kind == "choice" and style.value == "points" and [v for _l, v in style.choices] == ["curve", "points", "both"]
    assert settings["overlay.track.Whisker A"].group == "Whiskers"
    video.apply_setting("overlay.skeleton_style", "curve")
    video.apply_setting("overlay.track.Whisker A", False)
    assert video.skeletons.style == "curve" and video.skeletons.hidden == {"Whisker A"}
    video.reset_settings()
    assert video.skeletons.style == "points" and video.skeletons.hidden == set()


def test_the_style_choice_is_saved_in_the_workspace(window, qapp):
    from test_app_smoke import _reopen

    window.set_view_setting(_video(window), "overlay.skeleton_style", "both")
    window.save_workspace_as("Both")
    again = _reopen(window, qapp, workspace_name="Both")
    try:
        assert _video(again).skeletons.style == "both"
    finally:
        again.close()


def test_the_overlay_follows_the_frame_on_screen(window):
    video = _video(window)
    video._shown = 100                                             # 100 frames at 30 fps = 3.33 s: the markers have moved 33 px
    video._update_layers()
    assert np.allclose(video.skeletons.points[0][0, 0], 300 + 33.3, atol=0.5)
