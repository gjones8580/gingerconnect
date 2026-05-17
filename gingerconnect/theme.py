STYLESHEET = """
/* ── Base ─────────────────────────────────────────────────────────────── */
QMainWindow, QDialog, QWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: "Noto Sans", "Segoe UI", Ubuntu, sans-serif;
    font-size: 13px;
}

/* ── Sidebar panel ────────────────────────────────────────────────────── */
#Sidebar {
    background-color: #181825;
    border-right: 1px solid #313244;
}

/* ── Tree widget ──────────────────────────────────────────────────────── */
QTreeWidget {
    background-color: #181825;
    alternate-background-color: #181825;
    border: none;
    outline: none;
}

QTreeWidget::item {
    padding: 3px 4px;
    border-radius: 4px;
}

QTreeWidget::item:selected {
    background-color: #313244;
    color: #cdd6f4;
}

QTreeWidget::item:hover:!selected {
    background-color: #21213a;
}

QTreeWidget::branch {
    background-color: #181825;
    image: none;
}

/* ── Tab bar ──────────────────────────────────────────────────────────── */
QTabWidget::pane {
    background-color: #1e1e2e;
    border: none;
    border-top: 1px solid #313244;
}

QTabBar {
    background-color: #181825;
}

QTabBar::tab {
    background-color: #181825;
    color: #6c7086;
    padding: 6px 6px 6px 12px;
    border: none;
    border-bottom: 2px solid transparent;
    min-width: 100px;
}

QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
}

QTabBar::tab:hover:!selected {
    background-color: #24273a;
    color: #cdd6f4;
}

/* ── Tab close button (custom QPushButton set via setTabButton) ───────── */
QPushButton#TabCloseButton {
    background-color: transparent;
    border: none;
    color: #45475a;
    min-width: 16px;
    max-width: 16px;
    padding: 0;
    font-size: 11px;
    margin: 1px 4px 1px 2px;
}

QPushButton#TabCloseButton:hover {
    color: #f38ba8;
    background-color: rgba(243, 139, 168, 25);
    border-radius: 3px;
}

/* ── Line edit ────────────────────────────────────────────────────────── */
QLineEdit {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 8px;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}

QLineEdit:focus {
    border: 1px solid #89b4fa;
}

QLineEdit:disabled {
    color: #6c7086;
    background-color: #24273a;
}

/* ── Buttons ──────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 5px 14px;
    min-width: 60px;
}

QPushButton:hover {
    background-color: #45475a;
    border-color: #89b4fa;
}

QPushButton:pressed {
    background-color: #89b4fa;
    color: #1e1e2e;
}

QPushButton:disabled {
    color: #6c7086;
    border-color: #313244;
}

QPushButton#AccentButton {
    background-color: #89b4fa;
    color: #1e1e2e;
    border: none;
    font-weight: bold;
}

QPushButton#AccentButton:hover {
    background-color: #b4d0fb;
}

QPushButton#FlatButton {
    background-color: transparent;
    border: none;
    color: #6c7086;
    min-width: 28px;
    padding: 4px 6px;
}

QPushButton#FlatButton:hover {
    background-color: #313244;
    color: #cdd6f4;
}

/* ── Combo box ────────────────────────────────────────────────────────── */
QComboBox {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 6px;
    padding: 4px 8px;
    color: #cdd6f4;
}

QComboBox:focus {
    border: 1px solid #89b4fa;
}

QComboBox::drop-down {
    border: none;
    padding-right: 6px;
}

QComboBox::down-arrow {
    width: 10px;
    height: 10px;
}

QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #45475a;
    border: 1px solid #45475a;
    border-radius: 4px;
    outline: none;
}

/* ── Group box ────────────────────────────────────────────────────────── */
QGroupBox {
    border: 1px solid #45475a;
    border-radius: 6px;
    margin-top: 14px;
    padding-top: 6px;
    color: #89b4fa;
    font-weight: bold;
}

QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 4px;
}

/* ── Scroll bars ──────────────────────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 8px;
    margin: 0;
}

QScrollBar::handle:vertical {
    background: #45475a;
    border-radius: 4px;
    min-height: 24px;
}

QScrollBar::handle:vertical:hover {
    background: #585b70;
}

QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
    background: none;
    height: 0;
}

QScrollBar:horizontal {
    background: transparent;
    height: 8px;
    margin: 0;
}

QScrollBar::handle:horizontal {
    background: #45475a;
    border-radius: 4px;
    min-width: 24px;
}

QScrollBar::handle:horizontal:hover {
    background: #585b70;
}

QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {
    background: none;
    width: 0;
}

/* ── Context menu ─────────────────────────────────────────────────────── */
QMenu {
    background-color: #313244;
    border: 1px solid #45475a;
    border-radius: 8px;
    color: #cdd6f4;
    padding: 4px;
}

QMenu::item {
    padding: 6px 24px 6px 12px;
    border-radius: 4px;
}

QMenu::item:selected {
    background-color: #45475a;
    color: #89b4fa;
}

QMenu::item:disabled {
    color: #6c7086;
}

QMenu::separator {
    height: 1px;
    background: #45475a;
    margin: 4px 8px;
}

/* ── Status bar ───────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #181825;
    color: #6c7086;
    border-top: 1px solid #313244;
    font-size: 12px;
}

QStatusBar QLabel {
    color: #6c7086;
    padding: 0 4px;
}

/* ── Splitter ─────────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #313244;
}

QSplitter::handle:horizontal {
    width: 1px;
}

/* ── Form layout labels ───────────────────────────────────────────────── */
QLabel {
    background: transparent;
}

QLabel#SectionHeader {
    color: #89b4fa;
    font-weight: bold;
    font-size: 11px;
    padding-top: 4px;
}

/* ── Dialog button box ────────────────────────────────────────────────── */
QDialogButtonBox QPushButton {
    min-width: 80px;
}
"""
