"""The loading screen shown while another collection (session) is being opened.

Opening one reads files and builds every view, which can take many seconds. Without a sign of life the window looks
frozen, so a screen covers it, says what is being opened and which step it is on, and animates while the files are read.
"""

from __future__ import annotations

import threading
from typing import Callable, TypeVar

from PySide6.QtCore import QEvent, QEventLoop, QTimer, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QApplication, QLabel, QProgressBar, QVBoxLayout, QWidget

T = TypeVar("T")
POLL_MS = 30


def run_in_background(work: Callable[[], T]) -> T:
    """Run `work` on another thread and return its result (or raise what it raised), keeping the interface alive
    meanwhile so the loading screen's bar keeps moving. Only for work that touches no widgets."""
    outcome: dict = {}

    def target() -> None:
        try:
            outcome["value"] = work()
        except BaseException as exc:                      # handed back to the caller below
            outcome["error"] = exc

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    loop = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(lambda: None if thread.is_alive() else loop.quit())
    timer.start(POLL_MS)
    if thread.is_alive():
        loop.exec(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)
    timer.stop()
    thread.join()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"]


class LoadingScreen(QWidget):
    """A translucent screen over its parent window with a heading, a bar and a line saying what is happening."""

    def __init__(self, parent: QWidget) -> None:
        super().__init__(parent)
        self.heading = QLabel("")
        font = self.heading.font()
        font.setPointSize(font.pointSize() + 5)
        font.setBold(True)
        self.heading.setFont(font)
        self.heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.bar = QProgressBar()
        self.bar.setTextVisible(False)
        self.bar.setFixedWidth(340)
        self.detail = QLabel("")
        self.detail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout = QVBoxLayout(self)
        layout.addStretch(1)
        for widget in (self.heading, self.bar, self.detail):
            layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(1)
        parent.installEventFilter(self)
        self.hide()

    def eventFilter(self, obj, event) -> bool:
        if obj is self.parent() and event.type() == QEvent.Type.Resize:
            self.setGeometry(self.parent().rect())
        return False

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        colour = QColor(self.palette().color(self.backgroundRole()))
        colour.setAlpha(225)
        painter.fillRect(self.rect(), colour)

    # Swallow the mouse so nothing underneath can be clicked while the screen is up.
    def mousePressEvent(self, event) -> None:
        event.accept()

    def keyPressEvent(self, event) -> None:
        event.accept()

    @property
    def showing(self) -> bool:
        return self.isVisible() or self._wanted

    _wanted = False

    def begin(self, heading: str, detail: str = "") -> None:
        self._wanted = True
        self.heading.setText(heading)
        self.detail.setText(detail)
        self.bar.setRange(0, 0)                                   # busy until the steps can be counted
        self.setGeometry(self.parent().rect())
        self.raise_()
        self.show()
        self.setFocus()
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def progress(self, detail: str, done: int | None = None, total: int | None = None) -> None:
        """Say what is happening now; with `done` and `total`, the bar shows how far along it is."""
        self.detail.setText(detail)
        if done is not None and total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def end(self) -> None:
        self._wanted = False
        self.hide()
