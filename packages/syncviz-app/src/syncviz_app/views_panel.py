"""The sidebar's list of views: switch each on or off, add new ones, remove ones not wanted.

Switching a view off only hides its panel; it stays loaded, keeps its place in the timeline's
data coverage and comes back exactly as it was. Removing it discards it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from syncviz_app.controls import saved_in_workspace
from syncviz_app.views.base import describe_delay


def _swatch(colour: str) -> QIcon:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(colour))
    return QIcon(pixmap)


class ViewsPanel(QWidget):
    def __init__(self, window) -> None:
        super().__init__()
        self.window = window
        self._connected: set[int] = set()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        heading = QLabel("Views")
        heading.setStyleSheet("font-weight: 600;")
        layout.addWidget(heading)
        self.list = QListWidget()
        self.list.setToolTip("Tick a view to show it, untick to hide it. Double-click to bring it to the front.")
        layout.addWidget(self.list, 1)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add view…")
        self.remove_button = QPushButton("Remove")
        self.remove_button.setToolTip("Discard the selected view (to just hide it, untick it)")
        row.addWidget(self.add_button)
        row.addWidget(self.remove_button)
        layout.addLayout(row)
        shift_row = QHBoxLayout()
        shift_row.addWidget(QLabel("Delay"))
        self.lag_spin = saved_in_workspace(QDoubleSpinBox())
        self.lag_spin.setRange(-10000.0, 10000.0)
        self.lag_spin.setDecimals(1)
        self.lag_spin.setSingleStep(1.0)
        self.lag_spin.setSuffix(" ms")
        self.lag_spin.setToolTip(
            "Only changes what the selected view draws, to line things up by eye; the data is untouched.\n"
            "Positive: the view is delayed, so it runs behind the playhead (shows what happened that long ago).\n"
            "Negative: it runs ahead of the playhead (shows what is about to happen)."
        )
        self.lag_reset = QPushButton("Reset")
        self.lag_reset.setToolTip("Remove the delay from the selected view")
        shift_row.addWidget(self.lag_spin, 1)
        shift_row.addWidget(self.lag_reset)
        layout.addLayout(shift_row)
        self.lag_words = QLabel()
        self.lag_words.setWordWrap(True)
        self.lag_words.setEnabled(False)                       # a quiet explanation, not a control
        layout.addWidget(self.lag_words)
        self.settings_layout = QVBoxLayout()                    # the selected view's own settings, built when it is selected
        layout.addLayout(self.settings_layout)
        self.lag_spin.valueChanged.connect(self._lag_edited)
        self.lag_spin.editingFinished.connect(self.lag_spin.clearFocus)       # keep the keyboard shortcuts working
        self.lag_reset.clicked.connect(lambda: self.lag_spin.setValue(0.0))
        self.save_button = QPushButton("Save workspace")
        self.save_button.setToolTip("Save the views and panel positions now (Ctrl+S); this also happens when the window closes")
        layout.addWidget(self.save_button)
        self.save_button.clicked.connect(window.save_workspace_clicked)
        self.add_button.clicked.connect(window.choose_view_to_add)
        self.remove_button.clicked.connect(self._remove_selected)
        self.list.itemChanged.connect(self._item_toggled)
        self.list.itemDoubleClicked.connect(self._bring_to_front)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.list.currentItemChanged.connect(lambda *_: self.show_lag())
        self.rebuild()

    # -- content -------------------------------------------------------------------------
    def rebuild(self) -> None:
        w = self.window
        self.list.blockSignals(True)
        self.list.clear()
        for view, dock in zip(w.views, w.docks):
            item = QListWidgetItem(view.title)
            item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            item.setIcon(_swatch(w.context.colors.get(view.title, "#888888")))
            item.setData(Qt.ItemDataRole.UserRole, view)
            item.setCheckState(Qt.CheckState.Checked if dock.toggleViewAction().isChecked() else Qt.CheckState.Unchecked)
            self.list.addItem(item)
            if id(dock) not in self._connected:           # follow the panel being closed or shown elsewhere
                self._connected.add(id(dock))
                dock.toggleViewAction().toggled.connect(self.sync)
        self.list.blockSignals(False)
        self._update_buttons()
        self.show_lag()

    def sync(self, *_args) -> None:
        """Make the ticks match which panels are showing."""
        w = self.window
        self.list.blockSignals(True)
        for i in range(self.list.count()):
            item = self.list.item(i)
            view = item.data(Qt.ItemDataRole.UserRole)
            if view in w.views:
                dock = w.docks[w.views.index(view)]
                item.setCheckState(Qt.CheckState.Checked if dock.toggleViewAction().isChecked() else Qt.CheckState.Unchecked)
        self.list.blockSignals(False)

    def _update_buttons(self) -> None:
        self.remove_button.setEnabled(self.list.currentItem() is not None)
        has = self.list.currentItem() is not None
        self.lag_spin.setEnabled(has)
        self.lag_reset.setEnabled(has)

    def _selected_view(self):
        item = self.list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def show_lag(self) -> None:
        """Show the selected view's current shift in the field (without changing it)."""
        view = self._selected_view()
        self.lag_spin.blockSignals(True)
        self.lag_spin.setValue(0.0 if view is None else view.lag * 1000.0)
        self.lag_spin.blockSignals(False)
        self._describe()
        self.show_settings()

    def show_settings(self) -> None:
        """Build the controls for the selected view's own settings (none for most views)."""
        while self.settings_layout.count():
            widget = self.settings_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)                            # leave the panel now, not when the event loop gets to it
                widget.deleteLater()
        view = self._selected_view()
        settings = view.settings() if view is not None else []
        if not settings:
            return
        heading = QLabel("Settings")
        heading.setStyleSheet("font-weight: 600;")
        self.settings_layout.addWidget(heading)
        for setting in settings:
            if setting.kind == "choice":
                row = QHBoxLayout()
                box = saved_in_workspace(QComboBox())
                for label, value in setting.choices:
                    box.addItem(label, value)
                box.setCurrentIndex(max(box.findData(setting.value), 0))
                box.currentIndexChanged.connect(lambda _i, b=box, k=setting.key: self.window.set_view_setting(self._selected_view(), k, b.currentData()))
                row.addWidget(QLabel(setting.label))
                row.addWidget(box, 1)
                holder = QWidget()
                holder.setLayout(row)
                row.setContentsMargins(0, 0, 0, 0)
                self.settings_layout.addWidget(holder)
            else:
                check = saved_in_workspace(QCheckBox(setting.label))
                check.setChecked(bool(setting.value))
                check.toggled.connect(lambda on, k=setting.key: self.window.set_view_setting(self._selected_view(), k, on))
                self.settings_layout.addWidget(check)

    def _describe(self) -> None:
        self.lag_words.setText("" if self._selected_view() is None else describe_delay(self.lag_spin.value(), sentence=True))

    def _lag_edited(self, milliseconds: float) -> None:
        view = self._selected_view()
        if view is not None:
            self.window.set_view_lag(view, milliseconds)
        self._describe()

    # -- actions -------------------------------------------------------------------------
    def _dock_of(self, item):
        view = item.data(Qt.ItemDataRole.UserRole)
        return self.window.docks[self.window.views.index(view)]

    def _item_toggled(self, item) -> None:
        action = self._dock_of(item).toggleViewAction()
        if action.isChecked() != (item.checkState() == Qt.CheckState.Checked):
            action.trigger()

    def _bring_to_front(self, item) -> None:
        dock = self._dock_of(item)
        dock.show()
        dock.raise_()

    def _remove_selected(self) -> None:
        item = self.list.currentItem()
        if item is not None:
            self.window.remove_view(item.data(Qt.ItemDataRole.UserRole))
