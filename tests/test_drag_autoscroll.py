"""Phase 5: dragging past the top or bottom edge auto-scrolls the view.

The selection keeps extending while the pointer is held outside the widget,
so a selection longer than the window can be made in one gesture.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, QPoint, QPointF, Qt
from PyQt6.QtGui import QMouseEvent

from conftest import feed_lines


def press(term, x: int, y: int) -> None:
    term.mousePressEvent(QMouseEvent(
        QEvent.Type.MouseButtonPress, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def move(term, x: int, y: int) -> None:
    term.mouseMoveEvent(QMouseEvent(
        QEvent.Type.MouseMove, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
        Qt.KeyboardModifier.NoModifier,
    ))


def release(term, x: int, y: int) -> None:
    term.mouseReleaseEvent(QMouseEvent(
        QEvent.Type.MouseButtonRelease, QPointF(x, y), QPointF(x, y),
        Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
    ))


class TestSpeedCurve:
    def test_inside_the_viewport_does_not_scroll(self, terminal):
        for y in (0, 1, terminal._ch, terminal.height() // 2,
                  terminal.height() - 1):
            assert terminal._autoscroll_lines(y) == 0

    def test_above_the_top_scrolls_toward_older_output(self, terminal):
        assert terminal._autoscroll_lines(-1) < 0

    def test_below_the_bottom_scrolls_toward_newer_output(self, terminal):
        assert terminal._autoscroll_lines(terminal.height()) > 0

    def test_speed_grows_with_distance(self, terminal):
        near = abs(terminal._autoscroll_lines(-1))
        far = abs(terminal._autoscroll_lines(-4 * terminal._ch))
        assert far > near

    def test_speed_is_capped(self, terminal):
        from gingerconnect.terminal_widget import _AUTOSCROLL_MAX_LINES
        assert abs(terminal._autoscroll_lines(-100_000)) == _AUTOSCROLL_MAX_LINES
        assert abs(terminal._autoscroll_lines(terminal.height() + 100_000)) == (
            _AUTOSCROLL_MAX_LINES)

    @pytest.mark.parametrize("y_offset,expected_sign", [(-1, -1), (1, 1)])
    def test_symmetric_about_the_edges(self, terminal, y_offset, expected_sign):
        y = y_offset if y_offset < 0 else terminal.height() - 1 + y_offset
        assert terminal._autoscroll_lines(y) * expected_sign > 0


class TestTimerLifecycle:
    def test_dragging_inside_does_not_start_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, 3 * terminal._ch)
        assert terminal._autoscroll_timer.isActive() is False

    def test_dragging_above_the_top_starts_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -20)
        assert terminal._autoscroll_timer.isActive() is True

    def test_dragging_below_the_bottom_starts_the_timer(self, terminal):
        terminal._scroll_by(-50)
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, terminal.height() + 20)
        assert terminal._autoscroll_timer.isActive() is True

    def test_moving_back_inside_stops_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -20)
        move(terminal, 10, 4 * terminal._ch)
        assert terminal._autoscroll_timer.isActive() is False

    def test_release_stops_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -20)
        release(terminal, 10, -20)
        assert terminal._autoscroll_timer.isActive() is False
        assert terminal._selecting is False

    def test_reaching_the_oldest_line_stops_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -1000)
        for _ in range(500):
            terminal._autoscroll_tick()
            if not terminal._autoscroll_timer.isActive():
                break
        assert terminal._view_top_abs() == terminal._screen.history_base
        assert terminal._autoscroll_timer.isActive() is False

    def test_a_new_press_cancels_a_stale_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -20)
        press(terminal, 0, 5 * terminal._ch)
        assert terminal._autoscroll_timer.isActive() is False

    def test_closing_the_connection_stops_the_timer(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -20)
        terminal.close_connection()
        assert terminal._autoscroll_timer.isActive() is False

    def test_timer_really_fires(self, terminal, qapp):
        """Integration check: the timer is wired up, not just configured."""
        from PyQt6.QtTest import QTest
        press(terminal, 0, 5 * terminal._ch)
        before = terminal._view_top_abs()
        move(terminal, 10, -20)
        QTest.qWait(200)
        qapp.processEvents()
        assert terminal._view_top_abs() < before


class TestSelectionGrowth:
    def test_dragging_up_extends_the_selection_past_the_viewport(self, terminal):
        press(terminal, terminal._cols * terminal._cw, 8 * terminal._ch)
        move(terminal, 0, -30)
        for _ in range(20):
            terminal._autoscroll_tick()
        lines = terminal._selected_text().splitlines()
        assert len(lines) > terminal._rows

    def test_the_extended_selection_stays_contiguous(self, terminal):
        anchor_y = 8 * terminal._ch
        press(terminal, terminal._cols * terminal._cw, anchor_y)
        anchor = terminal._sel_anchor
        move(terminal, 0, -30)
        for _ in range(20):
            terminal._autoscroll_tick()
        start = terminal._sel_end[0]
        lines = terminal._selected_text().splitlines()
        assert lines == [f"line{i - terminal.base:03d}"
                         for i in range(start, anchor[0] + 1)]

    def test_the_anchor_never_moves(self, terminal):
        press(terminal, terminal._cols * terminal._cw, 8 * terminal._ch)
        anchor = terminal._sel_anchor
        move(terminal, 0, -30)
        for _ in range(20):
            terminal._autoscroll_tick()
        assert terminal._sel_anchor == anchor

    def test_the_selection_only_grows(self, terminal):
        press(terminal, terminal._cols * terminal._cw, 8 * terminal._ch)
        move(terminal, 0, -30)
        sizes = []
        for _ in range(15):
            terminal._autoscroll_tick()
            sizes.append(len(terminal._selected_text().splitlines()))
        assert sizes == sorted(sizes)
        assert sizes[-1] > sizes[0]

    def test_dragging_down_walks_back_toward_live(self, terminal):
        terminal._scroll_to(terminal._screen.history_base)
        press(terminal, 0, 2 * terminal._ch)
        move(terminal, terminal._cols * terminal._cw, terminal.height() + 30)
        before = terminal._view_top_abs()
        for _ in range(20):
            terminal._autoscroll_tick()
        assert terminal._view_top_abs() > before
        assert len(terminal._selected_text().splitlines()) > terminal._rows

    def test_an_autoscrolled_selection_copies_in_full(self, terminal, qapp):
        press(terminal, terminal._cols * terminal._cw, 8 * terminal._ch)
        move(terminal, 0, -30)
        for _ in range(30):
            terminal._autoscroll_tick()
        terminal._copy_selection()
        copied = qapp.clipboard().text().splitlines()
        assert copied == terminal._selected_text().splitlines()
        assert len(copied) > terminal._rows


class TestTickGuards:
    def test_tick_without_a_drag_is_a_no_op(self, terminal):
        terminal._selecting = False
        terminal._drag_pos = None
        before = terminal._view_top_abs()
        terminal._autoscroll_tick()
        assert terminal._view_top_abs() == before
        assert terminal._autoscroll_timer.isActive() is False

    def test_tick_with_the_pointer_back_inside_is_a_no_op(self, terminal):
        press(terminal, 0, 5 * terminal._ch)
        terminal._drag_pos = QPoint(0, 5 * terminal._ch)
        before = terminal._view_top_abs()
        terminal._autoscroll_tick()
        assert terminal._view_top_abs() == before

    def test_autoscroll_is_inert_on_the_alternate_screen(self, terminal):
        terminal._stream.feed(b"\x1b[?1049h")
        press(terminal, 0, 5 * terminal._ch)
        move(terminal, 10, -50)
        before = terminal._view_top_abs()
        terminal._autoscroll_tick()
        assert terminal._view_top_abs() == before

    def test_live_output_during_autoscroll_does_not_break_the_selection(self, terminal):
        press(terminal, terminal._cols * terminal._cw, 8 * terminal._ch)
        anchor = terminal._sel_anchor
        move(terminal, 0, -30)
        for _ in range(10):
            terminal._autoscroll_tick()
            feed_lines(terminal, 2, fmt="noise{}")
        assert terminal._sel_anchor == anchor
        lines = terminal._selected_text().splitlines()
        start = terminal._sel_end[0]
        assert lines == [f"line{i - terminal.base:03d}"
                         for i in range(start, anchor[0] + 1)]
