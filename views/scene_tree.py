# SPDX-License-Identifier: GPL-3.0-or-later
"""Scene tree with native internal moves and folder-only drop targets."""
from PySide6.QtCore import Signal, Qt
from PySide6.QtWidgets import QAbstractItemView, QTreeWidget


class SceneTree(QTreeWidget):
    moved = Signal()

    def __init__(self):
        super().__init__()
        self.setHeaderHidden(True)
        self.setColumnCount(1)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragDropMode(QAbstractItemView.InternalMove)
        self.setDefaultDropAction(Qt.MoveAction)
        self.setDropIndicatorShown(True)
        self.setAutoExpandDelay(600)
        self.setUniformRowHeights(True)

    def dropEvent(self, event):
        # Qt rejects self/descendant moves and items without ItemIsDropEnabled.
        blocked = self.blockSignals(True)
        try:
            super().dropEvent(event)
        finally:
            self.blockSignals(blocked)
        if event.isAccepted():
            self.moved.emit()
