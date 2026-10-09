"""The details panel: everything known about the selected item (design doc section 28.7).

A docked core panel. For one selected item it shows the description and every field the inspector gives, grouped, and lets the
user tick which figures also show when hovering. For several it shows a table with a row for each item and its brief figures, so they
can be compared; clicking a row shows that item's full details underneath. Which row is shown is the user's choice in the panel, not
the order the items were selected in. The panel only presents; what is known comes from the inspector.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QHeaderView, QLabel, QPushButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from syncviz.inspection import Target
from syncviz_app.context import AppContext
from syncviz_app.controls import saved_in_workspace

EMPTY_TEXT = "Click something in a view to see its details here."
MAX_ROWS = 60                  # a table of more items than this shows names only, so selecting a lot stays quick


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
        self.table = QTreeWidget()                       # one row for each selected item, when there are several
        self.table.setRootIsDecorated(False)
        self.table.setVisible(False)
        self.table.currentItemChanged.connect(lambda item, _previous: self._row_chosen(item))
        self.shown: Target | None = None                  # the item whose full details are in the tree
        self.clear_button = QPushButton("Clear selection")
        self.clear_button.clicked.connect(context.selection.clear)
        layout = QVBoxLayout(self)
        for widget in (self.title, self.scope, self.description, self.table, self.tree, self.clear_button):
            layout.addWidget(widget)
        layout.setStretchFactor(self.tree, 1)
        context.selection.subscribe(lambda _targets: self.show_selection())
        if context.navigator is not None:
            context.navigator.subscribe(lambda _nav: self.show_selection())      # statistics follow the current segment
        self.show_selection()

    def show_selection(self) -> None:
        targets = self.context.selection.targets
        self.clear_button.setEnabled(bool(targets))
        self.tree.clear()
        self.table.clear()
        self.shown = None
        self.table.setVisible(len(targets) > 1)
        if not targets or self.context.inspector is None:
            self.title.setText(EMPTY_TEXT)
            self.scope.setText("")
            self.description.setText("")
            return
        if len(targets) == 1:
            self._show_item(targets[0])
            return
        self._show_table(targets)

    def _show_table(self, targets: list[Target]) -> None:
        inspector = self.context.inspector
        self.title.setText(f"{len(targets)} items selected")
        self.description.setText("Click one to see all its details." if len(targets) <= MAX_ROWS else
                                 f"Too many to compare ({len(targets)}): select {MAX_ROWS} or fewer to see their figures.")
        rows, columns = [], {}
        for target in targets[:MAX_ROWS]:
            details = inspector.details(target)
            brief = {f.key: f for f in details.brief()}
            for key, field in brief.items():
                columns.setdefault(key, field.name)
            rows.append((target, details, brief))
        self.scope.setText(f"Statistics over: {rows[0][1].scope.label}" if rows else "")
        self.table.setColumnCount(1 + len(columns))
        self.table.setHeaderLabels(["Item", *columns.values()])
        for target, details, brief in rows:
            item = QTreeWidgetItem(self.table, [details.title, *[brief[k].value if k in brief else "" for k in columns]])
            item.setData(0, Qt.ItemDataRole.UserRole, target)
        for column in range(self.table.columnCount()):
            self.table.resizeColumnToContents(column)

    def _row_chosen(self, item) -> None:
        target = None if item is None else item.data(0, Qt.ItemDataRole.UserRole)
        if target is not None:
            self._show_item(target, keep_summary=True)

    def _show_item(self, target: Target, keep_summary: bool = False) -> None:
        """The full details of one item in the tree below (and, for a single selection, the heading too)."""
        inspector = self.context.inspector
        details = inspector.details(target)
        self.shown = target
        self.tree.clear()
        if not keep_summary:
            self.title.setText(details.title)
            self.description.setText(details.description)
        else:
            self.description.setText(f"{details.title}\n{details.description}".strip())
        self.scope.setText(f"Statistics over: {details.scope.label}")
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
        current = {f.key for f in inspector.details(self.shown).fields if inspector.shown_on_hover(f)} \
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
