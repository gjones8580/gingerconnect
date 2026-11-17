"""Phase 7: word/line selection, soft-wrap joining on copy, wide characters."""
from __future__ import annotations

import pytest

from conftest import select


@pytest.fixture
def log_line(make_terminal):
    """A 60-column terminal holding one line of log-like text."""
    term = make_terminal(cols=60)
    term._stream.feed(b"ERROR /var/log/app.log failed after 3 tries\r\n")
    term._sync_scrollbar()
    return term


@pytest.fixture
def wrapped(make_terminal):
    """A 40-column terminal holding a 95-char line that wraps over 3 rows."""
    term = make_terminal()
    term.long_line = "A" * 95
    term._stream.feed((term.long_line + "\r\nshort\r\n").encode())
    term._sync_scrollbar()
    return term


class TestWordSelection:
    @pytest.mark.parametrize("col,expected", [
        (0, "ERROR"),
        (4, "ERROR"),
        (8, "/var/log/app.log"),     # inside the path
        (6, "/var/log/app.log"),     # on the leading slash
        (21, "/var/log/app.log"),    # on the trailing "g"
        (24, "failed"),
        (40, "tries"),
    ])
    def test_double_click_picks_the_whole_token(self, log_line, col, expected):
        log_line._select_word((log_line.base, col))
        assert log_line._selected_text() == expected

    def test_clicking_whitespace_selects_the_gap(self, log_line):
        log_line._select_word((log_line.base, 5))   # the space after ERROR
        assert log_line._selected_text().strip() == ""

    def test_word_selection_is_active(self, log_line):
        log_line._select_word((log_line.base, 0))
        assert log_line._has_selection() is True

    def test_single_character_word_still_selects(self, make_terminal):
        term = make_terminal(cols=60)
        term._stream.feed(b"a (b) c\r\n")
        term._sync_scrollbar()
        term._select_word((term.base, 0))
        assert term._selected_text() == "a"

    def test_punctuation_is_its_own_run(self, make_terminal):
        term = make_terminal(cols=60)
        term._stream.feed(b"value = (1,2)\r\n")
        term._sync_scrollbar()
        term._select_word((term.base, 8))    # the "("
        assert term._selected_text() == "("

    def test_word_selection_works_deep_in_history(self, terminal):
        terminal._select_word((terminal.base + 3, 2))
        assert terminal._selected_text() == "line003"

    def test_word_selection_survives_scrolling(self, terminal):
        terminal._select_word((terminal.base + 3, 2))
        terminal._scroll_to(terminal._screen.lines_scrolled)
        assert terminal._selected_text() == "line003"


class TestLineSelection:
    def test_triple_click_takes_the_whole_line(self, log_line):
        log_line._select_line((log_line.base, 3))
        assert log_line._selected_text() == "ERROR /var/log/app.log failed after 3 tries"

    @pytest.mark.parametrize("row_offset", [0, 1, 2])
    def test_triple_click_follows_soft_wraps(self, wrapped, row_offset):
        """Clicking any row of a wrapped group selects the whole logical line."""
        wrapped._select_line((wrapped.base + row_offset, 0))
        assert wrapped._selected_text() == wrapped.long_line

    def test_line_selection_stops_at_a_hard_newline(self, wrapped):
        wrapped._select_line((wrapped.base + 3, 0))   # the "short" line
        assert wrapped._selected_text() == "short"

    def test_line_selection_works_deep_in_history(self, terminal):
        terminal._select_line((terminal.base + 50, 0))
        assert terminal._selected_text() == "line050"


class TestSoftWrapJoining:
    def test_a_wrapped_line_copies_as_one_line(self, wrapped):
        select(wrapped, (wrapped.base, 0), (wrapped.base + 3, wrapped._cols - 1))
        assert wrapped._selected_text().splitlines() == [wrapped.long_line, "short"]

    def test_hard_newlines_are_preserved(self, terminal):
        select(terminal, (terminal.base, 0), (terminal.base + 2, terminal._cols - 1))
        assert terminal._selected_text().splitlines() == [
            "line000", "line001", "line002"]

    def test_an_exactly_full_line_is_not_joined(self, make_terminal):
        """The ambiguous case must not glue two log lines together."""
        term = make_terminal()
        term._stream.feed((("X" * term._cols) + "\r\nnext\r\n").encode())
        term._sync_scrollbar()
        select(term, (term.base, 0), (term.base + 1, term._cols - 1))
        assert term._selected_text().splitlines() == ["X" * term._cols, "next"]

    def test_joining_works_across_the_history_boundary(self, make_terminal):
        term = make_terminal()
        long_line = "C" * 95
        term._stream.feed((long_line + "\r\n").encode())
        # Push the wrapped group deep into history.
        for i in range(40):
            term._stream.feed(f"filler{i}\r\n".encode())
        term._sync_scrollbar()
        term._select_line((term.base, 0))
        assert term._selected_text() == long_line

    def test_partial_selection_of_a_wrapped_line(self, wrapped):
        # Only the second row of the wrapped group.
        select(wrapped, (wrapped.base + 1, 0), (wrapped.base + 1, wrapped._cols - 1))
        assert wrapped._selected_text() == "A" * wrapped._cols


class TestWideCharacters:
    def test_wide_chars_copy_without_phantom_spaces(self, make_terminal):
        term = make_terminal(cols=60)
        term._stream.feed("日本語 ok\r\n".encode())
        term._sync_scrollbar()
        term._select_line((term.base, 0))
        assert term._selected_text() == "日本語 ok"

    def test_emoji_copy_cleanly(self, make_terminal):
        term = make_terminal(cols=60)
        term._stream.feed("done ✅ ok\r\n".encode())
        term._sync_scrollbar()
        term._select_line((term.base, 0))
        assert term._selected_text() == "done ✅ ok"


class TestContextMenu:
    def test_copy_is_disabled_without_a_selection(self, terminal, monkeypatch):
        actions = {}

        def fake_exec(self, _pos=None):
            for act in self.actions():
                actions[act.text()] = act.isEnabled()
            return None

        monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", fake_exec)
        from PyQt6.QtCore import QPoint
        terminal._clear_selection()
        terminal._show_context_menu(QPoint(0, 0))
        assert actions["Copy"] is False
        assert actions["Paste"] is True
        assert actions["Select All"] is True

    def test_copy_is_enabled_with_a_selection(self, terminal, monkeypatch):
        enabled = {}

        def fake_exec(self, _pos=None):
            for act in self.actions():
                enabled[act.text()] = act.isEnabled()
            return None

        monkeypatch.setattr("PyQt6.QtWidgets.QMenu.exec", fake_exec)
        from PyQt6.QtCore import QPoint
        terminal._select_all()
        terminal._show_context_menu(QPoint(0, 0))
        assert enabled["Copy"] is True
