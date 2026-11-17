"""Shared fixtures for the GingerConnect test suite.

The terminal tests drive real PyQt6 widgets, so Qt runs on the offscreen
platform plugin — no display server required.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtWidgets import QApplication

from gingerconnect.terminal_widget import TerminalWidget

# TerminalWidget.setMinimumSize clamps the widget to at least this size, so
# tests that want an exact grid must stay at or above it.
MIN_COLS = 40
MIN_ROWS = 12


class FakeSSH:
    """Stand-in for SSHConnection that records what the widget sends."""

    def __init__(self) -> None:
        self.sent: list[bytes] = []
        self.resizes: list[tuple[int, int]] = []
        self.closed = False

    def start_io(self, on_data, on_close) -> None:
        self.on_data = on_data
        self.on_close = on_close

    def write(self, data: bytes) -> None:
        self.sent.append(data)

    def resize(self, cols: int, rows: int) -> None:
        self.resizes.append((cols, rows))

    def close(self) -> None:
        self.closed = True


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_terminal(qapp):
    """Build a shown TerminalWidget with an exact character grid.

    The returned widget carries a `base` attribute: the absolute line id the
    next line fed will occupy. Tests express expectations relative to it
    rather than assuming output starts at id 0.
    """
    widgets = []

    def _make(rows: int = MIN_ROWS, cols: int = MIN_COLS) -> TerminalWidget:
        assert rows >= MIN_ROWS and cols >= MIN_COLS, "below the widget minimum"
        term = TerminalWidget(FakeSSH())
        # Timers would fight the test; data is fed straight into the stream.
        term._poll_timer.stop()
        term._blink_timer.stop()
        term.resize(cols * term._cw + term._sb_w, rows * term._ch)
        term.show()          # resizeEvent, and therefore the grid, needs this
        qapp.processEvents()
        assert (term._cols, term._rows) == (cols, rows)
        term.base = term._screen.lines_scrolled
        widgets.append(term)
        return term

    yield _make

    for term in widgets:
        term._autoscroll_timer.stop()
        term.hide()
        term.deleteLater()
    qapp.processEvents()


@pytest.fixture
def terminal(make_terminal):
    """A 40x12 terminal holding 200 numbered lines (`line000`...`line199`)."""
    term = make_terminal()
    feed_lines(term, 200)
    return term


def feed_lines(term: TerminalWidget, count: int, fmt: str = "line{:03d}") -> None:
    for i in range(count):
        term._stream.feed((fmt.format(i) + "\r\n").encode())
    term._sync_scrollbar()


def row_text(term: TerminalWidget, abs_row: int) -> str | None:
    """Render one absolute row the way the widget would paint it."""
    line = term._screen.line_at(abs_row)
    if line is None:
        return None
    out = []
    for col in range(term._cols):
        char = line.get(col)
        if char is None:
            out.append(" ")
        elif char.data == "":
            continue  # stub cell trailing a double-width character
        else:
            out.append(char.data)
    return "".join(out).rstrip()


def select(term: TerminalWidget, start: tuple[int, int], end: tuple[int, int]) -> None:
    """Set an active selection directly, in absolute (row_id, col) coords."""
    term._sel_anchor = start
    term._sel_end = end
    term._sel_active = True
