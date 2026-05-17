from __future__ import annotations
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal, QPoint
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QBrush
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QMenu, QPushButton,
    QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget,
)

from gingerconnect.models.connection import Connection


def _status_icon(active: bool) -> QIcon:
    px = QPixmap(14, 14)
    px.fill(Qt.GlobalColor.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor("#a6e3a1") if active else QColor("#45475a")
    p.setBrush(QBrush(color))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(2, 2, 10, 10)
    p.end()
    return QIcon(px)


_ROLE_CONNECTION = Qt.ItemDataRole.UserRole
_ROLE_GROUP = Qt.ItemDataRole.UserRole + 1


class Sidebar(QWidget):
    connection_activated = pyqtSignal(object)
    add_clicked = pyqtSignal()
    add_group_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    context_menu_requested = pyqtSignal(object, QPoint)       # connection, global pos
    group_context_menu_requested = pyqtSignal(str, QPoint)    # group name, global pos

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(220)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Title ──────────────────────────────────────────────────────────
        title_bar = QWidget()
        title_bar.setFixedHeight(40)
        title_bar.setStyleSheet("background:#181825;border-bottom:1px solid #313244;")
        tl = QHBoxLayout(title_bar)
        tl.setContentsMargins(10, 0, 10, 0)
        lbl = QLabel("GingerConnect")
        lbl.setStyleSheet("color:#89b4fa;font-weight:bold;font-size:14px;background:transparent;")
        tl.addWidget(lbl)
        root.addWidget(title_bar)

        # ── Search ─────────────────────────────────────────────────────────
        search_wrap = QWidget()
        search_wrap.setStyleSheet("background:#181825;")
        sl = QHBoxLayout(search_wrap)
        sl.setContentsMargins(8, 6, 8, 6)
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.setClearButtonEnabled(True)
        self._search.textChanged.connect(self._filter)
        sl.addWidget(self._search)
        root.addWidget(search_wrap)

        # ── Tree ───────────────────────────────────────────────────────────
        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        self._tree.setIndentation(16)
        self._tree.setAnimated(True)
        self._tree.setRootIsDecorated(False)   # we draw ▼/▶ in text
        self._tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._tree.customContextMenuRequested.connect(self._on_context_menu)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_double_click)
        root.addWidget(self._tree)

        # ── Bottom buttons ─────────────────────────────────────────────────
        btn_bar = QWidget()
        btn_bar.setStyleSheet("background:#181825;border-top:1px solid #313244;")
        btn_bar.setFixedHeight(36)
        bl = QHBoxLayout(btn_bar)
        bl.setContentsMargins(8, 4, 8, 4)
        bl.setSpacing(4)

        add_btn = QPushButton("+")
        add_btn.setObjectName("FlatButton")
        add_btn.setToolTip("Add connection or group")
        add_btn.setFixedSize(28, 28)
        add_btn.clicked.connect(self._show_add_menu)
        bl.addWidget(add_btn)

        bl.addStretch()

        settings_btn = QPushButton("⚙")
        settings_btn.setObjectName("FlatButton")
        settings_btn.setToolTip("Settings")
        settings_btn.setFixedSize(28, 28)
        settings_btn.clicked.connect(self.settings_clicked)
        bl.addWidget(settings_btn)

        root.addWidget(btn_bar)

        self._connections: list[Connection] = []
        self._all_groups: list[str] = []
        self._expanded_groups: dict[str, bool] = {}

    # ── public API ─────────────────────────────────────────────────────────

    def load_connections(
        self,
        connections: list[Connection],
        active_names: set[str],
        groups: Optional[list[str]] = None,
    ) -> None:
        self._connections = list(connections)
        self._all_groups = list(groups) if groups else []
        self._rebuild(active_names)

    def refresh_status(self, active_names: set[str]) -> None:
        def _refresh(item: QTreeWidgetItem) -> None:
            conn = self._item_connection(item)
            if conn is not None:
                item.setIcon(0, _status_icon(conn.name in active_names))
            for i in range(item.childCount()):
                child = item.child(i)
                if child:
                    _refresh(child)

        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            child = root.child(i)
            if child:
                _refresh(child)

    # ── internal ───────────────────────────────────────────────────────────

    def _rebuild(self, active_names: set[str]) -> None:
        self._tree.clear()

        # Collect every node path that needs a tree item.
        # For a path like "CSSE/RDP" we also need "CSSE" to exist as a parent,
        # so we expand every path into its ancestor segments.
        all_paths: set[str] = set()
        for path in self._all_groups:
            parts = path.split("/")
            for i in range(len(parts)):
                all_paths.add("/".join(parts[: i + 1]))
        for conn in self._connections:
            path = conn.group or "Default"
            parts = path.split("/")
            for i in range(len(parts)):
                all_paths.add("/".join(parts[: i + 1]))

        # Build items sorted so that "CSSE" always precedes "CSSE/RDP"
        # ("/" ASCII 47 < any letter, so lexicographic order is correct).
        node_map: dict[str, QTreeWidgetItem] = {}
        for path in sorted(all_paths):
            label = path.rsplit("/", 1)[-1]
            is_expanded = self._expanded_groups.get(path, True)
            prefix = "▼" if is_expanded else "▶"
            item = QTreeWidgetItem([f"{prefix}  {label}"])
            item.setData(0, _ROLE_GROUP, path)
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            font = item.font(0)
            font.setBold(True)
            item.setFont(0, font)
            item.setForeground(0, QColor("#6c7086"))

            if "/" in path:
                parent_path = path.rsplit("/", 1)[0]
                node_map[parent_path].addChild(item)
            else:
                self._tree.addTopLevelItem(item)
            node_map[path] = item

        for conn in self._connections:
            path = conn.group or "Default"
            parent = node_map.get(path)
            if parent is None:
                continue
            ci = QTreeWidgetItem()
            ci.setText(0, conn.name or conn.target.host)
            ci.setIcon(0, _status_icon(conn.name in active_names))
            ci.setData(0, _ROLE_CONNECTION, conn)
            parent.addChild(ci)

        # Apply expansion state after all children are present
        for path, item in node_map.items():
            item.setExpanded(self._expanded_groups.get(path, True))

    def _filter(self, text: str) -> None:
        text = text.lower()

        def _filter_item(item: QTreeWidgetItem) -> bool:
            """Return True if item or any descendant should remain visible."""
            if self._item_connection(item) is not None:
                visible = not text or text in item.text(0).lower()
                item.setHidden(not visible)
                return visible
            # Group node: visible if any child is visible
            any_visible = False
            for i in range(item.childCount()):
                child = item.child(i)
                if child and _filter_item(child):
                    any_visible = True
            item.setHidden(bool(text) and not any_visible)
            return any_visible or not text

        root = self._tree.invisibleRootItem()
        for i in range(root.childCount()):
            child = root.child(i)
            if child:
                _filter_item(child)

    def _item_connection(self, item: QTreeWidgetItem) -> Optional[Connection]:
        data = item.data(0, _ROLE_CONNECTION)
        return data if isinstance(data, Connection) else None

    def _item_group(self, item: QTreeWidgetItem) -> Optional[str]:
        data = item.data(0, _ROLE_GROUP)
        return data if isinstance(data, str) else None

    def _toggle_group(self, item: QTreeWidgetItem) -> None:
        path = self._item_group(item)
        if path is None:
            return
        label = path.rsplit("/", 1)[-1]   # display only the last segment
        is_expanded = item.isExpanded()
        item.setExpanded(not is_expanded)
        arrow = "▶" if is_expanded else "▼"
        item.setText(0, f"{arrow}  {label}")
        self._expanded_groups[path] = not is_expanded

    def _on_item_clicked(self, item: QTreeWidgetItem, _col: int) -> None:
        if self._item_connection(item) is None:
            self._toggle_group(item)

    def _on_double_click(self, item: QTreeWidgetItem, _col: int) -> None:
        conn = self._item_connection(item)
        if conn:
            self.connection_activated.emit(conn)

    def _on_context_menu(self, pos: QPoint) -> None:
        item = self._tree.itemAt(pos)
        if item is None:
            return
        global_pos = self._tree.viewport().mapToGlobal(pos)
        conn = self._item_connection(item)
        if conn is not None:
            self.context_menu_requested.emit(conn, global_pos)
        else:
            grp = self._item_group(item)
            if grp is not None:
                self.group_context_menu_requested.emit(grp, global_pos)

    def _show_add_menu(self) -> None:
        btn = self.sender()
        menu = QMenu(self)
        conn_act = menu.addAction("Add Connection")
        group_act = menu.addAction("Add Group")
        if btn is not None:
            pos = btn.mapToGlobal(btn.rect().bottomLeft())  # type: ignore[attr-defined]
        else:
            pos = self.mapToGlobal(QPoint(0, self.height()))
        action = menu.exec(pos)
        if action == conn_act:
            self.add_clicked.emit()
        elif action == group_act:
            self.add_group_clicked.emit()
