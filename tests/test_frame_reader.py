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


def assert_is_frame(image, i):
    assert abs(float(image.mean()) - level_of(i)) < 4, f"frame {i} has wrong content"


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
