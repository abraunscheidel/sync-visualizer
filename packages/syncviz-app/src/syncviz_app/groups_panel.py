"""The Groups panel and the dialog that makes a group from a rule (design doc 28.16).

A core panel: the groups are shared state. It lists them with how many items each has in the open recording and how it is defined,
and lets the viewer make one from a rule, select a group's items, or remove one they made. A group made from a selection comes from
the "Save as group…" command instead.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from syncviz.groups import Group, attribute_values, members_of
from syncviz_app.controls import not_saved

EMPTY_TEXT = "No groups. Select several items and choose Save as group, or make one from a rule."


def containers(context) -> list[tuple[str, str]]:
    """(label, ref) of the event containers the project's sources offer that have several members, such as the units."""
    out = []
    for source in context.resources.sources:
        try:
            entries = context.resources.catalog(source)
        except Exception:
            continue
        out += [(f"{source}: {e.path}", f"{source}:{e.path}") for e in entries if e.kind == "events" and len(e.members) > 1]
    return out


class _RuleRow(QWidget):
    """One line of a rule: an attribute of the items, and what its value has to be."""

    def __init__(self, values: dict[str, list], changed) -> None:
        super().__init__()
        self.values = values
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        self.attribute = not_saved(QComboBox(), "a dialog's own choice")
        self.attribute.addItems(list(values))
        self.operator = not_saved(QComboBox(), "a dialog's own choice")
        self.operator.addItem("is", "is")
        self.operator.addItem("from … to", "range")
        self.value = not_saved(QComboBox(), "a dialog's own choice")
        self.low = not_saved(QDoubleSpinBox(), "a dialog's own value")
        self.high = not_saved(QDoubleSpinBox(), "a dialog's own value")
        for box in (self.low, self.high):
            box.setRange(-1e12, 1e12)
            box.setDecimals(3)
        row.addWidget(self.attribute)
        row.addWidget(self.operator)
        row.addWidget(self.value, 1)
        row.addWidget(self.low)
        row.addWidget(self.high)
        self.attribute.currentIndexChanged.connect(self._attribute_changed)
        self.operator.currentIndexChanged.connect(self._shown)
        for signal in (self.attribute.currentIndexChanged, self.operator.currentIndexChanged, self.value.currentIndexChanged,
                       self.low.valueChanged, self.high.valueChanged):
            signal.connect(lambda *_: changed())
        self._attribute_changed()

    def _numbers(self) -> list[float]:
        found = self.values.get(self.attribute.currentText(), [])
        return [float(v) for v in found if isinstance(v, (int, float)) and not isinstance(v, bool)]

    def _attribute_changed(self) -> None:
        found = self.values.get(self.attribute.currentText(), [])
        self.value.blockSignals(True)
        self.value.clear()
        for v in found:
            self.value.addItem(str(v), v)
        self.value.blockSignals(False)
        numbers = self._numbers()
        if numbers and len(numbers) == len(found):                    # a measurement: a range is the natural rule
            self.operator.setCurrentIndex(self.operator.findData("range"))
            self.low.setValue(min(numbers))
            self.high.setValue(max(numbers))
        else:
            self.operator.setCurrentIndex(self.operator.findData("is"))
        self._shown()

    def _shown(self) -> None:
        range_rule = self.operator.currentData() == "range"
        self.value.setVisible(not range_rule)
        self.low.setVisible(range_rule)
        self.high.setVisible(range_rule)

    def rule(self) -> tuple[str, object] | None:
        name = self.attribute.currentText()
        if not name:
            return None
        if self.operator.currentData() == "range":
            return name, {"min": self.low.value(), "max": self.high.value()}
        return (name, self.value.currentData()) if self.value.count() else None


class GroupDialog(QDialog):
    """Make a group from a rule over the items of a container, with a live count of the items that match in the open recording."""

    def __init__(self, context, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("New group")
        self.resize(560, 360)
        self._choices = containers(context)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = not_saved(QLineEdit(), "a dialog's own text")
        self.name.setPlaceholderText("For example: Layer 4")
        self.container = not_saved(QComboBox(), "a dialog's own choice")
        for label, ref in self._choices:
            self.container.addItem(label, ref)
        form.addRow("Name", self.name)
        form.addRow("Items from", self.container)
        layout.addLayout(form)
        layout.addWidget(QLabel("Keep the items for which all of these hold:"))
        self.rules = QVBoxLayout()
        layout.addLayout(self.rules)
        add = QPushButton("Add a rule")
        add.clicked.connect(self.add_rule)
        layout.addWidget(add, 0, Qt.AlignmentFlag.AlignLeft)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        layout.addWidget(self.preview, 1)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self.container.currentIndexChanged.connect(self._container_changed)
        self.name.textChanged.connect(self._changed)
        self._attributes: dict[str, dict] = {}
        self._container_changed()

    def _container_changed(self) -> None:
        while self.rules.count():
            widget = self.rules.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        ref = self.container.currentData()
        try:
            self._attributes = self.context.groups.attributes_in(self.context.resources, ref) if ref else {}
        except Exception:
            self._attributes = {}
        if self._attributes:
            self.add_rule()
        self._changed()

    def add_rule(self) -> None:
        values = attribute_values(self._attributes)
        if values:
            self.rules.addWidget(_RuleRow(values, self._changed))
            self._changed()

    def where(self) -> dict:
        found = {}
        for i in range(self.rules.count()):
            rule = self.rules.itemAt(i).widget().rule()
            if rule is not None:
                found[rule[0]] = rule[1]
        return found

    def group(self) -> Group | None:
        where = self.where()
        if not self.name.text().strip() or not where or not self.container.currentData():
            return None
        return Group(self.name.text().strip(), self.container.currentData(), where)

    def _changed(self) -> None:
        group = self.group()
        where = self.where()
        if not self._attributes:
            self.preview.setText("This recording has no container of items with attributes to make a rule from.")
        elif not where:
            self.preview.setText("Add a rule.")
        else:
            matching = members_of(Group("preview", "x", where), self._attributes)
            self.preview.setText(f"{len(matching)} of {len(self._attributes)} items in the open recording match"
                                 + (": " + ", ".join(matching[:12]) + (" …" if len(matching) > 12 else "") if matching else ""))
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(group is not None)


class GroupsPanel(QWidget):
    def __init__(self, context) -> None:
        super().__init__()
        self.context = context
        self.groups = context.groups
        layout = QVBoxLayout(self)
        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(["Group", "Items here", "Defined by"])
        self.tree.setRootIsDecorated(False)
        self.empty = QLabel(EMPTY_TEXT)
        self.empty.setWordWrap(True)
        row = QHBoxLayout()
        self.new_button = QPushButton("New group…")
        self.select_button = QPushButton("Select items")
        self.delete_button = QPushButton("Delete")
        for button in (self.new_button, self.select_button, self.delete_button):
            row.addWidget(button)
        layout.addWidget(self.empty)
        layout.addWidget(self.tree, 1)
        layout.addLayout(row)
        self.new_button.clicked.connect(self.new_group)
        self.select_button.clicked.connect(self.select_items)
        self.delete_button.clicked.connect(self.delete)
        self.tree.currentItemChanged.connect(lambda *_: self._update_buttons())
        self.tree.itemDoubleClicked.connect(lambda *_: self.select_items())
        self.groups.subscribe(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        current = self._name()
        self.tree.clear()
        for group in self.groups.all():
            members = self.groups.members(self.context.resources, group.name)
            item = QTreeWidgetItem(self.tree, [group.name, str(len(members)), self.groups.describe(group.name)])
            item.setData(0, Qt.ItemDataRole.UserRole, group.name)
            item.setToolTip(0, group.description or ("From the project file" if not self.groups.is_saved(group.name) else "Saved by you"))
            if group.name == current:
                self.tree.setCurrentItem(item)
        for column in range(2):
            self.tree.resizeColumnToContents(column)
        self.empty.setVisible(not self.groups.all())
        self._update_buttons()

    def _name(self) -> str | None:
        item = self.tree.currentItem()
        return None if item is None else item.data(0, Qt.ItemDataRole.UserRole)

    def _update_buttons(self) -> None:
        name = self._name()
        self.select_button.setEnabled(name is not None)
        self.delete_button.setEnabled(name is not None and self.groups.is_saved(name))
        self.delete_button.setToolTip("" if name is None or self.groups.is_saved(name) else "This group is in the project file")
        self.new_button.setEnabled(bool(containers(self.context)))

    def new_group(self) -> None:
        dialog = GroupDialog(self.context, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.group() is not None:
            try:
                self.groups.add(dialog.group())
            except ValueError as exc:
                QMessageBox.warning(self, "New group", str(exc))

    def select_items(self) -> None:
        name = self._name()
        if name is not None:
            targets = self.groups.member_targets(self.context.resources, name)
            if targets:
                self.context.selection.set_all(targets)

    def delete(self) -> None:
        name = self._name()
        if name is not None and self.groups.is_saved(name):
            self.groups.remove(name)
