"""The Events panel: the event conditions in force, as chips (design doc 28.10).

A chip is one active condition: a list of events of which any one counts, and yes or no. Click a chip to change it, its x to
remove it. Chips combine with each other and with the segment filters (all must hold). A core panel, not a view: it holds
shared state and there is only one of it.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QRadioButton, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from syncviz.conditions import Condition
from syncviz_app.controls import not_saved

EMPTY_TEXT = "No event conditions. Add one to keep only the segments where something did, or did not, happen."


class ConditionDialog(QDialog):
    """Choose the events, and whether they happened or did not."""

    def __init__(self, context, condition: Condition | None = None, parent=None) -> None:
        super().__init__(parent)
        self.context = context
        self.setWindowTitle("Event condition")
        self.resize(420, 520)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Keep the segments where any of these events:"))
        self.search = not_saved(QLineEdit(), "a dialog's own search box")
        self.search.setPlaceholderText("Search events")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        wanted = set(condition.events) if condition else set()
        for group, events in context.events.groups.items():
            parent_item = QTreeWidgetItem(self.tree, [group])
            parent_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            for name in events:
                item = QTreeWidgetItem(parent_item, [name])
                item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked if name in wanted else Qt.CheckState.Unchecked)
                tip = context.explain(name)
                if tip:
                    item.setToolTip(0, tip)
            parent_item.setExpanded(True)
        layout.addWidget(self.tree, 1)
        row = QHBoxLayout()
        self.yes = not_saved(QRadioButton("happened"), "a dialog's own choice")
        self.no = not_saved(QRadioButton("did not happen"), "a dialog's own choice")
        (self.yes if condition is None or condition.answer else self.no).setChecked(True)
        row.addWidget(self.yes)
        row.addWidget(self.no)
        layout.addLayout(row)
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._edge = condition.edge if condition else "overlap"

    def _filter(self, text: str) -> None:
        text = text.strip().lower()
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            shown = 0
            for c in range(group.childCount()):
                child = group.child(c)
                hide = bool(text) and text not in child.text(0).lower()
                child.setHidden(hide)
                shown += not hide
            group.setHidden(shown == 0)

    def chosen(self) -> list[str]:
        return [self.tree.topLevelItem(g).child(c).text(0)
                for g in range(self.tree.topLevelItemCount()) for c in range(self.tree.topLevelItem(g).childCount())
                if self.tree.topLevelItem(g).child(c).checkState(0) == Qt.CheckState.Checked]

    def condition(self) -> Condition | None:
        events = self.chosen()
        if not events:
            return None
        return Condition(tuple(events), self.yes.isChecked(), self._edge)


class ClipDialog(QDialog):
    """How much of the time around an event to include, and what to cut around when the event lasts."""

    def __init__(self, name: str, clip: dict, parent=None) -> None:
        super().__init__(parent)
        from PySide6.QtWidgets import QComboBox, QFormLayout

        self.setWindowTitle(f"Clip window: {name}")
        form = QFormLayout(self)
        self.before = not_saved(QDoubleSpinBox(), "a dialog's own value")
        self.after = not_saved(QDoubleSpinBox(), "a dialog's own value")
        for box, value in ((self.before, clip["before_ms"]), (self.after, clip["after_ms"])):
            box.setRange(0.0, 600000.0)
            box.setSuffix(" ms")
            box.setValue(float(value))
        self.before.setToolTip("How much to include before it")
        self.after.setToolTip("How much to include after it")
        self.anchor = not_saved(QComboBox(), "a dialog's own choice")
        for label, value in (("The whole event", "span"), ("Its start only", "start"), ("Its end only", "stop")):
            self.anchor.addItem(label, value)
        self.anchor.setCurrentIndex(max(self.anchor.findData(clip["anchor"]), 0))
        self.anchor.setToolTip("For an event that lasts: cut around all of it, or only around where it starts or ends. "
                               "It makes no difference to an event that is a single moment.")
        form.addRow("Before", self.before)
        form.addRow("After", self.after)
        form.addRow("Around", self.anchor)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[float, float, str]:
        return self.before.value(), self.after.value(), self.anchor.currentData()


class EventsPanel(QWidget):
    def __init__(self, context) -> None:
        super().__init__()
        self.context = context
        self.conditions = context.events
        layout = QVBoxLayout(self)
        self.empty = QLabel(EMPTY_TEXT)
        self.empty.setWordWrap(True)
        layout.addWidget(self.empty)
        self.chips = QVBoxLayout()
        layout.addLayout(self.chips)
        self.message = QLabel("")
        self.message.setWordWrap(True)
        self.message.setStyleSheet("color: #c0392b;")
        layout.addWidget(self.message)
        row = QHBoxLayout()
        self.add_button = QPushButton("Add condition…")
        self.add_button.setEnabled(bool(self.conditions.groups))
        if not self.conditions.groups:
            self.add_button.setToolTip("The project names no events to choose from (an `events:` section in the project file)")
        self.clear_button = QPushButton("Clear all")
        row.addWidget(self.add_button)
        row.addWidget(self.clear_button)
        layout.addLayout(row)
        layout.addStretch(1)
        self.add_button.clicked.connect(self.add_clicked)
        self.clear_button.clicked.connect(self.conditions.clear)
        self.conditions.subscribe(self.rebuild)
        self.rebuild()

    def rebuild(self) -> None:
        while self.chips.count():
            widget = self.chips.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)                      # leave the panel now, not when the event loop gets to it
                widget.deleteLater()
        for index, condition in enumerate(self.conditions.items):
            self.chips.addWidget(self._chip(index, condition))
        self.empty.setVisible(not self.conditions.items)
        self.clear_button.setEnabled(bool(self.conditions.items))
        self.message.setText(self.conditions.message)

    def _chip(self, index: int, condition: Condition) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setProperty("chip", True)
        row = QHBoxLayout(frame)
        row.setContentsMargins(6, 2, 2, 2)
        label = QPushButton(condition.label())
        label.setFlat(True)
        label.setStyleSheet("text-align: left;")
        label.setToolTip("Click to change this condition")
        label.clicked.connect(lambda _=False, i=index: self.edit(i))
        remove = QPushButton("×")
        remove.setFixedWidth(26)
        remove.setToolTip("Remove this condition")
        remove.clicked.connect(lambda _=False, i=index: self.conditions.remove(i))
        row.addWidget(label, 1)
        row.addWidget(remove)
        return frame

    def add_clicked(self) -> None:
        dialog = ConditionDialog(self.context, None, self)
        if dialog.exec() == QDialog.DialogCode.Accepted and dialog.condition() is not None:
            self.conditions.add(dialog.condition())

    def edit(self, index: int) -> None:
        dialog = ConditionDialog(self.context, self.conditions.items[index], self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            condition = dialog.condition()
            if condition is None:
                self.conditions.remove(index)
            else:
                self.conditions.replace(index, condition)
