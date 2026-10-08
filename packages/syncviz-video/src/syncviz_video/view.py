"""The video view. Needs the Qt shell (install syncviz-video[qt]); nothing else imports this."""

from __future__ import annotations

import threading
from time import perf_counter, sleep

import numpy as np
from PySide6.QtCore import QObject, QRectF, QTimer, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter
from PySide6.QtWidgets import QSizePolicy, QVBoxLayout, QWidget

from syncviz.core import RegularGrid
from syncviz.sources import MissingDataError
from syncviz_app.views.base import Candidate, View, ViewSetting
from syncviz_app.views.rows import load_row_data
from syncviz_video.overlays import (
    CORNERS, DEFAULT_CORNER, DEFAULT_DECAY_S, OFF, SKELETON_LABELS, SKELETON_STYLES, ContactMarkers, CornerBadges,
    TrackedLines, TrackedSkeletons, palette,
)
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
        self.delay_s = 0.0                 # debugging: make every frame this slow
        self.delay_once_s = 0.0            # debugging: make only the next frame this slow
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
                    delay, self.delay_once_s = self.delay_s + self.delay_once_s, 0.0
                    if delay:
                        sleep(delay)
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
        self.layers: list = []                # drawn over the picture (see overlays.py)
        self.layers_visible = True            # one switch for all of them
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
            for layer in self.layers if self.layers_visible else []:
                layer.paint(p, target, (iw, ih))
            p.setOpacity(1.0)
        if self._placeholder_mix > 0.0 or self._image is None:
            fg = pal.color(pal.ColorRole.WindowText)
            panel = QColor(fg); panel.setAlpha(int(26 * max(self._placeholder_mix, 1.0 if self._image is None else 0.0)))
            p.fillRect(self.rect().adjusted(8, 8, -8, -8), panel)
            text = QColor(fg); text.setAlpha(int(150 * max(self._placeholder_mix, 1.0 if self._image is None else 0.0)))
            p.setPen(text)
            p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, self._message or "No video at this time")
        if self._cue:
            # The one status message for this view: centred over the picture, calm and translucent.
            box = QRectF(0, 0, 170, 34)
            box.moveCenter(self.rect().center())
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 150))
            p.drawRoundedRect(box, 8, 8)
            p.setPen(QColor(255, 255, 255, 230))
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, self._cue)


class VideoView(View):
    type_name = "video"
    display_name = "Video"

    @classmethod
    def candidates(cls, catalog):
        return [Candidate(f"{source}", {"type": cls.type_name, "title": f"{source}", "source": source})
                for source, entries in catalog.items() if any(e.kind == "video" for e in entries)]
    default_refresh_hz = 60.0          # the picture is what you watch, so it gets the full display rate

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
        self.badges: CornerBadges | None = None
        self.lines: TrackedLines | None = None
        self.skeletons: TrackedSkeletons | None = None
        self._skeleton_style_default = "curve"
        self.markers: ContactMarkers | None = None
        self._track_defaults: set[str] = set()
        self._badge_defaults = {"corner": DEFAULT_CORNER, "hidden": set()}
        overlay = spec.get("overlay")
        if overlay:
            self._build_tracking(context, overlay)           # under the badges
            if overlay.get("rows"):
                self._build_badges(context, overlay)
        self._wanted = -1
        self._shown = -1
        self._progress_at = perf_counter()     # when a frame last arrived, or the wait began
        self._cue_timer = QTimer(self)
        self._cue_timer.setSingleShot(True)
        self._cue_timer.timeout.connect(lambda: self.widget.set_cue(self._cue_text()))
        context.timeline.subscribe(self._on_timeline)

    def _build_tracking(self, context, overlay: dict) -> None:
        """Lines that follow tracked points and rings at contacts, from the overlay's `lines:` and `markers:`. As with the
        badges, one this recording has no data for is left out with a note."""
        colour_index = 0
        lines, markers, skeletons = [], [], []
        for spec in overlay.get("skeletons", []):
            try:
                tracks = context.resources.points(spec["from"])
            except MissingDataError as exc:
                context.notes.append(f"video skeleton {spec.get('name', '')!r} left out: {exc}")
                continue
            scale = 1.0 / float(spec["units_per_pixel"]) if "units_per_pixel" in spec else 1.0
            skeletons.append({"name": spec.get("name", ""), "group": spec.get("group"),
                              "description": context.explain(spec.get("name", ""), spec.get("description") or tracks.metadata.get("description", "")), "tracks": tracks, "scale": scale,
                              "order": tracks.chain(), "color": QColor(spec["color"]) if "color" in spec else palette(colour_index)})
            colour_index += 1
        for spec in overlay.get("lines", []):
            try:
                members = {"base_x": spec["base"][0], "base_y": spec["base"][1], "tip_x": spec["tip"][0], "tip_y": spec["tip"][1]}
                series = {key: context.resources.timeseries(spec["from"], member) for key, member in members.items()}
            except MissingDataError as exc:
                context.notes.append(f"video line {spec.get('name', '')!r} left out: {exc}")
                continue
            first = series["tip_x"]
            times = first.times
            stored = first.metadata.get("conversion", 1.0)
            # Pixels per stored unit: the project can say how many units make a pixel; otherwise undo the file's conversion.
            scale = 1.0 / float(spec["units_per_pixel"]) if "units_per_pixel" in spec else 1.0 / stored
            lines.append({"name": spec.get("name", ""), "group": spec.get("group"), "description": context.explain(spec.get("name", ""), spec.get("description", "")), "times": times, "scale": scale, "color": QColor(spec["color"]) if "color" in spec else palette(colour_index),
                          "max_gap": 1.5 * float(np.median(np.diff(times))) if len(times) > 2 else 0.01,
                          **{key: np.asarray(s.values, float) for key, s in series.items()}})
            colour_index += 1
        for spec in overlay.get("markers", []):
            try:
                table = context.resources.intervals(spec["from"])
                x, y = table.attributes[spec["x"]], table.attributes[spec["y"]]
            except (MissingDataError, KeyError) as exc:
                context.notes.append(f"video marker {spec.get('name', '')!r} left out: {exc}")
                continue
            scale = 1.0 / float(spec["units_per_pixel"]) if "units_per_pixel" in spec else 1.0
            colour = QColor(spec["color"]) if "color" in spec else palette(colour_index)
            for line in (*skeletons, *lines):        # `color_of: Whisker C0` draws the ring in that whisker's colour
                if line["name"] == spec.get("color_of"):
                    colour = line["color"]
            markers.append({"name": spec.get("name", ""), "group": spec.get("group"), "description": context.explain(spec.get("name", ""), spec.get("description", "")), "starts": table.starts, "stops": table.stops, "x": np.asarray(x, float),
                            "y": np.asarray(y, float), "scale": scale, "color": colour})
            colour_index += 1
        self._track_defaults = set(overlay.get("hidden", []))
        self._skeleton_style_default = overlay.get("skeleton_style", "curve")
        if skeletons:
            self.skeletons = TrackedSkeletons(skeletons, self._skeleton_style_default, self._track_defaults)
            self.widget.layers.append(self.skeletons)
        if lines:
            self.lines = TrackedLines(lines, self._track_defaults)
            self.widget.layers.append(self.lines)
        if markers:
            self.markers = ContactMarkers(markers, float(overlay.get("decay", DEFAULT_DECAY_S)), self._track_defaults)
            self.widget.layers.append(self.markers)

    def _build_badges(self, context, overlay: dict) -> None:
        """Event badges over the picture, from the project's `overlay:` section. A row whose data this recording does
        not have is left out, not an error: the picture is still worth showing."""
        rows = []
        for row in overlay.get("rows", []):
            try:
                data = load_row_data(context, row)
            except MissingDataError as exc:
                context.notes.append(f"video overlay row {row.get('name', '')!r} left out: {exc}")
                continue
            rows.append({"name": row.get("name", ""), "kind": row["kind"], "data": data, "group": row.get("group"),
                         "description": context.explain(row.get("name", ""), row.get("description", ""))})
        self._badge_defaults = {"corner": overlay.get("corner", DEFAULT_CORNER), "hidden": set(overlay.get("hidden", []))}
        self.badges = CornerBadges(rows, self._badge_defaults["corner"], float(overlay.get("decay", DEFAULT_DECAY_S)),
                                   self._badge_defaults["hidden"])
        self.widget.layers.append(self.badges)

    def _update_layers(self) -> None:
        """Bring the overlays to the time of the frame on screen (not the playhead, which may be ahead of it)."""
        if self._shown >= 0:
            time = self._shown / self.fps
            for layer in (self.badges, self.skeletons, self.lines, self.markers):
                if layer is not None:
                    layer.set_time(time)
            self.widget.update()

    # -- settings, shown under the Views list --------------------------------------------------
    def settings(self) -> list[ViewSetting]:
        if not self.widget.layers:
            return []
        out = [ViewSetting("overlay.enabled", "Show overlays", "toggle", self.widget.layers_visible)]
        if self.badges is not None and self.badges.rows:
            labels = {OFF: "Off", **{c: c.replace("-", " ").capitalize() for c in CORNERS}}
            out.append(ViewSetting("overlay.corner", "Event badges", "choice", self.badges.corner,
                                   [(labels[c], c) for c in (OFF, *CORNERS)]))
            out += [ViewSetting(f"overlay.show.{row['name']}", row["name"], "toggle", row["name"] not in self.badges.hidden,
                                description=row.get("description", ""), group=row.get("group")) for row in self.badges.rows]
        if self.skeletons is not None:
            out.append(ViewSetting("overlay.skeleton_style", "Tracked points", "choice", self.skeletons.style,
                                   [(SKELETON_LABELS[s], s) for s in SKELETON_STYLES]))
        for layer in (self.skeletons, self.lines, self.markers):    # what is drawn in the picture itself
            if layer is not None:
                out += [ViewSetting(f"overlay.track.{item['name']}", f"Draw {item['name']}", "toggle", item["name"] not in layer.hidden,
                                    description=item.get("description", ""), group=item.get("group")) for item in layer.items]
        return out

    def apply_setting(self, key: str, value) -> None:
        if key == "overlay.enabled":
            self.widget.layers_visible = bool(value)
            self.widget.update()
        elif key == "overlay.corner" and self.badges is not None:
            self.badges.set_corner(value)
        elif key.startswith("overlay.show.") and self.badges is not None:
            name = key[len("overlay.show."):]
            hidden = set(self.badges.hidden)
            (hidden.discard if value else hidden.add)(name)
            self.badges.set_hidden(hidden)
        elif key == "overlay.skeleton_style" and self.skeletons is not None:
            self.skeletons.set_style(value)
        elif key.startswith("overlay.track."):
            name = key[len("overlay.track."):]
            for layer in (self.skeletons, self.lines, self.markers):
                if layer is not None and name in layer.names:
                    hidden = set(layer.hidden)
                    (hidden.discard if value else hidden.add)(name)
                    layer.set_hidden(hidden)
        self._update_layers()

    def reset_settings(self) -> None:
        self.widget.layers_visible = True
        if self.badges is not None:
            self.badges.set_corner(self._badge_defaults["corner"])
            self.badges.set_hidden(self._badge_defaults["hidden"])
        for layer in (self.skeletons, self.lines, self.markers):
            if layer is not None:
                layer.set_hidden(self._track_defaults)
        if self.skeletons is not None:
            self.skeletons.set_style(self._skeleton_style_default)
        self._update_layers()

    def _cue_text(self) -> str:
        return "Buffering…" if self.context.timeline.holding else "Loading…"

    def _on_timeline(self, _tl) -> None:
        if self.widget._cue:                                 # a wait is showing: keep its wording current
            self.widget.set_cue(self._cue_text())

    def extent(self):
        return 0.0, self.n_frames / self.fps

    def time_base(self):
        return RegularGrid(rate=self.fps, count=self.n_frames)        # one tick per video frame

    def refresh(self, time: float) -> None:
        n = int(round(time * self.fps))
        if not 0 <= n < self.n_frames:
            self._wanted = -1
            self._cue_timer.stop()
            self.widget.show_no_data("No video at this time")
            return
        if n == self._wanted:
            return
        if self._wanted == self._shown:                      # was up to date: the wait starts now
            self._progress_at = perf_counter()
        self._wanted = n
        self.decoder.request(n)
        self._cue_timer.start(LOADING_CUE_DELAY_MS)

    def _on_frame(self, n: int, image: np.ndarray) -> None:
        if self._wanted == -1:
            return                                           # playhead has left the video; show the placeholder
        # Show every frame that finishes, even if the playhead has moved on a little since it
        # was requested. Discarding "stale" frames would show nothing at all whenever decoding
        # takes longer than the interval between requests, i.e. during any fast scrub.
        self._progress_at = perf_counter()
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
        self._update_layers()

    # -- debugging hooks (used by the Debug menu) ---------------------------------------
    @property
    def simulated_delay_s(self) -> float:
        return self.decoder.delay_s

    @simulated_delay_s.setter
    def simulated_delay_s(self, seconds: float) -> None:
        self.decoder.delay_s = float(seconds)

    def stall_once(self, seconds: float) -> None:
        self.decoder.delay_once_s = float(seconds)

    def stalled_for(self, now: float) -> float:
        if self._wanted == -1 or self._wanted == self._shown:
            return 0.0
        return max(0.0, now - self._progress_at)

    def close_view(self) -> None:
        self.context.timeline.unsubscribe(self._on_timeline)
        self.decoder.stop()
