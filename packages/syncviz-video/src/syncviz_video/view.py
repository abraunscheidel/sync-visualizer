"""The video view. Needs the Qt shell (install syncviz-video[qt]); nothing else imports this."""

from __future__ import annotations

import threading

import numpy as np
from PySide6.QtCore import QObject, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from syncviz_app.views.base import View
from syncviz_video.frame_index import FrameIndex
from syncviz_video.frame_reader import DEFAULT_CACHE_BYTES, PlaybackReader

LOADING_CUE_DELAY_MS = 180      # only hint that a frame is on its way if it takes this long
FADE_STEP = 0.18

# Video range (black ~16, white ~235) stretched to full range for display.
_VIDEO_RANGE_LUT = np.clip((np.arange(256) - 16) * 255.0 / 219.0, 0, 255).astype(np.uint8)


class _Decoder(QObject):
    """Decodes on its own thread, always working on the most recently requested frame."""

    frame_ready = Signal(int, object)
    failed = Signal(str)

    def __init__(self, path, index: FrameIndex, cache_bytes: int) -> None:
        super().__init__()
        self._path, self._index, self._cache_bytes = path, index, cache_bytes
        self._cond = threading.Condition()
        self._target: int | None = None
        self._stop = False
        self.native_luma = True
        self._thread = threading.Thread(target=self._run, name="video-decoder", daemon=True)
        self._thread.start()

    def request(self, n: int) -> None:
        with self._cond:
            self._target = n
            self._cond.notify()

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._thread.join(timeout=3)

    def _run(self) -> None:
        reader = PlaybackReader(self._path, self._index, self._cache_bytes)   # created here: not thread-safe
        self.native_luma = reader.native_luma
        try:
            while True:
                with self._cond:
                    while self._target is None and not self._stop:
                        self._cond.wait()
                    if self._stop:
                        return
                    n, self._target = self._target, None
                try:
                    self.frame_ready.emit(n, reader.frame(n))
                except Exception as exc:                       # a bad frame must not kill playback
                    self.failed.emit(f"frame {n}: {exc}")
        finally:
            reader.close()


class _FrameWidget(QWidget):
    """Draws the frame fitted to the panel, or a calm placeholder when there is nothing to show."""

    def __init__(self) -> None:
        super().__init__()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setMinimumSize(160, 120)
        self._image: QImage | None = None
        self._message = ""
        self._cue = ""
        self._placeholder_mix = 0.0           # 0 = frame fully shown, 1 = placeholder fully shown
        self._target_mix = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def show_frame(self, image: QImage) -> None:
        self._image, self._cue, self._target_mix = image, "", 0.0
        self._start_fade()

    def show_no_data(self, message: str) -> None:
        self._message, self._cue, self._target_mix = message, "", 1.0
        self._start_fade()

    def set_cue(self, text: str) -> None:
        if text != self._cue:
            self._cue = text
            self.update()

    def _start_fade(self) -> None:
        if self._placeholder_mix != self._target_mix and not self._timer.isActive():
            self._timer.start(16)
        self.update()

    def _step(self) -> None:
        delta = self._target_mix - self._placeholder_mix
        if abs(delta) <= FADE_STEP:
            self._placeholder_mix = self._target_mix
            self._timer.stop()
        else:
            self._placeholder_mix += FADE_STEP if delta > 0 else -FADE_STEP
        self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        pal = self.palette()
        base = pal.color(pal.ColorRole.Window)
        p.fillRect(self.rect(), base)
        if self._image is not None and self._placeholder_mix < 1.0:
            iw, ih = self._image.width(), self._image.height()
            scale = min(self.width() / iw, self.height() / ih)
            w, h = iw * scale, ih * scale
            target = QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h)
            p.setOpacity(1.0 - self._placeholder_mix)
            p.drawImage(target, self._image)
            p.setOpacity(1.0)
        if self._placeholder_mix > 0.0 or self._image is None:
            fg = pal.color(pal.ColorRole.WindowText)
            panel = QColor(fg); panel.setAlpha(int(26 * max(self._placeholder_mix, 1.0 if self._image is None else 0.0)))
            p.fillRect(self.rect().adjusted(8, 8, -8, -8), panel)
            text = QColor(fg); text.setAlpha(int(150 * max(self._placeholder_mix, 1.0 if self._image is None else 0.0)))
            p.setPen(text)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message or "No video at this time")
        if self._cue:
            p.setPen(QColor(255, 255, 255, 190))
            p.fillRect(QRectF(10, 10, 120, 22), QColor(0, 0, 0, 110))
            p.drawText(QRectF(10, 10, 120, 22), Qt.AlignmentFlag.AlignCenter, self._cue)


class VideoView(View):
    type_name = "video"

    def __init__(self, context, spec: dict) -> None:
        super().__init__(context, spec)
        source = context.resources.source(spec["source"])
        self.fps = float(source.fps)
        self.index = FrameIndex.build(source.path, cache=context.cache)
        self.n_frames = self.index.n_frames
        cache_bytes = int(float(spec.get("cache_mb", DEFAULT_CACHE_BYTES / 2**20)) * 2**20)
        self.decoder = _Decoder(source.path, self.index, cache_bytes)
        self.decoder.frame_ready.connect(self._on_frame)
        self.decoder.failed.connect(lambda msg: context.notes.append(f"video: {msg}"))
        self.widget = _FrameWidget()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.widget)
        self._wanted = -1
        self._shown = -1
        self._cue_timer = QTimer(self)
        self._cue_timer.setSingleShot(True)
        self._cue_timer.timeout.connect(lambda: self.widget.set_cue("Loading…"))

    def extent(self):
        return 0.0, self.n_frames / self.fps

    def refresh(self, time: float) -> None:
        n = int(round(time * self.fps))
        if not 0 <= n < self.n_frames:
            self._wanted = -1
            self._cue_timer.stop()
            self.widget.show_no_data("No video at this time")
            return
        if n == self._wanted:
            return
        self._wanted = n
        self.decoder.request(n)
        self._cue_timer.start(LOADING_CUE_DELAY_MS)

    def _on_frame(self, n: int, image: np.ndarray) -> None:
        if self._wanted == -1:
            return                                           # playhead has left the video; show the placeholder
        # Show every frame that finishes, even if the playhead has moved on a little since it
        # was requested. Discarding "stale" frames would show nothing at all whenever decoding
        # takes longer than the interval between requests, i.e. during any fast scrub.
        self._cue_timer.stop()
        self.widget.set_cue("")
        if n != self._wanted:
            self._cue_timer.start(LOADING_CUE_DELAY_MS)      # still behind; cue only if it stays so
        if self.decoder.native_luma:
            image = _VIDEO_RANGE_LUT[image]
        image = np.ascontiguousarray(image)
        h, w = image.shape
        self.widget.show_frame(QImage(image.data, w, h, w, QImage.Format.Format_Grayscale8).copy())
        self._shown = n

    def close_view(self) -> None:
        self.decoder.stop()
