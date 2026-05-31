from __future__ import annotations
import queue
from collections import deque
from typing import Optional

import pyte
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QResizeEvent,
)
from PyQt6.QtWidgets import QApplication, QMenu, QWidget

from gingerconnect.protocols.ssh import SSHConnection

# Catppuccin Mocha ANSI palette
_ANSI: dict[str, str] = {
    "default":       "#cdd6f4",
    "black":         "#45475a",
    "red":           "#f38ba8",
    "green":         "#a6e3a1",
    "yellow":        "#f9e2af",
    "blue":          "#89b4fa",
    "magenta":       "#cba6f7",
    "cyan":          "#89dceb",
    "white":         "#bac2de",
    "brightblack":   "#585b70",
    "brightred":     "#f38ba8",
    "brightgreen":   "#a6e3a1",
    "brightyellow":  "#f9e2af",
    "brightblue":    "#89b4fa",
    "brightmagenta": "#cba6f7",
    "brightcyan":    "#89dceb",
    "brightwhite":   "#cdd6f4",
}
_FG_DEFAULT = "#cdd6f4"
_BG_DEFAULT = "#1e1e2e"
_CURSOR_COLOR = "#89b4fa"
_SEL_BG = "#264f78"

_KEY_MAP: dict[int, bytes] = {
    Qt.Key.Key_Return:   b"\r",
    Qt.Key.Key_Enter:    b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Delete:   b"\x1b[3~",
    Qt.Key.Key_Escape:   b"\x1b",
    Qt.Key.Key_Tab:      b"\t",
    Qt.Key.Key_Up:       b"\x1b[A",
    Qt.Key.Key_Down:     b"\x1b[B",
    Qt.Key.Key_Right:    b"\x1b[C",
    Qt.Key.Key_Left:     b"\x1b[D",
    Qt.Key.Key_Home:     b"\x1b[H",
    Qt.Key.Key_End:      b"\x1b[F",
    Qt.Key.Key_PageUp:   b"\x1b[5~",
    Qt.Key.Key_PageDown: b"\x1b[6~",
    Qt.Key.Key_Insert:   b"\x1b[2~",
    Qt.Key.Key_F1:  b"\x1bOP",
    Qt.Key.Key_F2:  b"\x1bOQ",
    Qt.Key.Key_F3:  b"\x1bOR",
    Qt.Key.Key_F4:  b"\x1bOS",
    Qt.Key.Key_F5:  b"\x1b[15~",
    Qt.Key.Key_F6:  b"\x1b[17~",
    Qt.Key.Key_F7:  b"\x1b[18~",
    Qt.Key.Key_F8:  b"\x1b[19~",
    Qt.Key.Key_F9:  b"\x1b[20~",
    Qt.Key.Key_F10: b"\x1b[21~",
    Qt.Key.Key_F11: b"\x1b[23~",
    Qt.Key.Key_F12: b"\x1b[24~",
}


def _resolve_color(color: object, is_bg: bool) -> str:
    default = _BG_DEFAULT if is_bg else _FG_DEFAULT
    if color is None or color == "default":
        return default
    if isinstance(color, str):
        if color.startswith("#"):
            return color
        return _ANSI.get(color, default)
    if isinstance(color, int):
        return _256color(color)
    if isinstance(color, (list, tuple)) and len(color) == 3:
        r, g, b = color
        return f"#{r:02x}{g:02x}{b:02x}"
    return default


def _256color(idx: int) -> str:
    _standard = [
        "#45475a", "#f38ba8", "#a6e3a1", "#f9e2af",
        "#89b4fa", "#cba6f7", "#89dceb", "#bac2de",
        "#585b70", "#f38ba8", "#a6e3a1", "#f9e2af",
        "#89b4fa", "#cba6f7", "#89dceb", "#cdd6f4",
    ]
    if idx < 16:
        return _standard[idx]
    if idx < 232:
        idx -= 16
        b = idx % 6
        g = (idx // 6) % 6
        r = idx // 36
        def v(n: int) -> int:
            return 0 if n == 0 else 55 + n * 40
        return f"#{v(r):02x}{v(g):02x}{v(b):02x}"
    grey = 8 + (idx - 232) * 10
    return f"#{grey:02x}{grey:02x}{grey:02x}"


class ScrollbackScreen(pyte.Screen):
    """pyte Screen that captures lines as they scroll off the top."""

    def __init__(self, columns: int, lines: int, max_history: int = 5000) -> None:
        super().__init__(columns, lines)
        self._scrollback: deque[dict] = deque(maxlen=max_history)

    def index(self) -> None:
        try:
            margins = self.margins
            top = margins.top if margins else 0
            bottom = margins.bottom if margins else (self.lines - 1)
        except AttributeError:
            top, bottom = 0, self.lines - 1

        if self.cursor.y == bottom:
            self._scrollback.append(dict(self.buffer.get(top, {})))

        super().index()


class TerminalWidget(QWidget):
    connection_closed = pyqtSignal(str)  # emits error message or empty str

    def __init__(self, ssh: SSHConnection, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.ssh = ssh
        self._connected = False

        # Font & metrics
        font = QFont("Monospace")
        font.setStyleHint(QFont.StyleHint.TypeWriter)
        font.setPointSize(11)
        font.setFixedPitch(True)
        self._font = font
        m = QFontMetrics(font)
        self._cw = m.horizontalAdvance("M")
        self._ch = m.height()
        self._ascent = m.ascent()

        # pyte with scrollback
        self._cols, self._rows = 80, 24
        self._screen = ScrollbackScreen(self._cols, self._rows)
        self._stream = pyte.ByteStream(self._screen)
        self._cursor_visible = True

        # Scrollback state
        self._scroll_offset = 0  # lines scrolled above the live view

        # Selection state (display-coordinate row/col pairs)
        self._sel_anchor: Optional[tuple[int, int]] = None
        self._sel_end: Optional[tuple[int, int]] = None
        self._selecting = False

        # Queue for thread-safe data passing
        self._queue: queue.Queue[bytes | None] = queue.Queue()

        # Blink timer for cursor
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start(600)

        # Poll timer for incoming SSH data
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._drain_queue)
        self._poll_timer.start(16)  # ~60 fps

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(self._cw * 40, self._ch * 12)

        self._connected = True
        ssh.start_io(on_data=self._queue.put, on_close=self._enqueue_close)

    # ── queue callbacks (called from background thread) ────────────────────

    def _enqueue_close(self) -> None:
        self._queue.put(None)

    # ── main-thread processing ─────────────────────────────────────────────

    def _drain_queue(self) -> None:
        changed = False
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if item is None:
                self._poll_timer.stop()
                self._blink_timer.stop()
                self.connection_closed.emit("")
                return
            self._stream.feed(item)
            changed = True
        if changed:
            self.update()

    def _blink(self) -> None:
        self._cursor_visible = not self._cursor_visible
        cx = self._screen.cursor.x
        cy = self._screen.cursor.y
        x = cx * self._cw
        y = cy * self._ch
        self.update(x, y, self._cw, self._ch)

    # ── scrollback helpers ─────────────────────────────────────────────────

    def _get_display_line(self, display_row: int) -> dict:
        """Return the line dict for a given display row, accounting for scroll."""
        hist = self._screen._scrollback
        hist_len = len(hist)
        if self._scroll_offset == 0:
            return self._screen.buffer.get(display_row, {})
        combined_idx = hist_len - self._scroll_offset + display_row
        if combined_idx < 0:
            return {}
        if combined_idx < hist_len:
            return hist[combined_idx]
        screen_row = combined_idx - hist_len
        return self._screen.buffer.get(screen_row, {})

    # ── selection helpers ──────────────────────────────────────────────────

    def _pixel_to_cell(self, pos: QPoint) -> tuple[int, int]:
        row = max(0, min(self._rows - 1, pos.y() // self._ch))
        col = max(0, min(self._cols - 1, pos.x() // self._cw))
        return (row, col)

    def _is_cell_selected(self, row: int, col: int) -> bool:
        if self._sel_anchor is None or self._sel_end is None:
            return False
        if self._sel_anchor == self._sel_end:
            return False
        r1, c1 = self._sel_anchor
        r2, c2 = self._sel_end
        if (r1, c1) > (r2, c2):
            r1, c1, r2, c2 = r2, c2, r1, c1
        if row < r1 or row > r2:
            return False
        if r1 == r2:
            return c1 <= col <= c2
        if row == r1:
            return col >= c1
        if row == r2:
            return col <= c2
        return True

    def _copy_selection(self) -> None:
        if (self._sel_anchor is None or self._sel_end is None
                or self._sel_anchor == self._sel_end):
            return
        r1, c1 = self._sel_anchor
        r2, c2 = self._sel_end
        if (r1, c1) > (r2, c2):
            r1, c1, r2, c2 = r2, c2, r1, c1
        lines = []
        for row in range(r1, r2 + 1):
            sc = c1 if row == r1 else 0
            ec = (c2 + 1) if row == r2 else self._cols
            line_data = self._get_display_line(row)
            chars = []
            for col in range(sc, ec):
                char = line_data.get(col)
                chars.append(char.data if char and char.data else " ")
            lines.append("".join(chars).rstrip())
        QApplication.clipboard().setText("\n".join(lines))

    def _paste_clipboard(self) -> None:
        if not self._connected:
            return
        text = QApplication.clipboard().text()
        if text:
            self.ssh.write(text.encode("utf-8"))

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        has_sel = (
            self._sel_anchor is not None
            and self._sel_end is not None
            and self._sel_anchor != self._sel_end
        )
        copy_act = menu.addAction("Copy")
        copy_act.setEnabled(has_sel)
        paste_act = menu.addAction("Paste")
        action = menu.exec(global_pos)
        if action == copy_act:
            self._copy_selection()
        elif action == paste_act:
            self._paste_clipboard()

    # ── painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setFont(self._font)

        cw, ch = self._cw, self._ch

        painter.fillRect(self.rect(), QColor(_BG_DEFAULT))

        for row in range(self._rows):
            line = self._get_display_line(row)
            base_y = row * ch

            col = 0
            while col < self._cols:
                is_selected = self._is_cell_selected(row, col)
                char = line.get(col)

                if char is None:
                    if is_selected:
                        painter.fillRect(col * cw, base_y, cw, ch, QColor(_SEL_BG))
                    col += 1
                    continue

                data = char.data if char.data else " "
                fg_str = _resolve_color(char.fg, False)
                bg_str = _resolve_color(char.bg, True)
                bold = getattr(char, "bold", False)
                reverse = getattr(char, "reverse", False)

                if reverse:
                    fg_str, bg_str = bg_str, fg_str

                effective_bg = _SEL_BG if is_selected else bg_str

                if effective_bg != _BG_DEFAULT:
                    painter.fillRect(col * cw, base_y, cw, ch, QColor(effective_bg))

                if data.strip():
                    if bold:
                        f = QFont(self._font)
                        f.setBold(True)
                        painter.setFont(f)
                    else:
                        painter.setFont(self._font)
                    painter.setPen(QColor(fg_str))
                    painter.drawText(col * cw, base_y + self._ascent, data)

                if getattr(char, "underscore", False):
                    painter.setPen(QColor(fg_str))
                    painter.drawLine(
                        col * cw, base_y + ch - 2,
                        col * cw + cw, base_y + ch - 2,
                    )

                col += 1

        # Cursor only visible on the live screen, not scrollback
        if self._cursor_visible and self.hasFocus() and self._scroll_offset == 0:
            cx = self._screen.cursor.x
            cy = self._screen.cursor.y
            painter.fillRect(cx * cw, cy * ch, cw, ch, QColor(_CURSOR_COLOR))
            char = self._screen.buffer.get(cy, {}).get(cx)
            if char and char.data.strip():
                painter.setFont(self._font)
                painter.setPen(QColor(_BG_DEFAULT))
                painter.drawText(cx * cw, cy * ch + self._ascent, char.data)

    # ── keyboard input ─────────────────────────────────────────────────────

    def focusNextPrevChild(self, _next: bool) -> bool:
        # Prevent Qt from stealing Tab/Shift+Tab for focus traversal.
        # keyPressEvent handles Tab → \t forwarded to SSH.
        return False

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        text = event.text()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

        # Clipboard shortcuts — handled without touching scroll or selection
        if ctrl and shift:
            if key == Qt.Key.Key_C:
                self._copy_selection()
                return
            if key == Qt.Key.Key_V:
                self._paste_clipboard()
                return

        # All other keystrokes reset scroll to live view and clear selection
        self._scroll_offset = 0
        self._sel_anchor = None
        self._sel_end = None

        if key in _KEY_MAP:
            if key == Qt.Key.Key_Up and ctrl:
                data = b"\x1b[1;5A"
            elif key == Qt.Key.Key_Down and ctrl:
                data = b"\x1b[1;5B"
            elif key == Qt.Key.Key_Right and ctrl:
                data = b"\x1b[1;5C"
            elif key == Qt.Key.Key_Left and ctrl:
                data = b"\x1b[1;5D"
            else:
                data = _KEY_MAP[key]
            self.ssh.write(data)
            return

        if ctrl and text:
            ch = text.upper()
            if "A" <= ch <= "Z":
                self.ssh.write(bytes([ord(ch) - ord("A") + 1]))
                return
            if ch == "@":
                self.ssh.write(b"\x00")
                return

        if text:
            self.ssh.write(text.encode("utf-8"))

    # ── mouse input ────────────────────────────────────────────────────────

    def mousePressEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            cell = self._pixel_to_cell(event.position().toPoint())
            self._sel_anchor = cell
            self._sel_end = cell
            self._selecting = True
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._selecting:
            cell = self._pixel_to_cell(event.position().toPoint())
            if cell != self._sel_end:
                self._sel_end = cell
                self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._selecting = False
        super().mouseReleaseEvent(event)

    # ── scroll wheel ───────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        step = 3
        if delta > 0:
            self._scroll_offset = min(
                self._scroll_offset + step,
                len(self._screen._scrollback),
            )
        else:
            self._scroll_offset = max(0, self._scroll_offset - step)
        self.update()
        event.accept()

    # ── resize ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        cols = max(1, self.width() // self._cw)
        rows = max(1, self.height() // self._ch)
        if cols != self._cols or rows != self._rows:
            self._cols, self._rows = cols, rows
            self._screen.resize(rows, cols)
            self._screen._scrollback.clear()
            self._scroll_offset = 0
            if self._connected:
                self.ssh.resize(cols, rows)

    def focusInEvent(self, event) -> None:  # type: ignore[override]
        super().focusInEvent(event)
        self.update()

    def focusOutEvent(self, event) -> None:  # type: ignore[override]
        super().focusOutEvent(event)
        self.update()

    def sizeHint(self):  # type: ignore[override]
        from PyQt6.QtCore import QSize
        return QSize(self._cw * self._cols, self._ch * self._rows)

    def close_connection(self) -> None:
        self._poll_timer.stop()
        self._blink_timer.stop()
        self.ssh.close()
