"""The sidebar's list of views: switch each on or off, add new ones, remove ones not wanted.

Switching a view off only hides its panel; it stays loaded, keeps its place in the timeline's
data coverage and comes back exactly as it was. Removing it discards it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)


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
        self.save_button = QPushButton("Save workspace")
        self.save_button.setToolTip("Save the views and panel positions now (Ctrl+S); this also happens when the window closes")
        layout.addWidget(self.save_button)
        self.save_button.clicked.connect(window.save_workspace_clicked)
        self.add_button.clicked.connect(window.choose_view_to_add)
        self.remove_button.clicked.connect(self._remove_selected)
        self.list.itemChanged.connect(self._item_toggled)
        self.list.itemDoubleClicked.connect(self._bring_to_front)
        self.list.currentItemChanged.connect(lambda *_: self._update_buttons())
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
