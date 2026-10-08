import av
import numpy as np
import pytest

from syncviz.cache import DiskCache
from syncviz_video import FrameIndex, FrameReader

N_FRAMES = 120


def level_of(i: int) -> int:
    """Distinct, well-separated gray level per frame so a wrong frame is obvious."""
    return 20 + (i * 37) % 200


def write_video(path, n=N_FRAMES, size=(64, 48), fps=30, gop=10, bframes=2):
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "8", "g": str(gop), "bf": str(bframes), "sc_threshold": "0"}
        for i in range(n):
            img = np.full((size[1], size[0]), level_of(i), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="gray").reformat(format="yuv420p")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


@pytest.fixture(scope="module", params=["mp4", "mkv"])
def video(request, tmp_path_factory):
    path = tmp_path_factory.mktemp("v") / f"clip.{request.param}"
    write_video(path)
    return path


@pytest.fixture
def reader(video):
    index = FrameIndex.build(video)
    with FrameReader(video, index) as r:
        yield r


def expected_luma(level: int) -> float:
    """Encoding full-range gray as video yuv420p maps 0-255 onto luma 16-235."""
    return 16 + level * 219 / 255


def assert_is_frame(image, i):
    assert abs(float(image.mean()) - expected_luma(level_of(i))) < 4, f"frame {i} has wrong content"


def test_index_counts_every_frame_and_starts_at_a_keyframe(video):
    index = FrameIndex.build(video)

    assert index.n_frames == N_FRAMES
    assert index.keyframes[0] == 0
    assert len(index.keyframes) >= N_FRAMES // 10


def test_random_access_returns_the_requested_frames(reader):
    # Includes keyframe boundaries, frames just before/after them, first and last.
    for i in [0, 1, 9, 10, 11, 57, 58, 99, 100, 119, 3, 118, 60]:
        assert_is_frame(reader.read_frame(i), i)


def test_range_matches_individual_reads(reader):
    block = reader.read_frames(33, 48)

    assert block.shape[0] == 15
    for k, i in enumerate(range(33, 48)):
        assert_is_frame(block[k], i)


def test_iter_frames_is_sequential_and_complete(reader):
    numbers = [n for n, _ in reader.iter_frames(5, 95)]

    assert numbers == list(range(5, 95))


def test_backward_seeks_work_after_forward_reads(reader):
    reader.read_frames(80, 100)
    assert_is_frame(reader.read_frame(12), 12)
    assert_is_frame(reader.read_frame(115), 115)


@pytest.mark.parametrize("bad", [-1, N_FRAMES, N_FRAMES + 50])
def test_out_of_range_frame_rejected(reader, bad):
    with pytest.raises(IndexError):
        reader.read_frame(bad)


def test_index_is_cached(video, tmp_path):
    cache = DiskCache(tmp_path / "cache")
    first = FrameIndex.build(video, cache=cache)

    assert len(list((tmp_path / "cache").glob("frame_index-*.npy"))) == 1
    second = FrameIndex.build(video, cache=cache)
    np.testing.assert_array_equal(first.pts, second.pts)
    np.testing.assert_array_equal(first.keyframes, second.keyframes)


def test_duplicate_timestamps_rejected():
    table = np.array([[0, 1], [10, 0], [10, 0]], dtype=np.int64)

    with pytest.raises(ValueError, match="duplicate"):
        FrameIndex.from_packet_table(table)


def test_luma_falls_back_when_first_plane_is_not_brightness(tmp_path):
    """Planar RGB stores green in plane 0. Reading it as luma would be silently wrong."""
    from syncviz_video.frames import has_native_luma, luma

    path = tmp_path / "rgb.mkv"
    try:
        with av.open(str(path), "w") as container:
            stream = container.add_stream("libx264rgb", rate=30)
            stream.width, stream.height = 64, 48
            stream.pix_fmt = "rgb24"
            stream.options = {"crf": "0"}
            red = np.zeros((48, 64, 3), dtype=np.uint8)
            red[..., 0] = 255                       # pure red: green plane is 0, true luma is ~76
            for _ in range(5):
                for packet in stream.encode(av.VideoFrame.from_ndarray(red, format="rgb24")):
                    container.mux(packet)
            for packet in stream.encode():
                container.mux(packet)
    except Exception as exc:                        # encoder not available in this PyAV build
        pytest.skip(f"libx264rgb unavailable: {exc}")

    with av.open(str(path)) as container:
        frame = next(container.decode(container.streams.video[0]))
        assert not has_native_luma(frame)
        assert abs(float(luma(frame).mean()) - 76) < 6


def test_native_luma_is_used_for_yuv420p(video):
    from syncviz_video.frames import has_native_luma

    with av.open(str(video)) as container:
        frame = next(container.decode(container.streams.video[0]))
    assert frame.format.name == "yuv420p" and has_native_luma(frame)


# --- PlaybackReader ----------------------------------------------------------------------

def _count_seeks(reader):
    calls = []
    original = reader._reader.iter_frames

    def counting(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    reader._reader.iter_frames = counting
    return calls


def test_playback_reader_returns_the_right_frame_for_any_access_pattern(video):
    from syncviz_video.frame_reader import PlaybackReader

    index = FrameIndex.build(video)
    reader = PlaybackReader(video, index)
    try:
        for n in [0, 1, 2, 5, 5, 8, 9, 30, 29, 3, 100, 101, 104, 60, 119, 118, 0]:
            assert_is_frame(reader.frame(n), n)
    finally:
        reader.close()


def test_short_forward_jumps_continue_instead_of_reseeking(video):
    from syncviz_video.frame_reader import PlaybackReader

    index = FrameIndex.build(video)
    reader = PlaybackReader(video, index, max_cache_bytes=0)     # keep only the latest frame
    try:
        reader.frame(10)                      # first access seeks
        seeks = _count_seeks(reader)
        for n in [11, 14, 17, 20, 23]:        # playback-like: a few frames ahead each time
            assert_is_frame(reader.frame(n), n)
        assert seeks == []
        reader.frame(5)                       # nothing cached, so going backward must seek
        assert len(seeks) == 1
    finally:
        reader.close()


def test_frames_decoded_on_the_way_are_cached_so_stepping_back_is_free(video):
    from syncviz_video.frame_reader import PlaybackReader

    index = FrameIndex.build(video)
    reader = PlaybackReader(video, index)
    try:
        reader.frame(57)                      # lands mid-GOP: decodes from the keyframe up to 57
        seeks = _count_seeks(reader)
        for n in range(57, 49, -1):           # step backward one frame at a time
            assert_is_frame(reader.frame(n), n)
        assert seeks == []
        # Frames skipped over by a forward jump are cached too.
        reader.frame(60)
        assert_is_frame(reader.frame(59), 59)
        assert seeks == []
    finally:
        reader.close()


def test_cache_respects_its_byte_budget_and_stays_correct(video):
    from syncviz_video.frame_reader import PlaybackReader

    index = FrameIndex.build(video)
    frame_bytes = 64 * 48
    reader = PlaybackReader(video, index, max_cache_bytes=frame_bytes * 5)
    try:
        for n in [0, 20, 40, 60, 80, 100, 119, 70, 71, 5]:
            assert_is_frame(reader.frame(n), n)
            assert len(reader.cached_frames) <= 5
        assert 5 in reader.cached_frames      # the frame just asked for is always kept
    finally:
        reader.close()


def test_playback_reader_survives_running_off_the_end(video):
    from syncviz_video.frame_reader import PlaybackReader

    index = FrameIndex.build(video)
    reader = PlaybackReader(video, index)
    try:
        assert_is_frame(reader.frame(N_FRAMES - 1), N_FRAMES - 1)
        assert_is_frame(reader.frame(3), 3)
        with pytest.raises(IndexError):
            reader.frame(N_FRAMES)
    finally:
        reader.close()
