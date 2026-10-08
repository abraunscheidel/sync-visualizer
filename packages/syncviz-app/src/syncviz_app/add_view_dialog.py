"""The "Add view" dialog: pick one of the views the available data could feed."""

from __future__ import annotations

from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QFormLayout, QLabel, QLineEdit, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from syncviz import plugins
from syncviz.sources import DataEntry


def collect_candidates(catalog: dict[str, list[DataEntry]]) -> dict[str, list]:
    """Candidates grouped under the display name of each kind of view that can offer some."""
    groups: dict[str, list] = {}
    for type_name in sorted(plugins.available("views")):
        try:
            view_class = plugins.load("views", type_name)
        except Exception:
            continue
        found = view_class.candidates(catalog)
        if found:
            groups[view_class.display_name or type_name] = found
    return groups


class AddViewDialog(QDialog):
    def __init__(self, catalog: dict[str, list[DataEntry]], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add view")
        self.resize(560, 460)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Choose what the new view should show:"))
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        layout.addWidget(self.tree, 1)
        self.groups = collect_candidates(catalog)
        for group, candidates in self.groups.items():
            parent_item = QTreeWidgetItem([group])
            parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            self.tree.addTopLevelItem(parent_item)
            for candidate in candidates:
                child = QTreeWidgetItem([candidate.label])
                child.setData(0, Qt.ItemDataRole.UserRole, candidate)
                if candidate.description:
                    child.setToolTip(0, candidate.description)
                parent_item.addChild(child)
            parent_item.setExpanded(True)
        if not self.groups:
            layout.addWidget(QLabel("No data that can be shown was found in the project's sources."))
        form = QFormLayout()
        self.title = QLineEdit()
        form.addRow("Title", self.title)
        layout.addLayout(form)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setEnabled(False)
        self.tree.currentItemChanged.connect(self._selected)
        self.tree.itemDoubleClicked.connect(lambda *_: self.ok.isEnabled() and self.accept())

    def _candidate(self):
        item = self.tree.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _selected(self, *_args) -> None:
        candidate = self._candidate()
        self.ok.setEnabled(candidate is not None)
        if candidate is not None:
            self.title.setText(candidate.spec.get("title", ""))

    def spec(self) -> dict | None:
        """The chosen view's spec with the title as edited, or None if nothing is chosen."""
        candidate = self._candidate()
        if candidate is None:
            return None
        spec = deepcopy(candidate.spec)
        spec["title"] = self.title.text().strip() or spec.get("title") or spec["type"]
        return spec
