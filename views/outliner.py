# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 Marco Sumari Tellez and IngeTrazo contributors.
"""Browser: the model's tree, and the composer's views and sheets.

**The Browser** (a sidebar tab of the model window) is the Outliner
(#219): every group and component at every depth, under the document's
name. An icon says what each row is (group, component, image, 3D text, a
BIM-tagged element, or what an extension says it is); the eye shows or
hides it, the padlock locks it; the filter keeps the rows whose name, type,
BIM class or layer match, with the containers on the way to them. A click
selects in the view — opening the groups around it, as double-clicking down
to it would — and a double-click (or Enter) opens it for editing. A
selection made in the view is found in the tree, its branch unfolded, and
the groups open for editing read in bold, so the tree always says where you
are. Below the groups, the section planes, each with its cut, frame and
fill.

**Views and sheets** (:class:`SheetsPanel`, docked in the sheet composer,
beside the page) lists the saved scenes and the sheets with their view
frames. A scene dragged onto the page lands as a view where it is dropped;
each scene says which sheets place it, a frame whose scene was deleted is
flagged instead of breaking, and the sheets are opened, ordered, copied,
deleted and printed from there.

The Outliner is built on the Project Structure plugin Carlos Martins
(@fafecm) shared in #87 — the tree mirrored with the view both ways, the
eye per node, entering a nested group through its path — and on the scope
Roy Méndez Castro (@roymendezcastro) wrote down in #219. Its drag and
drop and its padlock are here too: re-nesting keeps every group where it
stands in the world, whatever frame the new parent has, and the lock is
saved in the document.

The model stays the only source of truth: rows hold their group (or scene,
sheet, frame) and renames and hides are the usual undoable commands.
"""
from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QIcon, QPainter, QPalette, QPen,
                           QPixmap)
from PySide6.QtWidgets import (QAbstractItemView, QDockWidget, QHBoxLayout,
                               QHeaderView, QLabel, QLineEdit, QStyle,
                               QToolButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from core import outliner
from core.group import Group
from core.i18n import tr
from core.section import SectionPlane

# Model tab columns.
(COL_NAME, COL_EYE, COL_LOCK, COL_TYPE, COL_LAYER, COL_MATERIAL, COL_COPIES,
 COL_IFC) = range(8)
#: Columns the header's right-click shows or hides, and which start shown.
OPTIONAL_COLUMNS = ((COL_TYPE, "Type", True), (COL_LAYER, "Layer", True),
                    (COL_MATERIAL, "Material", False),
                    (COL_COPIES, "Copies", False),
                    (COL_IFC, "IFC class", False))

# Keys the tree answers itself while it has the focus, instead of the
# window's single-key shortcuts (Space is Select, Esc cancels a tool…).
_TREE_KEYS = {Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Escape,
              Qt.Key_F2, Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right,
              Qt.Key_Home, Qt.Key_End, Qt.Key_PageUp, Qt.Key_PageDown}


# ---- Icons ---------------------------------------------------------------------
# Drawn, like the tool icons (views/icons.py), in the palette's own ink so
# they read in the light and the dark theme alike.

_ICONS: dict = {}


def _ink() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().text().color()


def _accent() -> QColor:
    from PySide6.QtWidgets import QApplication
    return QApplication.palette().highlight().color()


def _cube(p, ink, fill=None) -> None:
    """A small box in cavalier view: the group's mark."""
    front = QRectF(2.5, 6.5, 9, 8)
    if fill is not None:
        p.setBrush(fill)
    p.drawPolygon([QPointF(2.5, 6.5), QPointF(6.5, 2.5), QPointF(15.5, 2.5),
                   QPointF(15.5, 10.5), QPointF(11.5, 14.5),
                   QPointF(2.5, 14.5)])
    p.setBrush(Qt.NoBrush)
    p.drawRect(front)
    p.drawLine(QPointF(11.5, 6.5), QPointF(15.5, 2.5))


def _draw(key: str):
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(ink, 1.2))
    if key == "group":
        _cube(p, ink)
    elif key == "component":
        # A component is a box FILLED: the definition its copies share.
        fill = QColor(_accent())
        fill.setAlpha(110)
        _cube(p, ink, fill)
    elif key == "ifc":
        _cube(p, ink)
        p.setPen(Qt.NoPen)
        p.setBrush(_accent())
        p.drawEllipse(QRectF(10, 10, 7.5, 7.5))
    elif key == "document":
        p.drawPolygon([QPointF(2, 9), QPointF(9, 3), QPointF(16, 9)])
        p.drawRect(QRectF(4, 9, 10, 7))
    elif key == "sheet":
        p.drawPolygon([QPointF(3.5, 1.5), QPointF(11.5, 1.5),
                       QPointF(14.5, 4.5), QPointF(14.5, 16.5),
                       QPointF(3.5, 16.5)])
        p.drawLine(QPointF(11.5, 1.5), QPointF(11.5, 4.5))
        p.drawLine(QPointF(11.5, 4.5), QPointF(14.5, 4.5))
        p.drawLine(QPointF(6, 12), QPointF(12, 12))
        p.drawLine(QPointF(6, 14), QPointF(10, 14))
    elif key == "frame":
        p.drawRect(QRectF(2.5, 4.5, 13, 10))
        p.drawPolyline([QPointF(4, 13), QPointF(8, 8), QPointF(11, 11),
                        QPointF(14, 7)])
    elif key == "scene":
        # A camera: what a saved scene remembers.
        p.drawRect(QRectF(2.5, 6.5, 9, 7))
        p.drawPolygon([QPointF(11.5, 9), QPointF(15.5, 6.5),
                       QPointF(15.5, 13.5)])
    elif key in ("cut", "cut_off"):
        # A box sliced: the cut half filled when the plane cuts.
        if key == "cut":
            fill = QColor(_accent())
            fill.setAlpha(160)
            p.setPen(Qt.NoPen)
            p.setBrush(fill)
            p.drawPolygon([QPointF(3, 3), QPointF(15, 3), QPointF(3, 15)])
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(ink, 1.2))
        else:
            faint = QColor(ink)
            faint.setAlpha(110)
            p.setPen(QPen(faint, 1.2))
        p.drawRect(QRectF(3, 3, 12, 12))
        p.drawLine(QPointF(1.5, 16.5), QPointF(16.5, 1.5))
    elif key in ("lock", "lock_open"):
        # The shackle closed over the body, or swung up and open.
        p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
        if key == "lock":
            p.drawArc(QRectF(5.5, 2.5, 7, 10), 0, 180 * 16)
            p.drawLine(QPointF(5.5, 7.5), QPointF(5.5, 8.5))
            p.drawLine(QPointF(12.5, 7.5), QPointF(12.5, 8.5))
        else:
            faint = QColor(ink)
            faint.setAlpha(110)
            p.setPen(QPen(faint, 1.2))
            p.drawRoundedRect(QRectF(4, 8.5, 10, 7.5), 1.5, 1.5)
            p.drawArc(QRectF(8.5, 1.5, 7, 9), 0, 180 * 16)
            p.drawLine(QPointF(8.5, 6), QPointF(8.5, 8.5))
    elif key in ("eye", "eye_off"):
        if key == "eye_off":
            p.setPen(QPen(QColor(ink.red(), ink.green(), ink.blue(), 110),
                          1.2))
        p.drawEllipse(QRectF(2, 5.5, 14, 7))
        p.setBrush(p.pen().color())
        p.drawEllipse(QRectF(7, 7, 4, 4))
        if key == "eye_off":
            p.setPen(QPen(ink, 1.4))
            p.drawLine(QPointF(3, 15), QPointF(15, 3))
    p.end()
    return QIcon(pm)


def node_icon(key: str) -> QIcon:
    """The icon for a row kind — ``group``, ``component``, ``ifc``,
    ``image``, ``text``, ``document``, ``scene``, ``sheet``, ``frame``,
    ``eye``, ``eye_off``, ``warning``."""
    if key not in _ICONS:
        if key in ("image", "text", "sections"):
            from views.icons import tool_icon
            _ICONS[key] = tool_icon({"image": "image", "text": "text3d",
                                     "sections": "section_planes"}[key])
        elif key == "warning":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(
                QStyle.SP_MessageBoxWarning)
        elif key == "folder":
            from PySide6.QtWidgets import QApplication
            _ICONS[key] = QApplication.style().standardIcon(QStyle.SP_DirIcon)
        else:
            _ICONS[key] = _draw(key)
    return _ICONS[key]


def fill_icon(color, on: bool) -> QIcon:
    """The section fill as a swatch: the style's fill colour, hatched, or
    an empty faint square when the fill is off."""
    ink = _ink()
    pm = QPixmap(18, 18)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    if on:
        r, g, b = (max(0, min(255, round(c * 255))) for c in color[:3])
        p.setBrush(QColor(r, g, b))
        p.setPen(QPen(ink, 1.2))
        p.drawRect(QRectF(3, 3, 12, 12))
        p.setPen(QPen(QColor(255, 255, 255, 140), 1.0))
        for k in (6, 10, 14):
            p.drawLine(QPointF(3, 3 + k), QPointF(3 + k, 3))
    else:
        faint = QColor(ink)
        faint.setAlpha(110)
        p.setPen(QPen(faint, 1.2, Qt.DashLine))
        p.drawRect(QRectF(3, 3, 12, 12))
    p.end()
    return QIcon(pm)


def _remember_widths(header, key: str, columns) -> None:
    """Give ``columns`` the widths the user left them at, and keep them
    as they are dragged (per user, not per document)."""
    from PySide6.QtCore import QSettings
    saved = QSettings().value(key)
    if isinstance(saved, str):
        saved = saved.split(",")
    if isinstance(saved, (list, tuple)) and len(saved) == len(columns):
        for col, width in zip(columns, saved):
            try:
                if int(width) >= 40:
                    header.resizeSection(col, int(width))
            except (TypeError, ValueError):
                pass

    def save(*_args) -> None:
        QSettings().setValue(key, ",".join(
            str(header.sectionSize(c)) for c in columns))

    header.sectionResized.connect(save)


def _tool_button(text: str, tip: str, slot) -> QToolButton:
    btn = QToolButton()
    btn.setText(text)
    btn.setToolTip(tip)
    btn.setAutoRaise(True)
    btn.clicked.connect(slot)
    return btn


# ---- Model 3D ------------------------------------------------------------------

class _Tree(QTreeWidget):
    """The tree, with the keyboard of an outliner: Space shows or hides the
    selected rows, Enter opens the current one, Esc steps out one level,
    Tab puts the selection into the group above it and Shift+Tab takes it
    out one level. Rows dragged onto a group go into it; dropped between
    rows, they go beside them."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.InternalMove)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        editing = self.state() == QAbstractItemView.EditingState
        if (ev.type() == QEvent.ShortcutOverride and not editing
                and (ev.key() in _TREE_KEYS
                     or ev.key() in (Qt.Key_Tab, Qt.Key_Backtab))
                and not (ev.modifiers() & (Qt.ControlModifier
                                           | Qt.AltModifier))):
            ev.accept()
            return True
        # Tab moves the focus before keyPressEvent ever sees it.
        if (ev.type() == QEvent.KeyPress and not editing
                and ev.key() in (Qt.Key_Tab, Qt.Key_Backtab)):
            if ev.key() == Qt.Key_Backtab or \
                    ev.modifiers() & Qt.ShiftModifier:
                self._panel.outdent()
            else:
                self._panel.indent()
            return True
        return super().event(ev)

    def dropEvent(self, ev) -> None:
        """Re-nest through the panel — one undoable command — and never let
        Qt move the rows itself: the tree follows the model, not the other
        way round."""
        item = self.itemAt(ev.position().toPoint())
        if item is not None and \
                self.dropIndicatorPosition() != QAbstractItemView.OnItem:
            item = item.parent()            # between rows: beside them
        ev.setDropAction(Qt.IgnoreAction)
        ev.accept()
        sections = self._panel._sec_root
        if item is not None and sections is not None and (
                item is sections or item.parent() is sections):
            return                          # planes are not containers
        self._panel.reparent(self._panel._selected_groups(),
                             self._panel._group_of(item))

    def keyPressEvent(self, ev) -> None:
        if self.state() != QAbstractItemView.EditingState:
            key = ev.key()
            if key == Qt.Key_F2:
                plane = self._panel._plane_of(self.currentItem())
                if plane is not None:
                    self._panel.rename_plane(plane)
                    return
            if key == Qt.Key_Space:
                self._panel.toggle_hidden()
                return
            if key in (Qt.Key_Return, Qt.Key_Enter):
                item = self.currentItem()
                if item is not None:
                    self._panel.open_item(item)
                return
            if key == Qt.Key_Escape:
                self._panel.step_out()
                return
        super().keyPressEvent(ev)


class OutlinerPanel(QWidget):
    """The model's tree of groups and components (the Model 3D tab)."""

    def __init__(self, window) -> None:
        super().__init__()
        self._window = window
        self._updating = False
        self._stale = False
        self._shape: tuple | None = None
        self._items: dict = {}              # id(group) -> its row
        self._groups: dict = {}             # id(group) -> the group
        self._state: dict = {}              # id(group) -> what its row shows
        self._shown_selection: tuple = ()
        self._shown_path: tuple = ()
        self._query = ""
        self._kind_providers: tuple = ()
        self._root = None
        self._sec_root = None               # the «Section planes» folder
        self._sec_items: dict = {}          # id(plane) -> its row
        self._sec_state: dict = {}
        self._sec_shape = None
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        bar = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Filter by name, type or layer…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._on_filter)
        bar.addWidget(self.search, 1)
        bar.addWidget(_tool_button("◎", tr(
            "Isolate: hide everything but the selected groups"),
            self.isolate))
        bar.addWidget(_tool_button("◉", tr("Show all groups"),
                                   self.show_all))
        bar.addWidget(_tool_button("⊞", tr("Expand all"), self._expand_all))
        bar.addWidget(_tool_button("⊟", tr("Collapse all"),
                                   self._collapse_all))
        lay.addLayout(bar)
        self.tree = _Tree(self)
        self.tree.setColumnCount(8)
        self.tree.setHeaderLabels([tr("Name"), "", "", tr("Type"),
                                   tr("Layer"), tr("Material"), tr("Copies"),
                                   tr("IFC class")])
        head = self.tree.header()
        # The Name column is the user's to size — drag its edge in the
        # header; the width is remembered. The Layer column takes the rest.
        head.setStretchLastSection(True)
        head.setSectionResizeMode(COL_NAME, QHeaderView.Interactive)
        head.resizeSection(COL_NAME, 200)
        head.setSectionResizeMode(COL_EYE, QHeaderView.Fixed)
        head.resizeSection(COL_EYE, 26)
        head.setSectionResizeMode(COL_LOCK, QHeaderView.Fixed)
        head.resizeSection(COL_LOCK, 26)
        head.setSectionResizeMode(COL_TYPE, QHeaderView.Interactive)
        head.resizeSection(COL_TYPE, 110)
        head.setSectionResizeMode(COL_LAYER, QHeaderView.Interactive)
        head.resizeSection(COL_LAYER, 80)
        _remember_widths(head, "browser/model_columns",
                         (COL_NAME, COL_TYPE))
        for col, width in ((COL_MATERIAL, 100), (COL_COPIES, 60),
                           (COL_IFC, 110)):
            head.setSectionResizeMode(col, QHeaderView.Interactive)
            head.resizeSection(col, width)
        # Right-click on the header: which columns show (remembered).
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(self._on_header_menu)
        self._apply_column_choice()
        self.tree.headerItem().setIcon(COL_EYE, node_icon("eye"))
        self.tree.headerItem().setToolTip(COL_EYE, tr("Visible"))
        self.tree.headerItem().setIcon(COL_LOCK, node_icon("lock"))
        self.tree.headerItem().setToolTip(COL_LOCK, tr(
            "Locked: drawn, but it cannot be picked, selected or opened"))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        # Double-click OPENS a group, as in the view: renaming is F2 or the
        # context menu.
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.setToolTip(tr(
            "Click to select in the model; double-click or Enter opens the "
            "group. The eye (or Space) shows or hides, the padlock locks; "
            "F2 renames; Esc steps out one level. Drag rows onto a group, "
            "or press Tab / Shift+Tab, to move them in or out of it."))
        self.tree.itemSelectionChanged.connect(self._on_tree_selection)
        self.tree.itemClicked.connect(self._on_item_clicked)
        self.tree.itemDoubleClicked.connect(self._on_double_clicked)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        self._root = None
        lay.addWidget(self.tree, 1)
        self._empty = QLabel(tr(
            "No groups or components in the model yet."))
        self._empty.setWordWrap(True)
        self._empty.setEnabled(False)
        lay.addWidget(self._empty)
        self.summary = QLabel()
        self.summary.setEnabled(False)
        lay.addWidget(self.summary)
        self._matches = 0
        self.refresh()

    # ---- Model → view --------------------------------------------------------
    def _scene(self):
        return self._window.viewport.scene

    def on_scene_changed(self) -> None:
        """The dock's per-change call: refreshed when on screen, on
        showing otherwise — a hidden tab costs nothing per edit. On screen,
        one refresh 300 ms after the last edit: every row's state is read
        again (17 ms per edit on the Plaza, release_check 09-10), and a
        burst of edits pays it once."""
        if not self.isVisible():
            if not self._stale and self._holds_departed_groups():
                self._forget_rows()     # New / Open: let the old one go
            self._stale = True
            return
        timer = getattr(self, "_refresh_timer", None)
        if timer is None:
            from PySide6.QtCore import QTimer
            timer = self._refresh_timer = QTimer(self)
            timer.setSingleShot(True)
            timer.timeout.connect(self.refresh)
        timer.start(300)

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        if self._stale:
            self.refresh()

    def _document_name(self) -> str:
        w = self._window
        path = getattr(w, "_current_path", None)
        if path is not None:
            return path.name
        return getattr(w, "_import_name", None) or tr("Untitled")

    def refresh(self) -> None:
        """Bring the tree up to date: rows rebuilt only when groups came or
        went, otherwise updated in place — a refresh follows every edit and
        every click, and a rebuild would lose the scroll and the branches
        the user unfolded."""
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        self._stale = False
        self._kind_providers = tuple(
            getattr(self._window, "_outliner_kinds", None) or ())
        scene = self._scene()
        shape = outliner.structure(scene.groups)
        if shape != self._shape:
            self._rebuild(scene)
            self._shape = shape
        self._update_rows(scene)
        self._sync_sections(scene)
        if self._query:
            self._apply_filter()
        self._sync_selection(scene)
        self._empty.setVisible(not self._items)
        self._update_summary()

    def _holds_departed_groups(self) -> bool:
        """Whether a row still holds a group the model no longer has —
        after New or Open (both load into the same scene), or a delete."""
        if not self._groups:
            return False
        live = {id(g) for g, _p, _d in outliner.walk(self._scene().groups)}
        return any(key not in live for key in self._groups)

    def _forget_rows(self) -> None:
        """Drop the rows of a document that is no longer open. Each row
        holds its group, so a hidden Browser waiting to be shown kept the
        whole previous document in memory after Open (release_check
        10-10); the next refresh builds the rows of the new one."""
        self._kept_expanded = {self._groups[key].uid
                               for key, item in self._items.items()
                               if item.isExpanded()}
        self.tree.clear()
        self._items = {}
        self._groups = {}
        self._state = {}
        self._root = None
        self._shape = None

    def _update_summary(self) -> None:
        """The footer: what the model holds, or what the filter found."""
        total = len(self._state)
        if self._query:
            text = tr("{shown} of {total} match", shown=self._matches,
                      total=total)
        else:
            comps = sum(1 for st in self._state.values()
                        if st[3] == "component")
            hidden = sum(1 for st in self._state.values() if st[4])
            text = tr("{groups} groups · {components} components · "
                      "{hidden} hidden", groups=total - comps,
                      components=comps, hidden=hidden)
        if self.summary.text() != text:
            self.summary.setText(text)

    def _rebuild(self, scene) -> None:
        """Rows for every group, each born with its texts and icons: one
        constructor call does what a setText per column would, and the
        cache it fills tells ``_update_rows`` there is nothing left to do."""
        expanded = {self._groups[key].uid
                    for key, item in self._items.items() if item.isExpanded()}
        expanded |= self.__dict__.pop("_kept_expanded", set())
        scroll = self.tree.verticalScrollBar().value()
        counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            self._items = {}
            self._groups = {}
            self._state = {}
            root = self._root = QTreeWidgetItem(["", "", "", "", ""])
            root.setIcon(COL_NAME, node_icon("document"))
            root.setFlags(Qt.ItemIsEnabled | Qt.ItemIsDropEnabled)
            font = QFont(root.font(COL_NAME))
            font.setBold(True)
            root.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(root)
            editable = Qt.ItemIsEditable
            for g, parent, _depth in outliner.walk(scene.groups):
                key = id(g)
                state = self._row_state(g, counts, opened)
                item = QTreeWidgetItem([state[0], "", "", state[1],
                                        state[2], state[7], state[8],
                                        state[9]])
                item.setData(COL_NAME, Qt.UserRole, g)
                item.setFlags(item.flags() | editable)
                self._paint(item, None, state)
                (root if parent is None
                 else self._items[id(parent)]).addChild(item)
                self._items[key] = item
                self._groups[key] = g
                self._state[key] = state
            root.setExpanded(True)
            sec = self._sec_root = QTreeWidgetItem(["", "", "", "", ""])
            sec.setIcon(COL_NAME, node_icon("sections"))
            sec.setFlags(Qt.ItemIsEnabled)
            sec.setFont(COL_NAME, font)
            self.tree.addTopLevelItem(sec)
            self._sec_items = {}
            self._sec_shape = None
            self._sec_state = {}
            self._sec_folder = None         # a new row: its texts to write
            for key, item in self._items.items():
                if self._groups[key].uid in expanded:
                    item.setExpanded(True)
        finally:
            self.tree.blockSignals(False)
            self._updating = False
        self._shown_selection = ()
        self._shown_path = ()
        self.tree.verticalScrollBar().setValue(scroll)

    def _kind(self, group) -> str:
        return "ifc" if outliner.ifc_class(group) else outliner.kind(group)

    def _providers(self):
        # Read once per refresh (see refresh): asked per row, the lookup of
        # a missing attribute on the Qt window cost ~1 s on 10 000 rows.
        return self._kind_providers

    def _type_text(self, group, counts) -> str:
        custom = outliner.custom_kind(group, self._providers())
        if custom is not None:
            return custom["type"]
        cls = outliner.ifc_class(group)
        if cls:
            return cls
        kind = outliner.kind(group)
        if kind == "component":
            n = counts.get(id(group.mesh), 1)
            return (tr("Component") if n < 2
                    else tr("Component ({n} copies)", n=n))
        return {"group": tr("Group"), "image": tr("Image"),
                "text": tr("3D Text")}[kind]

    def _row_state(self, g, counts, opened) -> tuple:
        """Everything a row shows: ``(name, type, layer, kind, hidden,
        open, locked, material, copies, IFC class, properties)`` — compared
        as one tuple, so an unchanged row costs no Qt call at all."""
        custom = outliner.custom_kind(g, self._providers())
        props = "\n".join(f"{k}: {v}" for k, v in custom["props"]) \
            if custom else ""
        copies = (str(counts.get(id(g.mesh), 1)) if g.is_component()
                  else "")
        return (g.name or tr("Unnamed group"),
                custom["type"] if custom else self._type_text(g, counts),
                outliner.layer_name(g), self._kind(g), bool(g.hidden),
                id(g) in opened, bool(getattr(g, "locked", False)),
                outliner.material_name(g), copies, outliner.ifc_class(g),
                props)

    def _paint(self, item, old, new) -> None:
        """Bring ``item`` from the ``old`` state (``None``: just made, texts
        already in) to ``new``, touching only what differs."""
        if old is not None:
            for col, i in ((COL_NAME, 0), (COL_TYPE, 1), (COL_LAYER, 2),
                           (COL_MATERIAL, 7), (COL_COPIES, 8),
                           (COL_IFC, 9)):
                if old[i] != new[i]:
                    item.setText(col, new[i])
        if old is None or old[10] != new[10]:
            item.setToolTip(COL_TYPE, new[10])
        kind, hidden, bold = new[3], new[4], new[5]
        if old is None or old[3] != kind:
            item.setData(COL_TYPE, Qt.UserRole, kind)
            item.setIcon(COL_NAME, node_icon(kind))
        if old is None or old[4] != hidden:
            item.setData(COL_EYE, Qt.UserRole, hidden)
            item.setIcon(COL_EYE, node_icon("eye_off" if hidden else "eye"))
            if hidden or old is not None:
                item.setForeground(COL_NAME, self.tree.palette().brush(
                    QPalette.PlaceholderText if hidden else QPalette.Text))
        if (old is None and bold) or (old is not None and old[5] != bold):
            font = QFont(item.font(COL_NAME))
            font.setBold(bold)
            item.setFont(COL_NAME, font)
            item.setToolTip(COL_NAME, tr("Open for editing") if bold else "")
        locked = new[6]
        if old is None or old[6] != locked:
            item.setData(COL_LOCK, Qt.UserRole, locked)
            item.setIcon(COL_LOCK, node_icon("lock" if locked
                                             else "lock_open"))

    def _update_rows(self, scene) -> None:
        counts = outliner.instance_counts(scene.groups)
        opened = {id(g) for g in outliner.open_path(scene)}
        self._updating = True
        try:
            name = self._document_name()
            if self._root.text(COL_NAME) != name:
                self._root.setText(COL_NAME, name)
            state_of = self._state
            for key, g in self._groups.items():
                state = self._row_state(g, counts, opened)
                old = state_of[key]
                if state != old:
                    self._paint(self._items[key], old, state)
                    state_of[key] = state
        finally:
            self._updating = False

    def _reveal(self, item) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def _sync_selection(self, scene) -> None:
        """Highlight what is selected in the view and, when that changed,
        unfold its branch and scroll it into sight; unfold the groups open
        for editing too, so the context is on screen."""
        path = tuple(id(g) for g in outliner.open_path(scene))
        if path != self._shown_path:
            for key in path:
                item = self._items.get(key)
                if item is not None:
                    self._reveal(item)
                    item.setExpanded(True)
            self._shown_path = path
        chosen = tuple(id(g) for g in scene.selection
                       if id(g) in self._items)
        self.tree.blockSignals(True)
        try:
            wanted = set(chosen)
            for key, item in self._items.items():
                if item.isSelected() != (key in wanted):
                    item.setSelected(key in wanted)
            if chosen and set(chosen) != set(self._shown_selection):
                first = self._items[chosen[0]]
                self._reveal(first)
                self.tree.setCurrentItem(first, COL_NAME,
                                         QItemSelectionModel.NoUpdate)
                self.tree.scrollToItem(first)
        finally:
            self.tree.blockSignals(False)
        self._shown_selection = chosen

    # ---- Filter --------------------------------------------------------------
    def _on_filter(self, text: str) -> None:
        self._query = text.strip().casefold()
        self._apply_filter()
        self._update_summary()

    def _apply_filter(self) -> None:
        """Hide the rows the filter leaves out — no rebuild: a filter typed
        letter by letter over thousands of rows only flips their flag."""
        self._filter_sections()
        if not self._query:
            self._matches = len(self._items)
            for item in self._items.values():
                if item.isHidden():
                    item.setHidden(False)
            return
        scene = self._scene()
        counts = outliner.instance_counts(scene.groups)
        keep, hit = outliner.filter_keep(
            scene.groups, self._query,
            lambda g: self._type_text(g, counts))
        self._matches = len(hit)
        for key, item in self._items.items():
            item.setHidden(key not in keep)
            if key in keep and key not in hit:
                item.setExpanded(True)

    def _expand_all(self) -> None:
        self.tree.expandAll()

    def _collapse_all(self) -> None:
        self.tree.collapseAll()
        if self._root is not None:
            self._root.setExpanded(True)

    # ---- View → model --------------------------------------------------------
    def _open_to(self, path) -> bool:
        """Leave the view with exactly ``path`` open — stepping out of the
        levels that differ, then into the rest, one level at a time, as the
        view's own double-click and Esc do. False when a group on the way
        is hidden (it cannot be entered)."""
        if any(g.hidden or getattr(g, "locked", False) for g in path):
            return False
        vp = self._window.viewport
        scene = self._scene()
        current = outliner.open_path(scene)
        same = 0
        while (same < min(len(current), len(path))
               and current[same] is path[same]):
            same += 1
        for _ in range(len(current) - same):
            vp.end_one_group_edit()
        for g in path[same:]:
            vp.begin_group_edit(g)
        return outliner.open_path(scene) == list(path)

    def _group_of(self, item):
        data = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return data if isinstance(data, Group) else None

    def _plane_of(self, item):
        data = item.data(COL_NAME, Qt.UserRole) if item is not None else None
        return data if isinstance(data, SectionPlane) else None

    # ---- Section planes ------------------------------------------------------
    _SECTION_MODE_TEXT = {
        "both": "Cut and frame", "cut": "Cut only (no frame)",
        "frame": "Frame only (no cut)", "off": "Off"}

    def _sync_sections(self, scene) -> None:
        """The «Section planes» folder: one row per plane, its mode in
        words, the eye for its frame and the slice for its cut; the folder
        row carries the two global switches (View ▸ Section Planes and
        Section Cuts)."""
        sec = self._sec_root
        if sec is None:
            return
        planes = list(getattr(scene, "section_planes", None) or ())
        shape = tuple(id(sp) for sp in planes)
        self._updating = True
        try:
            if shape != self._sec_shape:
                expanded = sec.isExpanded() or self._sec_shape is None
                sec.takeChildren()
                self._sec_items = {}
                self._sec_state = {}
                for sp in planes:
                    item = QTreeWidgetItem(["", "", "", "", ""])
                    item.setData(COL_NAME, Qt.UserRole, sp)
                    item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setIcon(COL_NAME, node_icon("sections"))
                    item.setToolTip(COL_LOCK, tr(
                        "Click: this plane cuts the model (or stops)"))
                    sec.addChild(item)
                    self._sec_items[id(sp)] = item
                self._sec_shape = shape
                sec.setExpanded(expanded)
            fill = self._fill_state(scene)
            for sp in planes:
                item = self._sec_items[id(sp)]
                mode = outliner.section_mode(sp)
                own = dict(getattr(sp, "fill", None) or {})
                state = (outliner.section_label(sp), mode, fill,
                         tuple(sorted((k, tuple(v) if k == "color" else v)
                                      for k, v in own.items())))
                if self._sec_state.get(id(sp)) == state:
                    continue
                self._sec_state[id(sp)] = state
                item.setText(COL_NAME, state[0])
                item.setText(COL_TYPE, tr(self._SECTION_MODE_TEXT[mode]))
                cut, frame = outliner.SECTION_MODES[mode]
                item.setData(COL_EYE, Qt.UserRole, not frame)
                item.setIcon(COL_EYE, node_icon("eye" if frame else "eye_off"))
                item.setToolTip(COL_EYE, tr("Hide the frame, keep the cut")
                                if frame else tr("Show the frame"))
                item.setData(COL_LOCK, Qt.UserRole, cut)
                item.setIcon(COL_LOCK, node_icon("cut" if cut else "cut_off"))
                self._paint_fill(item, cut, fill, sp)
                item.setForeground(COL_NAME, self.tree.palette().brush(
                    QPalette.PlaceholderText if mode == "off"
                    else QPalette.Text))
            # The folder: the global switches, and the count.
            shown = bool(getattr(scene, "show_section_planes", True))
            cuts = bool(getattr(scene, "show_section_cuts", True))
            folder = (tr("Section planes"), shown, cuts, len(planes), fill)
            if getattr(self, "_sec_folder", None) != folder:
                self._sec_folder = folder
                sec.setText(COL_NAME, folder[0])
                sec.setText(COL_TYPE, tr("{n} planes", n=len(planes)))
                sec.setIcon(COL_EYE, node_icon("eye" if shown else "eye_off"))
                sec.setToolTip(COL_EYE, tr(
                    "Every section plane's frame (View ▸ Section Planes)"))
                sec.setIcon(COL_LOCK, node_icon("cut" if cuts else "cut_off"))
                sec.setToolTip(COL_LOCK, tr(
                    "Section cuts in the model (View ▸ Section Cuts)"))
                self._paint_fill(sec, True, fill)
            sec.setHidden(not planes)
        finally:
            self._updating = False

    def _filter_sections(self) -> None:
        sec = self._sec_root
        if sec is None:
            return
        any_shown = False
        for i in range(sec.childCount()):
            item = sec.child(i)
            show = not self._query or self._query in item.text(
                COL_NAME).casefold()
            item.setHidden(not show)
            any_shown = any_shown or show
        sec.setHidden(sec.childCount() == 0 or not any_shown)

    _PATTERN_TEXT = {"solid": "Solid", "hatch": "Hatched 45°",
                     "cross": "Cross-hatched", "none": "No fill"}

    def set_plane_fill(self, plane, **changes) -> None:
        """Change this cut's own fill — ``pattern``, ``color``, ``spacing``;
        a value of ``None`` drops that key back to the style's. One undo
        step."""
        from core.history import SetSectionFillCommand
        fill = dict(getattr(plane, "fill", None) or {})
        for key, value in changes.items():
            if value is None:
                fill.pop(key, None)
            else:
                fill[key] = value
        if fill == (getattr(plane, "fill", None) or {}):
            return
        self._window.viewport.history.execute(
            SetSectionFillCommand(plane, fill or None))
        self._window.viewport.update()
        self.refresh()

    def pick_plane_fill_color(self, plane) -> None:
        from views.color_dialog import get_color
        from core.section import effective_fill
        _p, color, _s = effective_fill(
            plane, getattr(self._scene(), "display_style", None))
        chosen = get_color(QColor.fromRgbF(*(float(c) for c in color[:3])),
                           self, tr("Fill color of this cut"))
        if chosen.isValid():
            self.set_plane_fill(plane, color=(chosen.redF(), chosen.greenF(),
                                              chosen.blueF()))

    def ask_plane_hatch_spacing(self, plane) -> None:
        """The hatch spacing, typed as any length (5cm, 50mm, 2") — a bare
        number in the document's unit."""
        from core.section import effective_fill
        from core.units import fmt_len
        from views import prompts
        from views.viewport import _parse_length_field
        _p, _c, spacing = effective_fill(
            plane, getattr(self._scene(), "display_style", None))
        text, ok = prompts.get_text(self, tr("Hatch spacing"),
                                    tr("Distance between hatch lines:"),
                                    text=fmt_len(spacing))
        if not ok:
            return
        value = _parse_length_field(text or "")
        if value is None or value <= 0:
            self._window.viewport.flash_status(
                tr("Not a length: {text}", text=text), 3000)
            return
        self.set_plane_fill(plane, spacing=float(value))

    def _plane_fill_menu(self, menu, plane) -> None:
        """The cut's own fill: pattern, colour, spacing, or the style's."""
        from PySide6.QtCore import QTimer
        sub = menu.addMenu(tr("Fill of this cut"))
        own = getattr(plane, "fill", None) or {}
        current = own.get("pattern")
        act = sub.addAction(tr("As the style"), lambda: self.set_plane_fill(
            plane, pattern=None))
        act.setCheckable(True)
        act.setChecked(current is None)
        for pattern in ("solid", "hatch", "cross", "none"):
            act = sub.addAction(tr(self._PATTERN_TEXT[pattern]),
                                lambda p=pattern: self.set_plane_fill(
                                    plane, pattern=p))
            act.setCheckable(True)
            act.setChecked(current == pattern)
        sub.addSeparator()
        # Dialogs open once the menu has closed (see _fill_actions).
        sub.addAction(tr("Fill color of this cut…"), lambda: QTimer.singleShot(
            0, lambda: self.pick_plane_fill_color(plane)))
        if own.get("color") is not None:
            sub.addAction(tr("Use the style's fill color"),
                          lambda: self.set_plane_fill(plane, color=None))
        sub.addAction(tr("Hatch spacing…"), lambda: QTimer.singleShot(
            0, lambda: self.ask_plane_hatch_spacing(plane)))

    def rename_plane(self, plane) -> bool:
        """Name and symbol of a section plane — the dialog the Section tool
        opens on placing one, here undoable."""
        from PySide6.QtWidgets import (QDialog, QDialogButtonBox,
                                       QFormLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Name Section Plane"))
        form = QFormLayout(dlg)
        name_edit = QLineEdit(plane.name)
        sym_edit = QLineEdit(plane.symbol)
        sym_edit.setMaxLength(3)
        form.addRow(tr("Name"), name_edit)
        form.addRow(tr("Symbol"), sym_edit)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._rename_dialog = dlg           # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return False
        return self.set_plane_name(plane, name_edit.text(), sym_edit.text())

    def set_plane_name(self, plane, name: str, symbol: str) -> bool:
        from core.history import RenameSectionPlaneCommand
        name = (name or "").strip() or plane.name
        symbol = (symbol or "").strip()[:3] or plane.symbol
        if (name, symbol) == (plane.name, plane.symbol):
            return False
        self._window.viewport.history.execute(
            RenameSectionPlaneCommand(plane, name, symbol))
        self._window.viewport.update()
        self.refresh()
        return True

    @staticmethod
    def _fill_state(scene) -> tuple:
        """``(on, colour)`` of the section fill — the display style's."""
        style = getattr(scene, "display_style", None)
        return (bool(getattr(style, "section_fill", True)),
                tuple(getattr(style, "section_fill_color",
                              (0.35, 0.37, 0.41))))

    def _paint_fill(self, item, show: bool, fill, plane=None) -> None:
        """The Fill cell (Layer column): on the folder row and on the plane
        that cuts — where a fill can show — empty on the others. A plane
        shows ITS fill: its own pattern and colour over the style's."""
        on, color = fill
        item.setData(COL_LAYER, Qt.UserRole, on if show else None)
        if not show:
            item.setIcon(COL_LAYER, QIcon())
            item.setText(COL_LAYER, "")
            item.setToolTip(COL_LAYER, "")
            return
        text = tr("Fill") if on else tr("No fill")
        if plane is not None:
            from core.section import effective_fill
            pattern, color, _s = effective_fill(
                plane, getattr(self._scene(), "display_style", None))
            on = pattern != "none"
            text = tr(self._PATTERN_TEXT[pattern])
        item.setIcon(COL_LAYER, fill_icon(color, on))
        item.setText(COL_LAYER, text)
        item.setToolTip(COL_LAYER, tr(
            "Section Fill: paint the cut faces solid (click to switch; its "
            "colour from the context menu or the Styles panel)"))

    def set_section_fill(self, on: bool) -> None:
        """View ▸ Section Fill, from the browser — the menu, the toolbar
        and the Styles panel follow."""
        w = self._window
        w._set_style_field("section_fill", bool(on))
        sync = getattr(w, "_sync_style_menu", None)
        if sync is not None:
            sync()
        self.refresh()

    def pick_section_fill_color(self) -> None:
        """The Styles panel's own colour picker for the fill — same dialog,
        same hint when the fill is off."""
        panel = getattr(self._window, "styles_panel", None)
        if panel is not None:
            panel._pick_color(tr("Section fill color"), "section_fill_color")
        self.refresh()

    def _fill_actions(self, menu) -> None:
        from PySide6.QtCore import QTimer
        on = self._fill_state(self._scene())[0]
        act = menu.addAction(tr("Section Fill"),
                             lambda: self.set_section_fill(not on))
        act.setCheckable(True)
        act.setChecked(on)
        # The dialog opens once the menu has closed: a modal opened inside
        # the menu's own event loop came back without a colour.
        menu.addAction(tr("Section fill color…"), lambda: QTimer.singleShot(
            0, self.pick_section_fill_color))

    def set_section_mode(self, plane, mode: str) -> None:
        """One plane: ``"both"``, ``"cut"``, ``"frame"`` or ``"off"`` —
        one undoable step."""
        from core.history import SetSectionModeCommand
        if outliner.section_mode(plane) == mode:
            return
        cut, frame = outliner.SECTION_MODES[mode]
        self._window.viewport.history.execute(
            SetSectionModeCommand(plane, cut, frame))
        self._window.viewport.update()
        self.refresh()

    def _toggle_section(self, plane, column) -> None:
        cut, frame = outliner.SECTION_MODES[outliner.section_mode(plane)]
        if column == COL_EYE:
            frame = not frame
        else:
            cut = not cut
        mode = {v: k for k, v in outliner.SECTION_MODES.items()}[(cut, frame)]
        self.set_section_mode(plane, mode)

    def set_section_globals(self, planes=None, cuts=None) -> None:
        """The View menu's two switches, from the folder row — they stay in
        step with the menu and the toolbar."""
        w = self._window
        if planes is not None:
            w._set_section_visibility("show_section_planes", planes)
        if cuts is not None:
            w._set_section_visibility("show_section_cuts", cuts)
        sync = getattr(w, "_sync_section_menu", None)
        if sync is not None:
            sync()
        self.refresh()

    def _select_plane(self, plane) -> None:
        scene = self._scene()
        if getattr(plane, "hidden", False):
            return                          # no frame to show selected
        scene.selection.clear()
        scene.selection.add(plane)
        self._shown_selection = ()
        scene.bump_view()
        self._window.viewport.update()

    def _selected_groups(self) -> list:
        return [g for g in (self._group_of(item)
                            for item in self.tree.selectedItems())
                if g is not None]

    def _on_tree_selection(self) -> None:
        """Rows picked in the tree become the view's selection. The view
        selects inside ONE context, so the rows that count are the current
        row's siblings; the groups above them open."""
        if self._updating:
            return
        current = self.tree.currentItem()
        plane = self._plane_of(current)
        if plane is not None and current.isSelected():
            self._select_plane(plane)
            return
        group = (self._group_of(current)
                 if current is not None and current.isSelected() else None)
        if group is None:
            picked = self._selected_groups()
            if not picked:
                return
            group = picked[0]
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        siblings = [g for g in self._selected_groups()
                    if outliner.path_to(scene.groups, g) == path]
        if not self._open_to(path):
            self._window.viewport.flash_status(tr(
                "A group around it is hidden or locked: show or unlock "
                "it to select inside"),
                3500)
            return
        picks = [g for g in siblings if scene.entity_selectable(g)]
        scene.selection.clear()
        scene.selection.update(picks)
        # Clicked here, so already in sight: the refresh this triggers must
        # not scroll the tree under the pointer.
        self._shown_selection = tuple(id(g) for g in picks)
        self._shown_path = tuple(id(g) for g in outliner.open_path(scene))
        scene.bump_view()
        self._window.viewport.update()

    def _on_item_clicked(self, item, column) -> None:
        if column == COL_LAYER and item.data(COL_LAYER, Qt.UserRole) \
                is not None and (item is self._sec_root
                                 or self._plane_of(item) is not None):
            self.set_section_fill(not self._fill_state(self._scene())[0])
            return
        if column in (COL_EYE, COL_LOCK):
            plane = self._plane_of(item)
            if plane is not None:
                self._toggle_section(plane, column)
                return
            if item is self._sec_root:
                scene = self._scene()
                if column == COL_EYE:
                    self.set_section_globals(planes=not getattr(
                        scene, "show_section_planes", True))
                else:
                    self.set_section_globals(cuts=not getattr(
                        scene, "show_section_cuts", True))
                return
        group = self._group_of(item)
        if group is None or column not in (COL_EYE, COL_LOCK):
            return
        # The eye or the padlock clicked on one of several selected rows
        # acts on all of them, as in an outliner.
        selected = self._selected_groups()
        targets = selected if group in selected else [group]
        if column == COL_EYE:
            self.toggle_hidden(targets)
        else:
            self.toggle_locked(targets)

    def _on_double_clicked(self, item, column) -> None:
        if column not in (COL_EYE, COL_LOCK):
            self.open_item(item)

    def open_item(self, item) -> None:
        """Open the row's group for editing — double-click or Enter. On a
        section plane: it cuts, or stops cutting."""
        plane = self._plane_of(item)
        if plane is not None:
            self._toggle_section(plane, COL_LOCK)
            return
        group = self._group_of(item)
        if group is None or group.hidden or getattr(group, "locked", False):
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if path is None:
            return
        if self._open_to(path + [group]):
            scene.bump_view()
            self._window.viewport.update()
            self.refresh()

    def step_out(self) -> None:
        """Esc: leave the innermost open group."""
        if self._scene().edit_group is None:
            return
        self._window.viewport.end_one_group_edit()
        self._window.viewport.update()
        self.refresh()

    def toggle_hidden(self, groups=None) -> None:
        """Show the rows when any of them is hidden, hide them otherwise —
        one undoable step."""
        from core.history import HideCommand
        if groups is None:
            plane = self._plane_of(self.tree.currentItem())
            if plane is not None:
                self._toggle_section(plane, COL_EYE)
                return
            # Hiding drops the rows from the selection: the current row is
            # what a second Space shows again.
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        hide = not any(g.hidden for g in groups)
        self._window.viewport.history.execute(HideCommand(groups,
                                                          hidden=hide))
        self._window.viewport.update()
        self.refresh()

    def toggle_locked(self, groups=None) -> None:
        """Unlock the rows when any of them is locked, lock them otherwise —
        one undoable step."""
        from core.history import LockCommand
        if groups is None:
            groups = self._selected_groups()
            current = self._group_of(self.tree.currentItem())
            if not groups and current is not None:
                groups = [current]
        groups = list(groups)
        if not groups:
            return
        lock = not any(getattr(g, "locked", False) for g in groups)
        if lock and any(g is self._scene().edit_group
                        or g in outliner.open_path(self._scene())
                        for g in groups):
            self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(LockCommand(groups, lock))
        self._window.viewport.update()
        self.refresh()

    _REPARENT_REFUSED = {
        "cycle": "A group cannot go inside itself or a group it holds",
        "component": "Components keep their parts: Make Unique first to "
                     "change what is inside one",
        "locked": "Unlock it first",
    }

    def reparent(self, groups, target) -> bool:
        """Put ``groups`` into ``target`` (``None``: the model) — one
        undoable step, nothing moves in the world."""
        from core.history import ReparentGroupsCommand
        scene = self._scene()
        moving = outliner.needs_moving(scene.groups, groups, target)
        if not moving:
            return False
        problem = outliner.reparent_problem(scene.groups, moving, target)
        if problem is not None:
            self._window.viewport.flash_status(
                tr(self._REPARENT_REFUSED[problem]), 4000)
            return False
        # The tools work on what is open: re-nesting under them is not
        # safe, and the view closes them as a click outside would.
        self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(
            ReparentGroupsCommand(moving, target))
        self._window.viewport.update()
        self.refresh()
        if target is not None:
            self._items[id(target)].setExpanded(True)
        first = self._items.get(id(moving[0]))
        if first is not None:
            self._reveal(first)
            self.tree.setCurrentItem(first, COL_NAME,
                                     QItemSelectionModel.NoUpdate)
            self.tree.scrollToItem(first)
        return True

    def indent(self) -> None:
        """Tab: into the group just above, at the same level."""
        current = self.tree.currentItem()
        group = self._group_of(current)
        if group is None:
            return
        parent = current.parent()
        index = parent.indexOfChild(current) if parent is not None else -1
        above = None
        while index > 0:
            index -= 1
            candidate = parent.child(index)
            if not candidate.isHidden():
                above = self._group_of(candidate)
                break
        if above is None:
            return
        self.reparent(self._selected_groups() or [group], above)

    def outdent(self) -> None:
        """Shift+Tab: out of the group it is in, one level up."""
        group = self._group_of(self.tree.currentItem())
        if group is None:
            return
        scene = self._scene()
        path = outliner.path_to(scene.groups, group)
        if not path:
            return
        self.reparent(self._selected_groups() or [group],
                      path[-2] if len(path) > 1 else None)

    # ---- Columns ---------------------------------------------------------
    def _hidden_columns(self) -> set:
        from PySide6.QtCore import QSettings
        raw = QSettings().value("browser/model_hidden_columns")
        if raw is None:
            return {c for c, _l, shown in OPTIONAL_COLUMNS if not shown}
        if isinstance(raw, str):
            raw = [x for x in raw.split(",") if x]
        out = set()
        for x in raw or ():
            try:
                out.add(int(x))
            except (TypeError, ValueError):
                pass
        return out

    def _apply_column_choice(self) -> None:
        hidden = self._hidden_columns()
        for col, _label, _shown in OPTIONAL_COLUMNS:
            self.tree.setColumnHidden(col, col in hidden)

    def set_column_shown(self, col: int, shown: bool) -> None:
        from PySide6.QtCore import QSettings
        hidden = self._hidden_columns()
        (hidden.discard if shown else hidden.add)(col)
        QSettings().setValue("browser/model_hidden_columns",
                             ",".join(str(c) for c in sorted(hidden)) or ",")
        self._apply_column_choice()

    def _on_header_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        menu = QMenu(self)
        hidden = self._hidden_columns()
        for col, label, _shown in OPTIONAL_COLUMNS:
            act = menu.addAction(tr(label), lambda c=col, on=col in hidden:
                                 self.set_column_shown(c, on))
            act.setCheckable(True)
            act.setChecked(col not in hidden)
        menu.exec(self.tree.header().mapToGlobal(pos))

    # ---- Several rows at once --------------------------------------------
    def assign_layer(self, groups, layer: str) -> None:
        """Put the rows on ``layer`` (made if new) — one undo step."""
        from core.history import AssignLayerCommand
        groups = [g for g in groups if g is not None]
        if not groups or not layer:
            return
        self._window.viewport.history.execute(
            AssignLayerCommand(groups, layer))
        self._window.viewport.update()
        self.refresh()

    def _ask_new_layer(self, groups) -> None:
        from views import prompts
        name, ok = prompts.get_text(self, tr("New layer"),
                                    tr("Layer name:"))
        if ok and name.strip():
            self.assign_layer(groups, name.strip())

    def paint_groups(self, groups, material=None, clear=False) -> None:
        """Paint the rows as a whole with ``material`` (the Paint tool's
        current one by default), or take their paint off — the same as
        painting a group from outside it; one undo step."""
        from core.history import (CompoundCommand, SetFaceMaterialTagCommand,
                                  SetGroupMaterialCommand)
        groups = [g for g in groups if g is not None]
        if not groups:
            return
        if clear:
            cmds = [SetGroupMaterialCommand(g, None) for g in groups]
        else:
            from tools.paint import PaintTool
            if material is None:
                if PaintTool.current_is_default:
                    cmds = [SetGroupMaterialCommand(g, None) for g in groups]
                else:
                    mat = PaintTool.current_material
                    material = PaintTool._current_as_material()
                    cmds = [SetFaceMaterialTagCommand(
                        [], mat.name if mat is not None else None, mat)]
                    cmds += [SetGroupMaterialCommand(g, material)
                             for g in groups]
            else:
                cmds = [SetGroupMaterialCommand(g, material) for g in groups]
        self._window.viewport.history.execute(CompoundCommand(cmds))
        self._window.viewport.update()
        self.refresh()

    def _batch_menu(self, menu, targets) -> None:
        layers = menu.addMenu(tr("Layer"))
        current = {outliner.layer_name(g) for g in targets}
        for ly in self._scene().layers:
            act = layers.addAction(ly.name, lambda n=ly.name:
                                   self.assign_layer(targets, n))
            act.setCheckable(True)
            act.setChecked(current == {ly.name})
        layers.addSeparator()
        from PySide6.QtCore import QTimer
        layers.addAction(tr("New layer…"), lambda: QTimer.singleShot(
            0, lambda: self._ask_new_layer(targets)))
        menu.addAction(tr("Paint with the active material"),
                       lambda: self.paint_groups(targets))
        if any(getattr(g, "material", None) for g in targets):
            menu.addAction(tr("Remove paint"),
                           lambda: self.paint_groups(targets, clear=True))

    # ---- A plan of a group -------------------------------------------------
    def create_plan(self, group, cut_height: float, sheet: bool = True,
                    scale: float = 100.0, open_sheet: bool = False):
        """A floor plan of ``group``: a horizontal cut ``cut_height`` above
        its base (made the active cut), a scene looking straight down on it
        in parallel projection, and — with ``sheet`` — a new sheet with
        that scene at 1:``scale``. One undo step. Returns the scene, or
        ``None`` when the group holds no geometry."""
        import math
        from PySide6.QtGui import QVector3D
        from core.camera import OrbitCamera
        from core.section import SectionPlane as _Plane
        from core.section import next_symbol
        scene = self._scene()
        bounds = outliner.world_bounds(scene.groups, group)
        if bounds is None:
            self._window.viewport.flash_status(
                tr("«{name}» holds no geometry to make a plan of",
                   name=group.name), 3500)
            return None
        (x0, y0, z0), (x1, y1, z1) = bounds
        z = z0 + float(cut_height)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        title = outliner.unique_name(
            tr("Plan {name}", name=group.name),
            [v.name for v in scene.saved_views])
        plane = _Plane(QVector3D(cx, cy, z), QVector3D(0, 0, 1),
                       name=title, symbol=next_symbol(scene.section_planes))
        cam = OrbitCamera()
        cam.target = QVector3D(cx, cy, z)
        cam.set_view("top")
        cam.perspective = False
        span = max(x1 - x0, y1 - y0, 1.0)
        cam.distance = span * 1.2 / (2 * math.tan(math.radians(
            cam.fov_deg) / 2))
        view = self._place_view(title, cam, plane, True, sheet, scale,
                                open_sheet)
        if z > z1 or z < z0:
            self._window.viewport.flash_status(tr(
                "The cut is outside «{name}»: the plan shows it whole",
                name=group.name), 4000)
        return view

    def _place_view(self, title, cam, plane, add_plane, sheet, scale,
                    open_sheet):
        """The part a plan of a group and a view of a cut share: the scene
        from ``cam`` cut by ``plane``, a sheet with it if asked — one undo
        step — and then the way to it: the sheet opened, or Sheets 2D with
        the scene marked, and the status bar saying what was made."""
        from core.composition import Composicion
        from core.history import CreatePlanCommand
        from core.saved_views import SavedView
        scene = self._scene()
        view = SavedView.capture(title, scene, cam)
        view.section = {"active": plane.uid, "planes_shown": False,
                        "cuts_shown": True}
        page = None
        if sheet:
            page = Composicion(name=outliner.unique_name(
                title, [c.name for c in scene.compositions]), paper="A3")
            frame = page.default_frame()
            frame.view_key = f"scene:{title}"
            frame.scale_n = float(scale)
            frame.show_title = True
            page.frames.append(frame)
        self._window.viewport.end_group_edit()
        self._window.viewport.history.execute(
            CreatePlanCommand(plane, view, page, add_plane=add_plane))
        self._window.tray.scenes.refresh()
        self._window._refresh_sheet_tabs()
        self._window.viewport.update()
        self.refresh()
        what = (tr("«{name}»: a scene and a sheet — in the composer",
                   name=title) if page is not None
                else tr("«{name}»: a scene — drag it onto a sheet in the "
                        "composer", name=title))
        self._window.viewport.flash_status(what, 6000)
        if page is not None and open_sheet:
            self._window._show_sheet(
                self._scene().compositions.index(page))
        composer = getattr(self._window, "_composer", None)
        if composer is not None:
            composer.views_panel.show_scene_row(title)
        return view

    def create_cut_view(self, plane, sheet: bool = True,
                        scale: float = 50.0, open_sheet: bool = False):
        """A view of an existing section plane: looking at the cut face on
        (from the side the plane takes away, towards what stays), in
        parallel projection, the plane made the active cut — a section for
        a vertical plane, a plan for a horizontal one. With ``sheet``, on a
        new sheet at 1:``scale``. One undo step; returns the scene."""
        import math
        from PySide6.QtGui import QVector3D
        from core.camera import OrbitCamera
        scene = self._scene()
        lo, hi = scene.bounds()
        n = QVector3D(plane.normal).normalized()
        if lo is None:
            centre, span = QVector3D(plane.point), 10.0
        else:
            centre = (lo + hi) * 0.5
            size = hi - lo
            span = max(size.x(), size.y(), size.z(), 1.0)
        # The target on the plane, facing the model's middle.
        target = centre - n * QVector3D.dotProduct(centre - plane.point, n)
        cam = OrbitCamera()
        cam.target = target
        cam.yaw = math.atan2(n.y(), n.x())
        cam.pitch = math.asin(max(-1.0, min(1.0, n.z())))
        cam.perspective = False
        cam.distance = span * 1.2 / (2 * math.tan(math.radians(
            cam.fov_deg) / 2))
        base = plane.name or tr("Section {symbol}", symbol=plane.symbol)
        title = outliner.unique_name(base, [v.name for v in scene.saved_views])
        return self._place_view(title, cam, plane, False, sheet, scale,
                                open_sheet)

    def ask_cut_view(self, plane) -> None:
        """The dialog for a view of a cut: a sheet or not, its scale, and
        whether to open it."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QFormLayout)
        from core.composition import format_scale, parse_scale
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("View of the cut {name}",
                              name=outliner.section_label(plane)))
        form = QFormLayout(dlg)
        on_sheet = QCheckBox(tr("Also place it on a new sheet"))
        on_sheet.setChecked(True)
        form.addRow("", on_sheet)
        scale = QLineEdit(format_scale(50.0))
        form.addRow(tr("Scale:"), scale)
        open_it = QCheckBox(tr("Open the sheet when done"))
        open_it.setChecked(True)
        form.addRow("", open_it)
        on_sheet.toggled.connect(scale.setEnabled)
        on_sheet.toggled.connect(open_it.setEnabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._cut_view_dialog = dlg         # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return
        self.create_cut_view(plane, on_sheet.isChecked(),
                             parse_scale(scale.text(), 50.0),
                             open_sheet=open_it.isChecked())

    def ask_plan(self, group) -> None:
        """The dialog: cut height above the group's base, a sheet or not,
        and its scale."""
        from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox,
                                       QFormLayout)
        from core.composition import format_scale, parse_scale
        from core.units import fmt_len
        from views.viewport import _parse_length_field
        dlg = QDialog(self)
        dlg.setWindowTitle(tr("Plan of {name}", name=group.name))
        form = QFormLayout(dlg)
        height = QLineEdit(fmt_len(1.2))
        height.setToolTip(tr("Measured up from the lowest point of the "
                             "group — 1.20 m cuts through the windows"))
        form.addRow(tr("Cut height:"), height)
        on_sheet = QCheckBox(tr("Also place it on a new sheet"))
        on_sheet.setChecked(True)
        form.addRow("", on_sheet)
        scale = QLineEdit(format_scale(100.0))
        form.addRow(tr("Scale:"), scale)
        open_it = QCheckBox(tr("Open the sheet when done"))
        open_it.setChecked(True)
        form.addRow("", open_it)
        on_sheet.toggled.connect(scale.setEnabled)
        on_sheet.toggled.connect(open_it.setEnabled)
        buttons = QDialogButtonBox(
            QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.accepted.connect(dlg.accept)
        buttons.rejected.connect(dlg.reject)
        form.addRow(buttons)
        self._plan_dialog = dlg             # reachable from the tests
        if dlg.exec() != QDialog.Accepted:
            return
        cut = _parse_length_field(height.text() or "")
        if cut is None:
            self._window.viewport.flash_status(
                tr("Not a length: {text}", text=height.text()), 3000)
            return
        self.create_plan(group, cut, on_sheet.isChecked(),
                         parse_scale(scale.text(), 100.0),
                         open_sheet=open_it.isChecked())

    def _isolate_targets(self) -> list:
        from core.group import Group
        picked = self._selected_groups()
        if not picked:
            picked = [g for g in self._scene().selection
                      if isinstance(g, Group)]
        return picked

    def isolate(self) -> None:
        """Hide every group but the selected ones and those holding them —
        one undoable step; Show all groups (or undo) brings them back.
        Loose geometry, dimensions and texts stay (#272)."""
        from core.history import HideCommand
        keep = self._isolate_targets()
        if not keep:
            self._window.viewport.flash_status(tr(
                "Select the groups to keep in view first"), 3000)
            return
        hide = outliner.isolate_hides(self._scene().groups, keep)
        if hide:
            self._window.viewport.history.execute(HideCommand(hide,
                                                              hidden=True))
            self._window.viewport.update()
        self.refresh()

    def show_all(self) -> None:
        """Show every hidden group of the tree — one undoable step."""
        from core.history import HideCommand
        hidden = [g for g, _p, _d in outliner.walk(self._scene().groups)
                  if g.hidden]
        if hidden:
            self._window.viewport.history.execute(HideCommand(hidden,
                                                              hidden=False))
            self._window.viewport.update()
        self.refresh()

    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != COL_NAME:
            return
        from core.history import RenameGroupCommand
        group = self._group_of(item)
        if group is None:
            return
        name = item.text(COL_NAME).strip()
        if name and name != group.name:
            self._window.viewport.history.execute(
                RenameGroupCommand(group, name))
            self._window.viewport.update()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtCore import QTimer
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        group = self._group_of(item)
        menu = QMenu(self)
        plane = self._plane_of(item)
        if plane is not None:
            menu.addAction(tr("Rename… (F2)"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.rename_plane(plane)))
            menu.addAction(tr("Create view of this cut…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.ask_cut_view(plane)))
            menu.addSeparator()
            current = outliner.section_mode(plane)
            for mode in ("both", "cut", "frame", "off"):
                act = menu.addAction(tr(self._SECTION_MODE_TEXT[mode]),
                                     lambda m=mode: self.set_section_mode(
                                         plane, m))
                act.setCheckable(True)
                act.setChecked(mode == current)
            menu.addSeparator()
            self._fill_actions(menu)
            self._plane_fill_menu(menu, plane)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if item is not None and item is self._sec_root:
            scene = self._scene()
            for text, attr, key in (
                    (tr("Section Planes"), "show_section_planes", "planes"),
                    (tr("Section Cuts"), "show_section_cuts", "cuts")):
                on = bool(getattr(scene, attr, True))
                act = menu.addAction(text, lambda k=key, v=not on:
                                     self.set_section_globals(**{k: v}))
                act.setCheckable(True)
                act.setChecked(on)
            self._fill_actions(menu)
            menu.exec(self.tree.viewport().mapToGlobal(pos))
            return
        if group is not None:
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(
                item, COL_NAME))
            selected = self._selected_groups()
            targets = selected if group in selected else [group]
            menu.addAction(tr("Show") if group.hidden else tr("Hide"),
                           lambda: self.toggle_hidden(targets))
            menu.addAction(tr("Unlock") if getattr(group, "locked", False)
                           else tr("Lock"),
                           lambda: self.toggle_locked(targets))
            menu.addAction(tr("Open for editing"),
                           lambda: self.open_item(item))
            if outliner.path_to(self._scene().groups, group):
                menu.addAction(tr("Move out of the group (Shift+Tab)"),
                               lambda: self.outdent())
            menu.addSeparator()
            self._batch_menu(menu, targets)
            menu.addSeparator()
            menu.addAction(tr("Create plan of this group…"),
                           lambda: QTimer.singleShot(
                               0, lambda: self.ask_plan(group)))
        if self._scene().edit_group is not None:
            menu.addAction(tr("Close group"), self.step_out)
        if self._scene().selection:
            menu.addAction(tr("Zoom Selection"),
                           self._window._on_zoom_selection)
        menu.addSeparator()
        if group is not None or self._isolate_targets():
            menu.addAction(tr("Isolate"), self.isolate)
        menu.addAction(tr("Show all groups"), self.show_all)
        menu.addSeparator()
        menu.addAction(tr("Expand all"), self._expand_all)
        menu.addAction(tr("Collapse all"), self._collapse_all)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- Sheets 2D -----------------------------------------------------------------

class _SheetsTree(QTreeWidget):
    """The Sheets 2D tree: a scene dragged onto a sheet (or onto one of its
    views) is placed on it; Alt+↑/↓ move a sheet in the set; Supr deletes
    one."""

    def __init__(self, panel) -> None:
        super().__init__()
        self._panel = panel
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setDefaultDropAction(Qt.CopyAction)

    def mimeTypes(self):
        from views.composer import SCENE_MIME
        return [SCENE_MIME]

    def mimeData(self, items):
        """The dragged scenes, by name — what the page of the composer (and
        a sheet row here) takes."""
        from PySide6.QtCore import QMimeData
        from views.composer import SCENE_MIME
        names = [d[1].name for d in (it.data(0, Qt.UserRole) for it in items)
                 if d and d[0] == "scene"]
        data = QMimeData()
        data.setData(SCENE_MIME, "\n".join(names).encode("utf-8"))
        return data

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def dropEvent(self, ev) -> None:
        item = self.itemAt(ev.position().toPoint())
        ev.setDropAction(Qt.IgnoreAction)          # the model moves, not Qt
        ev.accept()
        sheet = self._panel.sheet_of(item)
        scenes = [d[1] for d in (it.data(0, Qt.UserRole)
                                 for it in self.selectedItems())
                  if d and d[0] == "scene"]
        if sheet is not None and scenes:
            for view in scenes:
                self._panel.place_scene(view, sheet)

    def event(self, ev) -> bool:
        from PySide6.QtCore import QEvent
        if (ev.type() == QEvent.ShortcutOverride
                and self.state() != QAbstractItemView.EditingState
                and self._panel.current_sheet() is not None
                and ((ev.key() in (Qt.Key_Up, Qt.Key_Down)
                      and ev.modifiers() & Qt.AltModifier)
                     or ev.key() == Qt.Key_Delete)):
            ev.accept()
            return True
        return super().event(ev)

    def keyPressEvent(self, ev) -> None:
        sheet = self._panel.current_sheet()
        if sheet is not None and self.state() != \
                QAbstractItemView.EditingState:
            if ev.key() in (Qt.Key_Up, Qt.Key_Down) and \
                    ev.modifiers() & Qt.AltModifier:
                self._panel.move_sheet(sheet,
                                       -1 if ev.key() == Qt.Key_Up else 1)
                return
            if ev.key() == Qt.Key_Delete:
                self._panel.delete_sheet(sheet)
                return
        super().keyPressEvent(ev)


class SheetsPanel(QWidget):
    """Saved scenes and sheets with their view frames (the Sheets 2D tab) —
    where views go onto sheets: drag a scene onto a sheet, make, order,
    duplicate, delete and print sheets, and see which scenes are on no
    sheet yet."""

    def __init__(self, window, composer=None) -> None:
        super().__init__()
        self._window = window
        #: The sheet composer this panel lives in (its «Views and sheets»
        #: dock): scenes then go onto the page open beside it, through the
        #: composer's own undo, and show a picture of themselves.
        self._composer_win = composer
        self._stale = False
        self._shape = None
        self._thumb_queue: list = []
        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 6, 6, 6)
        lay.setSpacing(4)
        self.tree = _SheetsTree(self)
        if composer is not None:
            from PySide6.QtCore import QSize
            self.tree.setIconSize(QSize(48, 32))
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([tr("Name"), tr("Details")])
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        head = self.tree.header()
        head.setStretchLastSection(True)
        head.setSectionResizeMode(0, QHeaderView.Interactive)
        head.resizeSection(0, 230)
        _remember_widths(head, "browser/sheet_columns", (0,))
        self.tree.setUniformRowHeights(True)
        self.tree.setAlternatingRowColors(True)
        self.tree.setToolTip(tr(
            "Drag a scene onto the page to place it where you drop it, or "
            "double-click it to place it in a free spot. Double-click a sheet "
            "to open it. F2 renames, Alt+↑/↓ moves a sheet, Delete removes "
            "it.") if composer is not None else tr(
            "Drag a scene onto a sheet to place it there. Double-click a "
            "scene to show it, a sheet or a view to open the sheet. F2 "
            "renames, Alt+↑/↓ moves a sheet, Delete removes it. Selecting a "
            "scene marks the views that show it."))
        self.tree.setEditTriggers(QAbstractItemView.EditKeyPressed)
        self.tree.itemDoubleClicked.connect(
            lambda item, _col: self.activate(item))
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.currentItemChanged.connect(
            lambda item, _prev: self._mark_related(item))
        self._updating = False
        self._related: list = []
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._on_context_menu)
        lay.addWidget(self.tree, 1)
        new_sheet = _tool_button(tr("New sheet"), tr(
            "Open the sheet composer on a new sheet"), self._new_sheet)
        new_sheet.setToolButtonStyle(Qt.ToolButtonTextOnly)
        export = _tool_button(tr("Export PDF…"), tr(
            "The selected sheets — or all of them — into one PDF"),
            lambda: self.export_pdf())
        export.setToolButtonStyle(Qt.ToolButtonTextOnly)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(new_sheet)
        row.addWidget(export)
        lay.addLayout(row)
        self.scenes_root = None
        self.sheets_root = None
        # The composer is another window and edits sheets without telling
        # the model: while this tab is on screen it checks, once a second,
        # whether what it lists changed (a fingerprint of a few names — it
        # costs nothing when nothing did).
        from PySide6.QtCore import QTimer
        self._poll = QTimer(self)
        self._poll.setInterval(1000)
        self._poll.timeout.connect(self.refresh)
        self.refresh()

    def _scene(self):
        return self._window.viewport.scene

    def on_scene_changed(self) -> None:
        if self.isVisible():
            self.refresh()
        else:
            self._stale = True
            self.sync_composer()        # the composer is another window

    def showEvent(self, ev) -> None:
        super().showEvent(ev)
        # Sheets change in the composer window, which does not touch the
        # model's version: looking at the tab is when to catch up.
        self.refresh()
        self._poll.start()

    def hideEvent(self, ev) -> None:
        self._poll.stop()
        super().hideEvent(ev)

    def refresh(self) -> None:
        self._stale = False
        if self.tree.state() == QAbstractItemView.EditingState:
            return                      # a rename in progress: leave it be
        scene = self._scene()
        shape = outliner.sheets_shape(scene)
        if shape == self._shape:
            return
        self._shape = shape
        self._updating = True
        try:
            self._fill(scene)
        finally:
            self._updating = False
        self.sync_composer()
        if self._composer_win is not None:
            self._queue_thumbnails()

    def _queue_thumbnails(self) -> None:
        """Pictures of the scenes, one at a time from the event loop — a
        render each, so the panel shows at once and fills in. Queued by
        NAME: a render can refresh the panel, and the row it was for is
        then another one."""
        from PySide6.QtCore import QTimer
        root = self.scenes_root
        self._thumb_queue = []
        for i in range(root.childCount() if root is not None else 0):
            data = root.child(i).data(0, Qt.UserRole)
            if data:
                self._thumb_queue.append(data[1].name)
        QTimer.singleShot(0, self._next_thumbnail)

    def _scene_row(self, name):
        root = self.scenes_root
        for i in range(root.childCount() if root is not None else 0):
            item = root.child(i)
            data = item.data(0, Qt.UserRole)
            if data and data[1].name == name:
                return item
        return None

    def _next_thumbnail(self) -> None:
        from shiboken6 import isValid
        if not self._thumb_queue or not isValid(self):
            return
        name = self._thumb_queue.pop(0)
        icon = self._composer_win.scene_thumbnail(name)
        item = self._scene_row(name)          # after the render: the live row
        if icon is not None and item is not None and isValid(item):
            # A new icon is an item change to Qt, not a rename: unguarded,
            # it went through _on_item_changed, touched the document and
            # rebuilt the list — which queued the pictures again: the
            # scenes flickered, and the file read as modified.
            self._updating = True
            try:
                item.setIcon(0, icon)
            finally:
                self._updating = False
        if self._thumb_queue:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(20, self._next_thumbnail)

    def refresh_thumbnails(self) -> None:
        if self._composer_win is None:
            return
        self._composer_win.forget_thumbnails()
        self._queue_thumbnails()

    def sync_composer(self) -> None:
        """Bring an open composer up to date with the document's sheets
        and scenes. It reloads them when it opens; a sheet or a scene made
        while it is already open (Create plan, the browser) — or one undone
        under it — did not reach it: the new sheet missed from its list,
        or the window kept showing a sheet that no longer existed."""
        comp_win = getattr(self._window, "_composer", None)
        if comp_win is None:
            return
        # Only when the sheets or scenes changed: reloading the composer's
        # list refreshes the sheet strip, which calls back here.
        shape = outliner.sheets_shape(self._scene())
        if shape == getattr(self, "_synced_shape", None):
            return
        self._synced_shape = shape
        comps = self._scene().compositions
        if comp_win.comp not in comps:
            if not comps:
                return                      # it makes its own on showing
            from core.composition import ComposerHistory
            comp_win.comp = comps[0]
            comp_win.history = ComposerHistory(
                on_change=comp_win._on_history_change)
            comp_win._rebuild_canvas()
        comp_win._reload_comp_combo()
        reload = getattr(comp_win, "_reload_view_sources", None)
        if reload is not None:
            reload()
        if comp_win.isVisible():
            # A view placed or taken away from here, on the open sheet.
            comp_win._rebuild_canvas()
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, comp_win._auto_render_stale)

    def show_scene_row(self, name: str) -> None:
        """Bring the scene called ``name`` into view, current — which also
        marks the sheet views that show it."""
        self.refresh()
        root = self.scenes_root
        for i in range(root.childCount() if root is not None else 0):
            item = root.child(i)
            data = item.data(0, Qt.UserRole)
            if data and data[1].name == name:
                root.setExpanded(True)
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _fill(self, scene) -> None:
        current = self.tree.currentItem()
        current_key = self._key(current) if current is not None else None
        self._related = []
        from core.composition import format_scale
        from views.composer import frame_view_name
        expanded = {self._key(it) for it in self._all_items()
                    if it.isExpanded()}
        first = self.tree.topLevelItemCount() == 0
        used = outliner.scene_usage(scene)
        self.tree.clear()
        views = list(getattr(scene, "saved_views", None) or ())
        comps = list(getattr(scene, "compositions", None) or ())
        unplaced = len(outliner.unplaced_scenes(scene))
        self.scenes_root = QTreeWidgetItem(
            [tr("Scenes"), tr("{n} saved · {k} on no sheet", n=len(views),
                              k=unplaced) if unplaced
             else tr("{n} saved", n=len(views))])
        self.scenes_root.setIcon(0, node_icon("folder"))
        self.sheets_root = QTreeWidgetItem(
            [tr("Sheets"), tr("{n} sheets", n=len(comps))])
        self.sheets_root.setIcon(0, node_icon("folder"))
        for root in (self.scenes_root, self.sheets_root):
            font = QFont(root.font(0))
            font.setBold(True)
            root.setFont(0, font)
            root.setFlags(Qt.ItemIsEnabled)
            self.tree.addTopLevelItem(root)
        for view in views:
            on = used.get(view.name, [])
            item = QTreeWidgetItem([view.name, tr("On {sheets}",
                                                  sheets=", ".join(on))
                                    if on else tr("Not on a sheet")])
            item.setIcon(0, node_icon("scene"))
            item.setData(0, Qt.UserRole, ("scene", view))
            item.setFlags((item.flags() | Qt.ItemIsEditable
                           | Qt.ItemIsDragEnabled) & ~Qt.ItemIsDropEnabled)
            if not on:
                font = QFont(item.font(0))
                font.setItalic(True)
                item.setFont(0, font)
            self.scenes_root.addChild(item)
        for index, comp in enumerate(comps):
            orient = tr("landscape") if comp.landscape else tr("portrait")
            sheet = QTreeWidgetItem([comp.name, f"{comp.paper} · {orient}"])
            sheet.setIcon(0, node_icon("sheet"))
            sheet.setData(0, Qt.UserRole, ("sheet", index))
            sheet.setFlags((sheet.flags() | Qt.ItemIsEditable
                            | Qt.ItemIsDropEnabled) & ~Qt.ItemIsDragEnabled)
            self.sheets_root.addChild(sheet)
            for frame in comp.frames:
                if frame.view_key == "__current__":
                    name = tr("Current view")
                else:
                    name = frame_view_name(frame)
                item = QTreeWidgetItem(
                    [f"{name} · {format_scale(frame.scale_n)}", ""])
                item.setData(0, Qt.UserRole, ("frame", index, frame))
                item.setFlags((item.flags() | Qt.ItemIsDropEnabled)
                              & ~Qt.ItemIsDragEnabled)
                if outliner.is_orphan(scene, frame):
                    item.setIcon(0, node_icon("warning"))
                    item.setText(1, tr("Scene missing"))
                    item.setToolTip(0, tr(
                        "This view shows the scene «{name}», which the "
                        "model no longer has. The frame keeps its place on "
                        "the sheet; pick another view for it in the "
                        "composer.", name=outliner.frame_scene(frame)))
                else:
                    item.setIcon(0, node_icon("frame"))
                    item.setText(1, tr("Scene") if outliner.frame_scene(
                        frame) else tr("Standard view")
                        if frame.view_key.startswith("std:")
                        else tr("Live camera"))
                sheet.addChild(item)
        for it in self._all_items():
            if first or self._key(it) in expanded or it in (
                    self.scenes_root, self.sheets_root):
                it.setExpanded(True)
            if current_key is not None and self._key(it) == current_key:
                self.tree.setCurrentItem(it)

    def _all_items(self):
        stack = [self.tree.topLevelItem(i)
                 for i in range(self.tree.topLevelItemCount())]
        while stack:
            item = stack.pop()
            yield item
            stack.extend(item.child(i) for i in range(item.childCount()))

    @staticmethod
    def _key(item):
        data = item.data(0, Qt.UserRole)
        if data is None:
            return ("root", item.text(0))
        return (data[0], item.text(0))

    # ---- Scenes ↔ views ---------------------------------------------------
    def _mark_related(self, item) -> None:
        """Mark what the current row is linked to: a scene → the views that
        show it, on every sheet; a view → its scene. The link is the one
        a sheet keeps — the scene's name — read both ways."""
        from PySide6.QtGui import QBrush
        for it in self._related:
            for col in (0, 1):
                it.setBackground(col, QBrush())
            it.setData(0, Qt.UserRole + 1, False)
        self._related = []
        data = item.data(0, Qt.UserRole) if item is not None else None
        if not data:
            return
        if data[0] == "scene":
            name = data[1].name
            wanted = lambda d: d[0] == "frame" and \
                outliner.frame_scene(d[2]) == name
        elif data[0] == "frame" and outliner.frame_scene(data[2]):
            name = outliner.frame_scene(data[2])
            wanted = lambda d: d[0] == "scene" and d[1].name == name
        else:
            return
        tint = QColor(_accent())
        tint.setAlpha(60)
        for it in self._all_items():
            d = it.data(0, Qt.UserRole)
            if d and wanted(d):
                for col in (0, 1):
                    it.setBackground(col, tint)
                it.setData(0, Qt.UserRole + 1, True)
                self._related.append(it)
                self._reveal(it)

    @staticmethod
    def _reveal(item) -> None:
        parent = item.parent()
        while parent is not None:
            parent.setExpanded(True)
            parent = parent.parent()

    def related(self) -> list:
        """The rows marked as linked to the current one."""
        return list(self._related)

    # ---- Rename --------------------------------------------------------
    def _on_item_changed(self, item, column) -> None:
        if self._updating or column != 0:
            return
        data = item.data(0, Qt.UserRole)
        if not data or data[0] not in ("scene", "sheet"):
            return
        text = item.text(0).strip()
        comps = self._scene().compositions
        current = (data[1].name if data[0] == "scene"
                   else comps[data[1]].name if 0 <= data[1] < len(comps)
                   else None)
        if text == current:
            return                      # not a rename: nothing to do
        if data[0] == "scene":
            self.rename_scene(data[1], text)
        else:
            self.rename_sheet(data[1], text)

    def _touch(self) -> None:
        self._scene().version += 1          # a document change: unsaved
        self._window.viewport.update()
        self._shape = None
        from PySide6.QtCore import QTimer
        QTimer.singleShot(0, self.refresh)  # not under the editor's signal

    def rename_scene(self, view, name: str) -> bool:
        """Rename a scene and carry the sheet views that show it along."""
        if not outliner.rename_scene(self._scene(), view, name):
            if name and name != view.name:
                self._window.viewport.flash_status(tr(
                    "Another scene is already called «{name}»", name=name),
                    3500)
            self._touch()
            return False
        self._window.tray.scenes.refresh()
        composer = getattr(self._window, "_composer", None)
        reload = getattr(composer, "_reload_view_sources", None)
        if reload is not None:
            reload()
        self._touch()
        return True

    def rename_sheet(self, index: int, name: str) -> bool:
        comps = self._scene().compositions
        if not name or not 0 <= index < len(comps) \
                or comps[index].name == name:
            self._touch()
            return False
        comps[index].name = name
        composer = getattr(self._window, "_composer", None)
        if getattr(composer, "comp_combo", None) is not None:
            composer._reload_comp_combo()
        else:
            self._window._refresh_sheet_tabs()
        self._touch()
        return True

    # ---- Working with sheets -----------------------------------------------
    def sheet_of(self, item):
        """The sheet a row is (or is in), or ``None``."""
        data = item.data(0, Qt.UserRole) if item is not None else None
        comps = self._scene().compositions
        if data and data[0] in ("sheet", "frame") and \
                0 <= data[1] < len(comps):
            return comps[data[1]]
        return None

    def current_sheet(self):
        item = self.tree.currentItem()
        data = item.data(0, Qt.UserRole) if item is not None else None
        return self.sheet_of(item) if data and data[0] == "sheet" else None

    def _selected_sheets(self) -> list:
        out = []
        for it in self.tree.selectedItems():
            sheet = self.sheet_of(it)
            if sheet is not None and sheet not in out:
                out.append(sheet)
        return out

    def place_scene(self, view, sheet=None, scale: float = 100.0):
        """Place scene ``view`` on ``sheet`` — on a new sheet named after
        it when ``None`` — in a free spot of the page, at 1:``scale``. One
        undo step; returns the new frame."""
        from core.composition import Composicion, MarcoVista
        from core.history import (AddSheetCommand, CompoundCommand,
                                  PlaceViewCommand)
        scene = self._scene()
        comp_win = self._composer_win
        if comp_win is not None and sheet is not None:
            # Beside the page: open that sheet and put the view in a free
            # place of it, as one step of the composer's own undo.
            comps = scene.compositions
            if comp_win.comp is not sheet and sheet in comps:
                comp_win.show_sheet(comps.index(sheet))
            return comp_win.place_scene_at(view.name)
        cmds = []
        if sheet is None:
            sheet = Composicion(name=outliner.unique_name(
                view.name, [c.name for c in scene.compositions]),
                paper="A3")
            cmds.append(AddSheetCommand(sheet))
        pw, ph = sheet.page_size_mm()
        m = float(getattr(sheet, "margin_mm", 10.0) or 0.0)
        w_mm = max(60.0, (pw - 2 * m) / 2 - 15)
        h_mm = max(45.0, (ph - 2 * m) / 2 - 15)
        # A quarter of the page where there is room; smaller where there is
        # less; over the others, a step aside, only on a full page.
        spot = None
        for k in (1.0, 0.75, 0.5, 0.35):
            spot = outliner.free_slot(sheet, w_mm * k, h_mm * k,
                                      fallback=False)
            if spot is not None:
                w_mm, h_mm = w_mm * k, h_mm * k
                break
        x, y = spot if spot is not None else outliner.free_slot(
            sheet, w_mm, h_mm)
        frame = MarcoVista(x_mm=x, y_mm=y, w_mm=w_mm, h_mm=h_mm,
                           view_key=f"scene:{view.name}",
                           scale_n=float(scale), show_title=True)
        cmds.append(PlaceViewCommand(sheet, frame))
        self._window.viewport.history.execute(
            CompoundCommand(cmds) if len(cmds) > 1 else cmds[0])
        self._window._refresh_sheet_tabs()
        self._window.viewport.flash_status(tr(
            "«{scene}» placed on «{sheet}»", scene=view.name,
            sheet=sheet.name), 4000)
        self.refresh()
        return frame

    def move_sheet(self, sheet, step: int) -> None:
        """Up or down the set — one undo step."""
        from core.history import MoveSheetCommand
        comps = self._scene().compositions
        i = comps.index(sheet) + step
        if not 0 <= i < len(comps):
            return
        self._window.viewport.history.execute(MoveSheetCommand(sheet, i))
        self._window._refresh_sheet_tabs()
        self.refresh()
        self._select_sheet(sheet)

    def _select_sheet(self, sheet) -> None:
        comps = self._scene().compositions
        if sheet not in comps or self.sheets_root is None:
            return
        item = self.sheets_root.child(comps.index(sheet))
        if item is not None:
            self.tree.setCurrentItem(item)

    def duplicate_sheet(self, sheet) -> None:
        comp_win = self._window._ensure_composer()
        comp_win.duplicate_sheet(self._scene().compositions.index(sheet))
        self._window._refresh_sheet_tabs()
        self.refresh()

    def delete_sheet(self, sheet) -> None:
        """Through the composer: it asks first and keeps one sheet."""
        comp_win = self._window._ensure_composer()
        if comp_win.delete_sheet(self._scene().compositions.index(sheet),
                                 self):
            self._window._refresh_sheet_tabs()
            self.refresh()

    def export_pdf(self, sheets=None, path=None) -> None:
        """The selected sheets (all, when none is selected) into one PDF,
        in the set's order — the composer's own atlas export."""
        sheets = sheets if sheets is not None else self._selected_sheets()
        if path is None:
            from views.filedialogs import file_dialogs
            path, _ = file_dialogs.getSaveFileName(
                self, tr("Export PDF…"), "laminas.pdf", "PDF (*.pdf)")
        if not path:
            return
        comp_win = self._window._ensure_composer()
        troubled = comp_win.export_all_pdf(path, sheets or None)
        n = len(sheets) if sheets else len(self._scene().compositions)
        self._window.viewport.flash_status(
            tr("Exported {n} sheets to {name}", n=n, name=path)
            if not troubled else
            tr("Exported {name} — but a view would not render on {sheets}",
               name=path, sheets=", ".join(troubled)), 6000)

    def _place_menu(self, menu, view) -> None:
        sub = menu.addMenu(tr("Place on sheet"))
        for comp in self._scene().compositions:
            sub.addAction(comp.name, lambda c=comp: self.place_scene(view, c))
        sub.addSeparator()
        sub.addAction(tr("On a new sheet"),
                      lambda: self.place_scene(view, None))

    def activate(self, item) -> None:
        """Double-click: a scene shows (in the composer: is placed in a
        free place of the open sheet), a sheet (or one of its views) opens
        in the composer."""
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        if data[0] == "scene" and self._composer_win is not None:
            self._composer_win.place_scene_at(data[1].name)
        elif data[0] == "scene":
            self._show_scene(data[1])
        else:
            self._window._show_sheet(data[1])

    def _show_scene(self, view) -> None:
        """Through the Scenes panel, so a scene shown from here does all
        a scene shown there does (style menu, selection, layers)."""
        scenes = self._window.tray.scenes
        for i in range(scenes.list.count()):
            row = scenes.list.item(i)
            if row.data(Qt.UserRole) is view:
                scenes._on_activate(row)
                return

    def _new_sheet(self) -> None:
        self._window._show_new_sheet()
        self.refresh()

    def _on_context_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu
        item = self.tree.itemAt(pos)
        data = item.data(0, Qt.UserRole) if item is not None else None
        menu = QMenu(self)
        if data and data[0] == "scene":
            menu.addAction(tr("Show scene"), lambda: self.activate(item))
            menu.addAction(tr("Rename…"), lambda: self.tree.editItem(item, 0))
            self._place_menu(menu, data[1])
        elif data:
            menu.addAction(tr("Open sheet"), lambda: self.activate(item))
            if data[0] == "sheet":
                sheet = self.sheet_of(item)
                menu.addAction(tr("Rename…"),
                               lambda: self.tree.editItem(item, 0))
                menu.addAction(tr("Duplicate sheet"),
                               lambda: self.duplicate_sheet(sheet))
                menu.addAction(tr("Delete sheet"),
                               lambda: self.delete_sheet(sheet))
                menu.addSeparator()
                menu.addAction(tr("Move up (Alt+↑)"),
                               lambda: self.move_sheet(sheet, -1))
                menu.addAction(tr("Move down (Alt+↓)"),
                               lambda: self.move_sheet(sheet, 1))
                menu.addSeparator()
                views = list(self._scene().saved_views)
                if views:
                    sub = menu.addMenu(tr("Place a scene here"))
                    free = outliner.unplaced_scenes(self._scene())
                    for v in free + [v for v in views if v not in free]:
                        sub.addAction(v.name, lambda vv=v, s=sheet:
                                      self.place_scene(vv, s))
                chosen = self._selected_sheets() or [sheet]
                menu.addAction(tr("Export to PDF…") if len(chosen) == 1
                               else tr("Export {n} sheets to PDF…",
                                       n=len(chosen)),
                               lambda: self.export_pdf(chosen))
            if data[0] == "frame":
                name = outliner.frame_scene(data[2])
                view = next((v for v in self._scene().saved_views
                             if v.name == name), None)
                if view is not None:
                    menu.addAction(tr("Show scene"),
                                   lambda: self._show_scene(view))
        menu.addAction(tr("New sheet"), self._new_sheet)
        if self._composer_win is not None:
            menu.addAction(tr("Refresh previews"), self.refresh_thumbnails)
        menu.exec(self.tree.viewport().mapToGlobal(pos))


# ---- The dock ------------------------------------------------------------------

class ProjectBrowser(QDockWidget):
    """Sidebar tab **Browser**: the model's tree. The sheets have
    their own panel in the sheet composer, beside the page they go on
    («Views and sheets», :class:`SheetsPanel`)."""

    def __init__(self, window) -> None:
        super().__init__(tr("Browser"), window)
        self.setObjectName("tray_project_browser")
        self.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetMovable
                         | QDockWidget.DockWidgetClosable)
        self._window = window
        self.outliner = OutlinerPanel(window)
        self.setWidget(self.outliner)
        self.setMinimumWidth(240)

    def on_scene_changed(self) -> None:
        self.outliner.on_scene_changed()
        composer = getattr(self._window, "_composer", None)
        if composer is not None:
            composer.views_panel.on_scene_changed()
