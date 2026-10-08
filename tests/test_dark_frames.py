import av
import numpy as np
import pytest

from syncviz import plugins
from syncviz.cache import DiskCache
from syncviz.resources import EventSeries
from syncviz_video import DarkFrameDetector, find_dark_runs
from syncviz_video.scan import scan_brightness


def make_brightness(n=1000, dark_runs=((100, 27), (400, 28), (900, 27)), level=130.0, seed=0):
    rng = np.random.default_rng(seed)
    b = level + rng.normal(0, 3, n)
    for start, length in dark_runs:
        b[start : start + length] = 0.0
    return b


def test_finds_known_runs():
    runs = find_dark_runs(make_brightness())

    assert runs.start_frames.tolist() == [100, 400, 900]
    assert runs.lengths.tolist() == [27, 28, 27]


def test_no_runs_in_constant_video():
    runs = find_dark_runs(np.full(500, 130.0))

    assert len(runs.start_frames) == 0


def test_run_touching_start_and_end_is_counted():
    b = make_brightness(n=300, dark_runs=((0, 5), (295, 5)))

    runs = find_dark_runs(b)

    assert runs.start_frames.tolist() == [0, 295]
    assert runs.lengths.tolist() == [5, 5]


def test_explicit_threshold_overrides_auto():
    b = make_brightness()
    b[50:60] = 90.0    # dimmer but not black

    assert len(find_dark_runs(b, threshold="auto").start_frames) == 3
    assert len(find_dark_runs(b, threshold=100.0).start_frames) == 4


def test_bad_threshold_rejected():
    with pytest.raises(ValueError):
        find_dark_runs(make_brightness(), threshold="otsu")


def write_video(path, brightness_levels, size=(64, 48), fps=30):
    """Write a tiny video whose frame i has uniform gray level brightness_levels[i]."""
    with av.open(str(path), "w") as container:
        stream = container.add_stream("libx264", rate=fps)
        stream.width, stream.height = size
        stream.pix_fmt = "yuv420p"
        stream.options = {"crf": "10"}
        for level in brightness_levels:
            img = np.full((size[1], size[0]), int(level), dtype=np.uint8)
            frame = av.VideoFrame.from_ndarray(img, format="gray").reformat(format="yuv420p")
            for packet in stream.encode(frame):
                container.mux(packet)
        for packet in stream.encode():
            container.mux(packet)


@pytest.fixture(scope="module")
def synthetic_video(tmp_path_factory):
    path = tmp_path_factory.mktemp("video") / "sync.mp4"
    levels = np.full(200, 130)
    levels[40:55] = 0
    levels[120:135] = 0
    write_video(path, levels)
    return path


def test_scan_counts_every_frame(synthetic_video):
    b = scan_brightness(synthetic_video)

    assert len(b) == 200
    assert b[0] > 100 and b[45] < 20


def test_detector_end_to_end_with_cache(synthetic_video, tmp_path):
    cache = DiskCache(tmp_path / "cache")
    detector = DarkFrameDetector()

    first = detector.detect(synthetic_video, fps=200.0, cache=cache)
    assert isinstance(first, EventSeries)
    np.testing.assert_allclose(first.times, [40 / 200, 120 / 200], atol=1 / 200)
    np.testing.assert_allclose(first.durations, [15 / 200, 15 / 200], atol=2 / 200)

    # Second call must come from the cache: make decoding impossible.
    import syncviz_video.dark_frames as df

    original = df.scan_brightness
    df.scan_brightness = lambda *a, **k: (_ for _ in ()).throw(AssertionError("rescanned"))
    try:
        second = detector.detect(synthetic_video, fps=200.0, cache=cache)
    finally:
        df.scan_brightness = original
    np.testing.assert_array_equal(first.times, second.times)


def test_cache_invalidated_when_file_changes(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"one")
    cache = DiskCache(tmp_path / "cache")
    calls = []

    def compute():
        calls.append(1)
        return np.arange(3)

    cache.get_or_compute(f, "a", compute)
    cache.get_or_compute(f, "a", compute)
    assert len(calls) == 1

    f.write_bytes(b"changed contents")
    cache.get_or_compute(f, "a", compute)
    assert len(calls) == 2


def test_detector_discovered_via_entry_point():
    cls = plugins.load("sync_detectors", "dark_frames")

    assert cls is DarkFrameDetector


def test_event_series_validation():
    with pytest.raises(ValueError):
        EventSeries(times=np.array([2.0, 1.0]))
    with pytest.raises(ValueError):
        EventSeries(times=np.array([1.0, 2.0]), durations=np.array([1.0]))
