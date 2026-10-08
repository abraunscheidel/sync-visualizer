"""The details panel: everything known about the selected item (design doc section 28.7).

A docked core panel. It shows the selection's description and every field the inspector gives, grouped, and lets the
user tick which figures also show when hovering. The panel only presents; what is known comes from the inspector.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHeaderView, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from syncviz_app.context import AppContext
from syncviz_app.controls import saved_in_workspace

EMPTY_TEXT = "Click something in a view to see its details here."


class DetailsPanel(QWidget):
    def __init__(self, context: AppContext) -> None:
        super().__init__()
        self.context = context
        self.hover_keys: set[str] | None = None            # None until the user changes a tick: each statistic's own default
        self._building = False
        self.title = QLabel(EMPTY_TEXT)
        self.title.setWordWrap(True)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self.scope = QLabel("")
        self.description = QLabel("")
        self.description.setWordWrap(True)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["", "", "On hover"])
        self.tree.setRootIsDecorated(False)
        header = self.tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        self.clear_button = QPushButton("Clear selection")
        self.clear_button.clicked.connect(context.selection.clear)
        layout = QVBoxLayout(self)
        for widget in (self.title, self.scope, self.description, self.tree, self.clear_button):
            layout.addWidget(widget)
        layout.setStretchFactor(self.tree, 1)
        context.selection.subscribe(lambda _target: self.show_selection())
        if context.navigator is not None:
            context.navigator.subscribe(lambda _nav: self.show_selection())      # statistics follow the current segment
        self.show_selection()

    def show_selection(self) -> None:
        target = self.context.selection.target
        self.tree.clear()
        self.clear_button.setEnabled(target is not None)
        if target is None or self.context.inspector is None:
            self.title.setText(EMPTY_TEXT)
            self.scope.setText("")
            self.description.setText("")
            return
        inspector = self.context.inspector
        details = inspector.details(target)
        self.title.setText(details.title)
        self.scope.setText(f"Statistics over: {details.scope.label}")
        self.description.setText(details.description)
        self._building = True
        groups: dict[str, QTreeWidgetItem] = {}
        for field in details.fields:
            parent = groups.get(field.group)
            if parent is None:
                parent = QTreeWidgetItem(self.tree, [field.group or "Details"])
                parent.setFirstColumnSpanned(True)
                parent.setExpanded(True)
                groups[field.group] = parent
            item = QTreeWidgetItem(parent, [field.name, field.value])
            box = saved_in_workspace(QCheckBox())
            box.setToolTip("Also show this figure when hovering over the item")
            box.setChecked(inspector.shown_on_hover(field))
            box.toggled.connect(lambda on, key=field.key: self._toggled(key, on))
            self.tree.setItemWidget(item, 2, box)
        self.tree.expandAll()
        self._building = False

    def _toggled(self, key: str, on: bool) -> None:
        if self._building:
            return
        inspector = self.context.inspector
        current = {f.key for f in inspector.details(self.context.selection.target).fields if inspector.shown_on_hover(f)} \
            if inspector.hover_keys is None else set(inspector.hover_keys)
        current.add(key) if on else current.discard(key)
        inspector.hover_keys = current

    # -- what a workspace saves ---------------------------------------------------------------------
    def state(self) -> dict:
        keys = self.context.inspector.hover_keys
        return {"hover": None if keys is None else sorted(keys)}

    def apply_state(self, state: dict) -> None:
        hover = state.get("hover")
        self.context.inspector.hover_keys = None if hover is None else {str(k) for k in hover}
        self.show_selection()
