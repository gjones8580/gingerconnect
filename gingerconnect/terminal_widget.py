from __future__ import annotations
import queue
from typing import Optional

import pyte
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QResizeEvent,
)
from PyQt6.QtWidgets import QWidget

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
    names = list(_ANSI.keys())  # first 16 names match ANSI order
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

        # pyte
        self._cols, self._rows = 80, 24
        self._screen = pyte.Screen(self._cols, self._rows)
        self._stream = pyte.ByteStream(self._screen)
        self._cursor_visible = True

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

        # Caller must have already called ssh.connect(); we just start I/O.
        self._connected = True
        ssh.start_io(on_data=self._queue.put, on_close=self._enqueue_close)

    # ── queue callbacks (called from background thread) ────────────────────

    def _enqueue_close(self) -> None:
        self._queue.put(None)  # sentinel

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

    # ── painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setFont(self._font)

        buf = self._screen.buffer
        cw, ch = self._cw, self._ch

        painter.fillRect(self.rect(), QColor(_BG_DEFAULT))

        for row in range(self._rows):
            line = buf.get(row, {})
            base_y = row * ch

            col = 0
            while col < self._cols:
                char = line.get(col)
                if char is None:
                    col += 1
                    continue

                data = char.data if char.data else " "
                fg_str = _resolve_color(char.fg, False)
                bg_str = _resolve_color(char.bg, True)
                bold = getattr(char, "bold", False)
                reverse = getattr(char, "reverse", False)

                if reverse:
                    fg_str, bg_str = bg_str, fg_str

                # Background
                if bg_str != _BG_DEFAULT:
                    painter.fillRect(col * cw, base_y, cw, ch, QColor(bg_str))

                # Text
                if data.strip():
                    if bold:
                        f = QFont(self._font)
                        f.setBold(True)
                        painter.setFont(f)
                    else:
                        painter.setFont(self._font)
                    painter.setPen(QColor(fg_str))
                    painter.drawText(col * cw, base_y + self._ascent, data)

                # Underline
                if getattr(char, "underscore", False):
                    painter.setPen(QColor(fg_str))
                    painter.drawLine(
                        col * cw, base_y + ch - 2,
                        col * cw + cw, base_y + ch - 2,
                    )

                col += 1

        # Cursor
        if self._cursor_visible and self.hasFocus():
            cx = self._screen.cursor.x
            cy = self._screen.cursor.y
            painter.fillRect(cx * cw, cy * ch, cw, ch, QColor(_CURSOR_COLOR))
            char = buf.get(cy, {}).get(cx)
            if char and char.data.strip():
                painter.setFont(self._font)
                painter.setPen(QColor(_BG_DEFAULT))
                painter.drawText(cx * cw, cy * ch + self._ascent, char.data)

    # ── keyboard input ─────────────────────────────────────────────────────

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        text = event.text()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)

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

    # ── resize ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        cols = max(1, self.width() // self._cw)
        rows = max(1, self.height() // self._ch)
        if cols != self._cols or rows != self._rows:
            self._cols, self._rows = cols, rows
            self._screen.resize(rows, cols)
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
