"""Phase 4: selection lives in absolute coordinates.

This is the regression suite for the reported bug: a highlight made in a long
log must stay on the same text no matter how the viewport moves, and must not
be capped at one screenful.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QPoint

from conftest import feed_lines, row_text, select


class TestImmuneToScrolling:
    """The reported bug: scrolling must not move the highlight."""

    @pytest.fixture
    def selected(self, terminal):
        # Four lines highlighted in the middle of the viewport, at the bottom
        # of a 200-line log.
        select(terminal,
               (terminal._abs_row(2), 0),
               (terminal._abs_row(5), terminal._cols - 1))
        return terminal, terminal._selected_text()

    def test_selection_spans_the_dragged_lines(self, selected):
        _, text = selected
        assert len(text.splitlines()) == 4

    def test_scrolling_to_the_top_does_not_move_it(self, selected):
        term, text = selected
        term._scroll_to(term._screen.history_base)
        assert term._selected_text() == text

    def test_scrolling_to_the_middle_does_not_move_it(self, selected):
        term, text = selected
        term._scroll_to(term._screen.history_base + term._screen.history_len // 2)
        assert term._selected_text() == text

    def test_scrolling_back_to_live_does_not_move_it(self, selected):
        term, text = selected
        term._scroll_to(term._screen.history_base)
        term._scroll_to(term._screen.lines_scrolled)
        assert term._selected_text() == text

    @pytest.mark.parametrize("lines", [-1, -5, -30, -150, 5, 30])
    def test_scrolling_by_any_amount_does_not_move_it(self, selected, lines):
        term, text = selected
        term._scroll_to(term._screen.history_base + 60)
        term._scroll_by(lines)
        assert term._selected_text() == text

    def test_incoming_output_does_not_move_it(self, selected):
        term, text = selected
        term._scroll_to(term._screen.history_base + 30)
        feed_lines(term, 50, fmt="new{}")
        assert term._selected_text() == text

    def test_highlight_paints_on_the_rows_holding_the_text(self, terminal):
        """The painted cells must follow the text, not the viewport."""
        start = terminal.base + 100
        select(terminal, (start, 0), (start + 3, terminal._cols - 1))

        def highlighted():
            return [r for r in range(terminal._rows)
                    if terminal._is_cell_selected(terminal._abs_row(r), 0)]

        terminal._scroll_to(start - 10)
        assert highlighted() == [10, 11]
        terminal._scroll_to(start)
        assert highlighted() == [0, 1, 2, 3]
        terminal._scroll_to(start + 2)
        assert highlighted() == [0, 1]
        terminal._scroll_to(start + 50)
        assert highlighted() == []

    def test_every_highlighted_row_is_inside_the_selection(self, terminal):
        start = terminal.base + 100
        select(terminal, (start, 0), (start + 3, terminal._cols - 1))
        for view_top in (start - 11, start - 5, start, start + 2):
            terminal._scroll_to(view_top)
            for row in range(terminal._rows):
                abs_row = terminal._abs_row(row)
                if terminal._is_cell_selected(abs_row, 0):
                    assert start <= abs_row <= start + 3


class TestBeyondOneScreenful:
    def test_whole_log_can_be_selected(self, terminal):
        select(terminal, (terminal.base, 0),
               (terminal.base + 199, terminal._cols - 1))
        lines = terminal._selected_text().splitlines()
        assert lines == [f"line{i:03d}" for i in range(200)]

    def test_selection_exceeds_the_viewport_height(self, terminal):
        select(terminal, (terminal.base, 0),
               (terminal.base + 199, terminal._cols - 1))
        assert len(terminal._selected_text().splitlines()) > terminal._rows

    def test_selection_spanning_history_and_live_screen(self, terminal):
        screen = terminal._screen
        start = screen.lines_scrolled - 5      # last 5 history lines
        end = screen.lines_scrolled + 3        # into the live screen
        select(terminal, (start, 0), (end, terminal._cols - 1))
        lines = terminal._selected_text().splitlines()
        assert lines[0] == row_text(terminal, start)
        assert len([l for l in lines if l]) == end - start + 1   # inclusive

    def test_select_all_takes_the_whole_log(self, terminal):
        terminal._select_all()
        lines = [l for l in terminal._selected_text().splitlines() if l]
        assert lines == [f"line{i:03d}" for i in range(200)]

    def test_lines_aged_out_of_history_are_skipped(self, make_terminal):
        term = make_terminal()
        term._screen._scrollback = type(term._screen._scrollback)(
            term._screen._scrollback, maxlen=30)
        term._screen._scrollback_wrapped = type(term._screen._scrollback_wrapped)(
            term._screen._scrollback_wrapped, maxlen=30)
        feed_lines(term, 200)
        select(term, (0, 0), (term._screen.lines_scrolled, term._cols - 1))
        lines = [l for l in term._selected_text().splitlines() if l]
        # Only what survives in history plus the live screen.
        assert len(lines) <= 30 + term._rows
        assert lines[0] == row_text(term, term._screen.history_base)


class TestDragging:
    def test_drag_tracks_the_pointer(self, terminal):
        anchor = terminal._pixel_to_cell(QPoint(0, 2 * terminal._ch))
        terminal._sel_anchor = anchor
        terminal._selecting = True
        terminal._extend_selection(QPoint(terminal._cols * terminal._cw,
                                          5 * terminal._ch))
        assert len(terminal._selected_text().splitlines()) == 4

    def test_wheel_scroll_mid_drag_extends_past_the_viewport(self, terminal):
        press = terminal._pixel_to_cell(
            QPoint(terminal._cols * terminal._cw, 8 * terminal._ch))
        terminal._sel_anchor = press
        terminal._selecting = True

        terminal._scroll_by(-50)               # wheel up while still dragging
        drag = terminal._pixel_to_cell(QPoint(0, 0))
        terminal._sel_end = drag
        terminal._sel_active = True

        lines = terminal._selected_text().splitlines()
        assert len(lines) > 50
        assert lines == [f"line{i - terminal.base:03d}"
                         for i in range(drag[0], press[0] + 1)]

    def test_shift_click_extends_an_existing_selection(self, terminal, qapp):
        from PyQt6.QtCore import QEvent, QPointF, Qt
        from PyQt6.QtGui import QMouseEvent

        select(terminal, (terminal.base + 10, 0),
               (terminal.base + 12, terminal._cols - 1))
        terminal._scroll_to(terminal.base + 100)

        event = QMouseEvent(
            QEvent.Type.MouseButtonPress,
            QPointF(terminal._cols * terminal._cw, 3 * terminal._ch),
            QPointF(0, 0), Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier,
        )
        terminal.mousePressEvent(event)

        lines = terminal._selected_text().splitlines()
        assert len(lines) > terminal._rows
        assert lines[0] == "line010"

    def test_bare_click_selects_nothing(self, terminal):
        cell = terminal._pixel_to_cell(QPoint(5 * terminal._cw, 3 * terminal._ch))
        terminal._sel_anchor = cell
        terminal._sel_end = cell
        terminal._sel_active = False
        assert terminal._has_selection() is False
        assert terminal._selected_text() == ""
        assert terminal._is_cell_selected(*cell) is False


class TestCopy:
    def test_copy_puts_the_selection_on_the_clipboard(self, terminal, qapp):
        select(terminal, (terminal.base, 0), (terminal.base + 2, terminal._cols - 1))
        terminal._copy_selection()
        assert qapp.clipboard().text() == "line000\nline001\nline002"

    def test_copy_survives_a_scroll_between_select_and_copy(self, terminal, qapp):
        select(terminal, (terminal.base + 80, 0),
               (terminal.base + 83, terminal._cols - 1))
        terminal._scroll_to(terminal._screen.history_base)
        terminal._copy_selection()
        assert qapp.clipboard().text() == (
            "line080\nline081\nline082\nline083")

    def test_copy_with_no_selection_leaves_the_clipboard_alone(self, terminal, qapp):
        qapp.clipboard().setText("untouched")
        terminal._clear_selection()
        terminal._copy_selection()
        assert qapp.clipboard().text() == "untouched"

    def test_partial_first_and_last_lines(self, terminal):
        select(terminal, (terminal.base, 4), (terminal.base + 2, 2))
        assert terminal._selected_text().splitlines() == ["000", "line001", "lin"]

    def test_trailing_blanks_are_trimmed(self, terminal):
        select(terminal, (terminal.base, 0), (terminal.base, terminal._cols - 1))
        assert terminal._selected_text() == "line000"


class TestPaste:
    def test_paste_sends_clipboard_text_to_the_remote(self, terminal, qapp):
        qapp.clipboard().setText("hello world")
        terminal._paste_clipboard()
        assert terminal.ssh.sent[-1] == b"hello world"

    def test_paste_of_empty_clipboard_sends_nothing(self, terminal, qapp):
        qapp.clipboard().setText("")
        terminal.ssh.sent.clear()
        terminal._paste_clipboard()
        assert terminal.ssh.sent == []


class TestRepaint:
    @pytest.mark.parametrize("offset", [0, 1, 50, 150, 188])
    def test_painting_a_scrolled_view_with_a_selection(self, terminal, offset):
        terminal._select_all()
        terminal._scroll_to(terminal._screen.history_base + offset)
        terminal.repaint()   # must not raise
