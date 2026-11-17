from __future__ import annotations
import queue
from collections import deque
from typing import Optional

import pyte
from pyte.screens import Margins
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QFont, QFontMetrics, QKeyEvent, QPainter, QResizeEvent,
)
from PyQt6.QtWidgets import QApplication, QMenu, QScrollBar, QWidget

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
    """pyte Screen with a scrollback buffer addressed by absolute line id.

    Every line that has ever occupied the screen gets a stable, monotonically
    increasing id, so a selection (or a scroll position) can be anchored to a
    line of *output* rather than to a row of the *viewport*:

        * live screen row ``y``  -> ``lines_scrolled + y``
        * ``_scrollback[i]``     -> ``history_base + i``

    ``lines_scrolled`` is only ever bumped together with a history append, so
    the two mappings stay contiguous and ``line_at()`` can resolve any id with
    plain arithmetic.
    """

    def __init__(self, columns: int, lines: int, max_history: int = 5000) -> None:
        # These must exist before Screen.__init__, which calls reset().
        self._scrollback: deque[dict] = deque(maxlen=max_history)
        self._scrollback_wrapped: deque[bool] = deque(maxlen=max_history)
        self._wrapped_rows: set[int] = set()
        self._in_draw = False
        self._alt_screen = False
        self.lines_scrolled = 0
        self._history_base = 0
        super().__init__(columns, lines)

    # ── absolute-id lookups ────────────────────────────────────────────────

    @property
    def alt_screen(self) -> bool:
        return self._alt_screen

    @property
    def history_base(self) -> int:
        """Absolute id of the oldest line still retrievable."""
        return self._history_base

    @property
    def history_len(self) -> int:
        return len(self._scrollback)

    def line_at(self, abs_row: int) -> Optional[dict]:
        """Line dict for an absolute row id, or None if it is unavailable."""
        if abs_row >= self.lines_scrolled:
            y = abs_row - self.lines_scrolled
            return self.buffer.get(y, {}) if y < self.lines else None
        i = abs_row - self._history_base
        return self._scrollback[i] if 0 <= i < len(self._scrollback) else None

    def wrapped_at(self, abs_row: int) -> bool:
        """True if this line continues onto the next one via autowrap."""
        if abs_row >= self.lines_scrolled:
            return (abs_row - self.lines_scrolled) in self._wrapped_rows
        i = abs_row - self._history_base
        if 0 <= i < len(self._scrollback_wrapped):
            return self._scrollback_wrapped[i]
        return False

    # ── history maintenance ────────────────────────────────────────────────

    def _push_history(self, y: int) -> None:
        if len(self._scrollback) == self._scrollback.maxlen:
            self._history_base += 1
        elif not self._scrollback:
            self._history_base = self.lines_scrolled
        self._scrollback.append(dict(self.buffer.get(y, {})))
        self._scrollback_wrapped.append(y in self._wrapped_rows)
        self.lines_scrolled += 1

    def _shift_wrap_flags(self, top: int, bottom: int) -> None:
        """Mirror index()'s buffer shift onto the wrap flags."""
        if not self._wrapped_rows:
            return
        self._wrapped_rows = {
            (y - 1 if top < y <= bottom else y)
            for y in self._wrapped_rows
            if y != top
        }

    # ── wrap detection ─────────────────────────────────────────────────────

    def draw(self, data: str) -> None:
        # The only index() Screen.draw() can trigger is the autowrap one, so
        # this flag distinguishes a soft wrap from a real newline.
        self._in_draw = True
        try:
            super().draw(data)
        finally:
            self._in_draw = False

    def index(self) -> None:
        top, bottom = self.margins or Margins(0, self.lines - 1)
        scrolling = self.cursor.y == bottom

        if self._in_draw:
            self._wrapped_rows.add(self.cursor.y)
        else:
            self._wrapped_rows.discard(self.cursor.y)

        if scrolling and not self._alt_screen:
            self._push_history(top)

        super().index()

        if scrolling:
            self._shift_wrap_flags(top, bottom)

    # Line movement other than index() is rare in logs; treat the affected
    # lines as hard-terminated rather than tracking the shift precisely.
    def reverse_index(self) -> None:
        self._wrapped_rows.clear()
        super().reverse_index()

    def insert_lines(self, *args, **kwargs) -> None:
        self._wrapped_rows.clear()
        super().insert_lines(*args, **kwargs)

    def delete_lines(self, *args, **kwargs) -> None:
        self._wrapped_rows.clear()
        super().delete_lines(*args, **kwargs)

    # ── alternate screen ───────────────────────────────────────────────────

    # pyte has no alternate buffer, but full-screen apps still scroll their
    # redraws off the top. Keeping those out of history keeps the log clean.
    _ALT_MODES = frozenset((47, 1047, 1049))

    def set_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and self._ALT_MODES.intersection(modes):
            self._alt_screen = True
            self._wrapped_rows.clear()
        super().set_mode(*modes, **kwargs)

    def reset_mode(self, *modes: int, **kwargs) -> None:
        if kwargs.get("private") and self._ALT_MODES.intersection(modes):
            self._alt_screen = False
            self._wrapped_rows.clear()
        super().reset_mode(*modes, **kwargs)

    # ── screen lifecycle ───────────────────────────────────────────────────

    def reset(self) -> None:
        super().reset()
        self._wrapped_rows.clear()

    def erase_in_display(self, how: int = 0, *args, **kwargs) -> None:
        if how == 3:  # ESC [ 3 J — explicitly drop the scrollback
            self._scrollback.clear()
            self._scrollback_wrapped.clear()
            self._history_base = self.lines_scrolled
        if how in (2, 3):
            self._wrapped_rows.clear()
        super().erase_in_display(how, *args, **kwargs)

    def resize(self, lines: Optional[int] = None, columns: Optional[int] = None) -> None:
        """Resize, preserving absolute ids across a row-count shrink.

        Screen.resize() drops surplus lines off the *top*; push them into
        history first so ids stay contiguous (a live row's id is unchanged:
        ``lines_scrolled`` grows by exactly as much as ``y`` shrinks).
        """
        new_lines = lines if lines else self.lines
        drop = self.lines - new_lines
        if drop > 0 and not self._alt_screen:
            # On a pristine screen (nothing drawn, nothing scrolled yet) the
            # dropped rows are blank and no ids are in use, so discard them
            # instead of seeding history with empty lines at startup.
            pristine = (self.lines_scrolled == 0
                        and not self._scrollback
                        and not any(y in self.buffer for y in range(drop)))
            if not pristine:
                for y in range(drop):
                    self._push_history(y)
        super().resize(lines, columns)
        self._wrapped_rows.clear()


# Characters that count as part of a "word" for double-click selection, on
# top of alphanumerics — chosen so paths, URLs and log tokens select whole.
_WORD_CHARS = "_-./:@~+=?&%#"

# Selection auto-scroll while dragging past the top or bottom edge
_AUTOSCROLL_MS = 40
_AUTOSCROLL_MAX_LINES = 8


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

        # Viewport: absolute id of the top display row. While _follow is set
        # the view is pinned to the live screen; otherwise it stays on the
        # same lines of output no matter how much new output arrives.
        self._follow = True
        self._view_top = 0

        # Selection, in absolute (row_id, col) coordinates
        self._sel_anchor: Optional[tuple[int, int]] = None
        self._sel_end: Optional[tuple[int, int]] = None
        self._sel_active = False
        self._selecting = False
        self._last_dbl_ms = 0
        self._drag_pos: Optional[QPoint] = None

        # Scrollbar (child overlay; the gutter is reserved out of the columns)
        self._scrollbar = QScrollBar(Qt.Orientation.Vertical, self)
        self._scrollbar.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._scrollbar.setCursor(Qt.CursorShape.ArrowCursor)
        self._sb_w = max(8, self._scrollbar.sizeHint().width())
        self._sb_guard = False
        self._scrollbar.valueChanged.connect(self._on_scrollbar)
        self._scrollbar.hide()

        # Queue for thread-safe data passing
        self._queue: queue.Queue[bytes | None] = queue.Queue()

        # Blink timer for cursor
        self._blink_timer = QTimer(self)
        self._blink_timer.timeout.connect(self._blink)
        self._blink_timer.start(600)

        # Drives selection auto-scroll while the pointer is dragged outside
        self._autoscroll_timer = QTimer(self)
        self._autoscroll_timer.timeout.connect(self._autoscroll_tick)

        # Poll timer for incoming SSH data
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._drain_queue)
        self._poll_timer.start(16)  # ~60 fps

        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(self._cw * 40 + self._sb_w, self._ch * 12)

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
            self._sync_scrollbar()
            self.update()

    def _blink(self) -> None:
        self._cursor_visible = not self._cursor_visible
        row = self._cursor_display_row()
        if row is None:
            return
        self.update(self._screen.cursor.x * self._cw, row * self._ch,
                    self._cw, self._ch)

    # ── viewport ───────────────────────────────────────────────────────────

    def _view_top_abs(self) -> int:
        """Absolute line id shown on display row 0."""
        screen = self._screen
        if self._follow or screen.alt_screen:
            return screen.lines_scrolled
        return max(screen.history_base,
                   min(self._view_top, screen.lines_scrolled))

    def _abs_row(self, display_row: int) -> int:
        return self._view_top_abs() + display_row

    def _cursor_display_row(self) -> Optional[int]:
        row = (self._screen.lines_scrolled + self._screen.cursor.y
               - self._view_top_abs())
        return row if 0 <= row < self._rows else None

    def _scroll_to(self, abs_top: int) -> None:
        screen = self._screen
        abs_top = max(screen.history_base, min(abs_top, screen.lines_scrolled))
        self._follow = abs_top >= screen.lines_scrolled
        self._view_top = abs_top
        self._sync_scrollbar()
        self.update()

    def _scroll_by(self, lines: int) -> None:
        """Scroll by `lines`; negative moves toward older output."""
        if self._screen.alt_screen:
            return
        self._scroll_to(self._view_top_abs() + lines)

    def _sync_scrollbar(self) -> None:
        screen = self._screen
        span = 0 if screen.alt_screen else screen.lines_scrolled - screen.history_base
        self._sb_guard = True
        try:
            self._scrollbar.setRange(0, max(0, span))
            self._scrollbar.setPageStep(max(1, self._rows))
            self._scrollbar.setSingleStep(1)
            self._scrollbar.setValue(self._view_top_abs() - screen.history_base)
        finally:
            self._sb_guard = False
        self._scrollbar.setVisible(span > 0)

    def _on_scrollbar(self, value: int) -> None:
        if self._sb_guard:
            return
        self._scroll_to(self._screen.history_base + value)

    # ── selection ──────────────────────────────────────────────────────────

    def _pixel_to_cell(self, pos: QPoint) -> tuple[int, int]:
        """Map a pixel position to an absolute (row_id, col) pair."""
        display_row = max(0, min(self._rows - 1, pos.y() // self._ch))
        col = max(0, min(self._cols - 1, pos.x() // self._cw))
        return (self._abs_row(display_row), col)

    def _has_selection(self) -> bool:
        return (self._sel_active
                and self._sel_anchor is not None
                and self._sel_end is not None)

    def _sel_range(self) -> Optional[tuple[int, int, int, int]]:
        if not self._has_selection():
            return None
        (r1, c1), (r2, c2) = sorted((self._sel_anchor, self._sel_end))
        return (r1, c1, r2, c2)

    def _clear_selection(self) -> None:
        self._sel_anchor = None
        self._sel_end = None
        self._sel_active = False

    def _is_cell_selected(self, abs_row: int, col: int) -> bool:
        rng = self._sel_range()
        if rng is None:
            return False
        r1, c1, r2, c2 = rng
        if abs_row < r1 or abs_row > r2:
            return False
        if r1 == r2:
            return c1 <= col <= c2
        if abs_row == r1:
            return col >= c1
        if abs_row == r2:
            return col <= c2
        return True

    def _char_at(self, line: dict, col: int) -> str:
        char = line.get(col)
        if char is None:
            return " "
        return char.data if char.data else " "

    def _selected_text(self) -> str:
        rng = self._sel_range()
        if rng is None:
            return ""
        r1, c1, r2, c2 = rng
        screen = self._screen
        lines: list[str] = []
        pending = ""  # accumulated soft-wrapped prefix
        for row in range(r1, r2 + 1):
            line = screen.line_at(row)
            if line is None:  # aged out of history, or past the live screen
                continue
            start = c1 if row == r1 else 0
            stop = (c2 + 1) if row == r2 else self._cols
            chars = []
            for col in range(start, stop):
                char = line.get(col)
                if char is None:
                    chars.append(" ")
                elif char.data == "":
                    continue  # stub cell trailing a double-width character
                else:
                    chars.append(char.data)
            segment = "".join(chars)
            if screen.wrapped_at(row) and row < r2:
                pending += segment  # continues on the next row; keep padding
            else:
                lines.append((pending + segment).rstrip())
                pending = ""
        if pending:
            lines.append(pending.rstrip())
        return "\n".join(lines)

    def _copy_selection(self) -> None:
        text = self._selected_text()
        if text:
            QApplication.clipboard().setText(text)

    def _paste_clipboard(self) -> None:
        if not self._connected:
            return
        text = QApplication.clipboard().text()
        if text:
            self.ssh.write(text.encode("utf-8"))

    def _select_all(self) -> None:
        screen = self._screen
        self._sel_anchor = (screen.history_base, 0)
        self._sel_end = (screen.lines_scrolled + self._rows - 1, self._cols - 1)
        self._sel_active = True
        self.update()

    def _select_word(self, cell: tuple[int, int]) -> None:
        abs_row, col = cell
        line = self._screen.line_at(abs_row)
        if line is None:
            return

        def kind(c: int) -> int:
            ch = self._char_at(line, c)
            if ch.isspace():
                return 0
            if ch.isalnum() or ch in _WORD_CHARS:
                return 1
            return 2

        target = kind(col)
        start = col
        while start > 0 and kind(start - 1) == target:
            start -= 1
        end = col
        while end < self._cols - 1 and kind(end + 1) == target:
            end += 1
        self._sel_anchor = (abs_row, start)
        self._sel_end = (abs_row, end)
        self._sel_active = True
        self.update()

    def _select_line(self, cell: tuple[int, int]) -> None:
        """Select the whole logical line, following soft wraps both ways."""
        abs_row = cell[0]
        screen = self._screen
        first = abs_row
        while first > screen.history_base and screen.wrapped_at(first - 1):
            first -= 1
        last = abs_row
        limit = screen.lines_scrolled + self._rows - 1
        while last < limit and screen.wrapped_at(last):
            last += 1
        self._sel_anchor = (first, 0)
        self._sel_end = (last, self._cols - 1)
        self._sel_active = True
        self.update()

    def _show_context_menu(self, global_pos: QPoint) -> None:
        menu = QMenu(self)
        copy_act = menu.addAction("Copy")
        copy_act.setEnabled(self._has_selection())
        paste_act = menu.addAction("Paste")
        menu.addSeparator()
        select_all_act = menu.addAction("Select All")
        action = menu.exec(global_pos)
        if action == copy_act:
            self._copy_selection()
        elif action == paste_act:
            self._paste_clipboard()
        elif action == select_all_act:
            self._select_all()

    # ── painting ───────────────────────────────────────────────────────────

    def paintEvent(self, _event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setFont(self._font)

        cw, ch = self._cw, self._ch
        view_top = self._view_top_abs()

        painter.fillRect(self.rect(), QColor(_BG_DEFAULT))

        for row in range(self._rows):
            line = self._screen.line_at(view_top + row)
            if line is None:
                line = {}
            base_y = row * ch
            abs_row = view_top + row

            col = 0
            while col < self._cols:
                is_selected = self._is_cell_selected(abs_row, col)
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

        # Cursor, drawn only while its line is actually in view
        cursor_row = self._cursor_display_row()
        if self._cursor_visible and self.hasFocus() and cursor_row is not None:
            cx = self._screen.cursor.x
            painter.fillRect(cx * cw, cursor_row * ch, cw, ch, QColor(_CURSOR_COLOR))
            char = self._screen.buffer.get(self._screen.cursor.y, {}).get(cx)
            if char and char.data.strip():
                painter.setFont(self._font)
                painter.setPen(QColor(_BG_DEFAULT))
                painter.drawText(cx * cw, cursor_row * ch + self._ascent, char.data)

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

        # Clipboard/selection shortcuts — must not disturb scroll or selection
        if ctrl and shift:
            if key == Qt.Key.Key_C:
                self._copy_selection()
                return
            if key == Qt.Key.Key_V:
                self._paste_clipboard()
                return
            if key == Qt.Key.Key_A:
                self._select_all()
                return

        # Scrollback navigation — keeps the selection intact
        if shift and not ctrl:
            if key == Qt.Key.Key_PageUp:
                self._scroll_by(-max(1, self._rows - 1))
                return
            if key == Qt.Key.Key_PageDown:
                self._scroll_by(max(1, self._rows - 1))
                return
            if key == Qt.Key.Key_Home:
                self._scroll_to(self._screen.history_base)
                return
            if key == Qt.Key.Key_End:
                self._scroll_to(self._screen.lines_scrolled)
                return

        # All other keystrokes snap back to the live view and drop the selection
        self._follow = True
        self._clear_selection()
        self._sync_scrollbar()

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
            interval = QApplication.doubleClickInterval()
            if self._last_dbl_ms and event.timestamp() - self._last_dbl_ms <= interval:
                # Third click of a triple-click: take the whole logical line.
                self._last_dbl_ms = 0
                self._select_line(cell)
                super().mousePressEvent(event)
                return
            self._last_dbl_ms = 0
            if (event.modifiers() & Qt.KeyboardModifier.ShiftModifier
                    and self._sel_anchor is not None):
                self._sel_end = cell          # extend the existing selection
                self._sel_active = True
            else:
                self._sel_anchor = cell
                self._sel_end = cell
                self._sel_active = False      # a bare click selects nothing
            self._selecting = True
            self._drag_pos = event.position().toPoint()
            self._autoscroll_timer.stop()
            self.update()
        elif event.button() == Qt.MouseButton.RightButton:
            self._show_context_menu(event.globalPosition().toPoint())
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._last_dbl_ms = event.timestamp()
            self._select_word(self._pixel_to_cell(event.position().toPoint()))
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event) -> None:  # type: ignore[override]
        if self._selecting:
            pos = event.position().toPoint()
            self._drag_pos = pos
            self._extend_selection(pos)
            if self._autoscroll_lines(pos.y()):
                if not self._autoscroll_timer.isActive():
                    self._autoscroll_timer.start(_AUTOSCROLL_MS)
            else:
                self._autoscroll_timer.stop()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # type: ignore[override]
        if event.button() == Qt.MouseButton.LeftButton:
            self._selecting = False
            self._stop_autoscroll()
        super().mouseReleaseEvent(event)

    # ── drag auto-scroll ───────────────────────────────────────────────────

    def _extend_selection(self, pos: QPoint) -> None:
        cell = self._pixel_to_cell(pos)
        if cell != self._sel_end:
            self._sel_end = cell
            self._sel_active = cell != self._sel_anchor
            self.update()

    def _autoscroll_lines(self, y: int) -> int:
        """Lines to scroll per tick for a pointer `y` px outside the viewport.

        Zero while the pointer is inside; otherwise signed, and faster the
        further past the edge it is, so a long log can be crossed quickly.
        """
        if y < 0:
            overshoot, direction = -y, -1
        elif y >= self.height():
            overshoot, direction = y - self.height() + 1, 1
        else:
            return 0
        rows = 1 + overshoot // max(1, self._ch)
        return direction * min(rows, _AUTOSCROLL_MAX_LINES)

    def _autoscroll_tick(self) -> None:
        if not self._selecting or self._drag_pos is None:
            self._stop_autoscroll()
            return
        lines = self._autoscroll_lines(self._drag_pos.y())
        if not lines:
            self._stop_autoscroll()
            return
        before = self._view_top_abs()
        self._scroll_by(lines)
        if self._view_top_abs() == before:
            self._stop_autoscroll()   # already at the end of the buffer
            return
        self._extend_selection(self._drag_pos)

    def _stop_autoscroll(self) -> None:
        self._autoscroll_timer.stop()
        self._drag_pos = None

    # ── scroll wheel ───────────────────────────────────────────────────────

    def wheelEvent(self, event) -> None:  # type: ignore[override]
        delta = event.angleDelta().y()
        if delta:
            self._scroll_by(-3 if delta > 0 else 3)
        event.accept()

    # ── resize ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._scrollbar.setGeometry(
            self.width() - self._sb_w, 0, self._sb_w, self.height()
        )
        cols = max(1, (self.width() - self._sb_w) // self._cw)
        rows = max(1, self.height() // self._ch)
        if cols != self._cols or rows != self._rows:
            self._cols, self._rows = cols, rows
            # Scrollback survives the resize; only the selection is dropped,
            # since a column change invalidates its column offsets.
            self._screen.resize(rows, cols)
            self._clear_selection()
            self._follow = True
            self._sync_scrollbar()
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
        return QSize(self._cw * self._cols + self._sb_w, self._ch * self._rows)

    def close_connection(self) -> None:
        self._poll_timer.stop()
        self._blink_timer.stop()
        self._autoscroll_timer.stop()
        self.ssh.close()
