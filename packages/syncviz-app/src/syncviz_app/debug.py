"""The Debug menu: ways to provoke slow or failing conditions and watch how the app reacts.

Views opt in by having the attributes used here (`simulated_delay_s`, `stall_once`), so the
window itself knows nothing about video.
"""

from __future__ import annotations

import time

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QLabel

DELAYS_S = [0.0, 0.05, 0.2, 0.6, 1.5]
STALL_ONCE_S = 3.0


class DebugTools:
    def __init__(self, window) -> None:
        self.window = window
        self.slowable = [v for v in window.views if hasattr(v, "simulated_delay_s")]
        menu = window.menuBar().addMenu("&Debug")

        if self.slowable:
            slow = menu.addMenu("Simulate slow decoding")
            group = QActionGroup(window)
            for seconds in DELAYS_S:
                action = QAction("Off" if seconds == 0 else f"{seconds * 1000:g} ms per frame", window)
                action.setCheckable(True)
                action.setChecked(seconds == 0)
                action.triggered.connect(lambda _c=False, s=seconds: self.set_delay(s))
                group.addAction(action)
                slow.addAction(action)
            self.stall_action = QAction(f"Stall the next frame for {STALL_ONCE_S:g} s", window)
            self.stall_action.triggered.connect(self.stall_once)
            menu.addAction(self.stall_action)
            menu.addSeparator()

        self.readout_action = QAction("Show live status", window)
        self.readout_action.setCheckable(True)
        self.readout_action.toggled.connect(self._toggle_readout)
        menu.addAction(self.readout_action)

        self.readout = QLabel()
        self.readout.setStyleSheet("padding: 0 8px; font-family: Consolas, monospace;")
        self.readout.hide()
        window.statusBar().addPermanentWidget(self.readout)
        self._timer = QTimer(window)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self.update_readout)

    def set_delay(self, seconds: float) -> None:
        for view in self.slowable:
            view.simulated_delay_s = seconds

    def stall_once(self) -> None:
        for view in self.slowable:
            view.stall_once(STALL_ONCE_S)

    def _toggle_readout(self, on: bool) -> None:
        self.readout.setVisible(on)
        if on:
            self._timer.start()
            self.update_readout()
        else:
            self._timer.stop()

    def text(self) -> str:
        tl = self.window.context.timeline
        now = time.perf_counter()
        state = "holding" if tl.holding else "playing" if tl.playing else "paused"
        parts = [state, f"governor ×{self.window.scheduler.governor.scale:.2f}"]
        for view in self.window.views:
            parts.append(f"{view.title}: waited {view.stalled_for(now):.2f} s")
        return "   |   ".join(parts)

    def update_readout(self) -> None:
        self.readout.setText(self.text())
