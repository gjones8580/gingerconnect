"""Phase 3: the viewport is a window onto the id space, not the coord system.

While scrolled back the view is pinned to an absolute line, so incoming
output no longer drags it along.
"""
from __future__ import annotations

from conftest import feed_lines, row_text


class TestFollowMode:
    def test_new_terminal_follows_the_live_screen(self, make_terminal):
        term = make_terminal()
        assert term._follow is True
        assert term._view_top_abs() == term._screen.lines_scrolled

    def test_scrolling_back_leaves_follow_mode(self, terminal):
        terminal._scroll_by(-10)
        assert terminal._follow is False

    def test_scrolling_to_the_bottom_re_arms_follow(self, terminal):
        terminal._scroll_by(-10)
        terminal._scroll_by(10)
        assert terminal._follow is True

    def test_following_view_tracks_new_output(self, terminal):
        before = terminal._view_top_abs()
        feed_lines(terminal, 10, fmt="more{}")
        assert terminal._view_top_abs() == before + 10


class TestPinning:
    def test_scrolled_back_view_ignores_incoming_output(self, terminal):
        terminal._scroll_to(terminal._screen.history_base + 20)
        pinned = terminal._view_top_abs()
        top_line = terminal._screen.line_at(pinned)

        feed_lines(terminal, 60, fmt="new{}")

        assert terminal._view_top_abs() == pinned
        assert terminal._screen.line_at(pinned) == top_line
        assert terminal._follow is False

    def test_pinned_view_shows_the_same_text_after_output(self, terminal):
        terminal._scroll_to(terminal._screen.history_base + 20)
        visible = [row_text(terminal, terminal._abs_row(r))
                   for r in range(terminal._rows)]
        feed_lines(terminal, 60, fmt="new{}")
        assert [row_text(terminal, terminal._abs_row(r))
                for r in range(terminal._rows)] == visible


class TestScrollClamping:
    def test_cannot_scroll_past_the_oldest_line(self, terminal):
        terminal._scroll_by(-10_000)
        assert terminal._view_top_abs() == terminal._screen.history_base

    def test_cannot_scroll_past_the_live_screen(self, terminal):
        terminal._scroll_by(10_000)
        assert terminal._view_top_abs() == terminal._screen.lines_scrolled
        assert terminal._follow is True

    def test_view_is_clamped_when_history_is_evicted(self, make_terminal):
        term = make_terminal()
        term._screen._scrollback = type(term._screen._scrollback)(
            term._screen._scrollback, maxlen=20)
        feed_lines(term, 100)
        term._scroll_to(term._screen.history_base)
        feed_lines(term, 100, fmt="push{}")
        # The pinned line aged out; the view must land on the oldest survivor.
        assert term._view_top_abs() >= term._screen.history_base

    def test_empty_history_pins_the_view(self, make_terminal):
        term = make_terminal()
        term._scroll_by(-50)
        assert term._view_top_abs() == term._screen.lines_scrolled


class TestWheel:
    def _wheel(self, term, notches):
        from PyQt6.QtCore import QPoint, QPointF
        from PyQt6.QtGui import QWheelEvent
        from PyQt6.QtCore import Qt
        event = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0),
            QPoint(0, 120 * notches), Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
        )
        term.wheelEvent(event)

    def test_wheel_up_scrolls_toward_older_output(self, terminal):
        before = terminal._view_top_abs()
        self._wheel(terminal, 1)
        assert terminal._view_top_abs() == before - 3

    def test_wheel_down_scrolls_toward_newer_output(self, terminal):
        terminal._scroll_by(-30)
        before = terminal._view_top_abs()
        self._wheel(terminal, -1)
        assert terminal._view_top_abs() == before + 3

    def test_wheel_is_inert_on_the_alternate_screen(self, terminal):
        terminal._stream.feed(b"\x1b[?1049h")
        before = terminal._view_top_abs()
        self._wheel(terminal, 1)
        assert terminal._view_top_abs() == before


class TestScrollbar:
    def test_range_matches_the_history_span(self, terminal):
        screen = terminal._screen
        assert terminal._scrollbar.maximum() == (
            screen.lines_scrolled - screen.history_base)

    def test_sits_at_the_bottom_while_following(self, terminal):
        bar = terminal._scrollbar
        assert bar.value() == bar.maximum()

    def test_page_step_is_one_screenful(self, terminal):
        assert terminal._scrollbar.pageStep() == terminal._rows

    def test_hidden_until_there_is_history(self, make_terminal):
        term = make_terminal()
        term._sync_scrollbar()
        assert term._scrollbar.isVisible() is False

    def test_shown_once_lines_scroll_off(self, terminal):
        assert terminal._scrollbar.isVisible() is True

    def test_dragging_it_scrolls_the_view(self, terminal, qapp):
        terminal._scrollbar.setValue(0)
        qapp.processEvents()
        assert terminal._view_top_abs() == terminal._screen.history_base
        assert terminal._follow is False

    def test_dragging_to_the_bottom_re_arms_follow(self, terminal, qapp):
        bar = terminal._scrollbar
        bar.setValue(0)
        qapp.processEvents()
        bar.setValue(bar.maximum())
        qapp.processEvents()
        assert terminal._follow is True

    def test_tracks_the_view_when_scrolled_by_other_means(self, terminal):
        terminal._scroll_to(terminal._screen.history_base + 7)
        assert terminal._scrollbar.value() == 7

    def test_does_not_steal_keyboard_focus(self, terminal):
        from PyQt6.QtCore import Qt
        assert terminal._scrollbar.focusPolicy() == Qt.FocusPolicy.NoFocus


class TestCursorVisibility:
    def test_cursor_row_known_while_following(self, terminal):
        assert terminal._cursor_display_row() is not None

    def test_cursor_hidden_when_scrolled_well_back(self, terminal):
        terminal._scroll_to(terminal._screen.history_base)
        assert terminal._cursor_display_row() is None

    def test_cursor_on_the_bottom_row_hides_on_any_scrollback(self, terminal):
        assert terminal._screen.cursor.y == terminal._rows - 1
        terminal._scroll_by(-1)
        assert terminal._cursor_display_row() is None

    def test_cursor_still_shown_when_its_line_is_in_view(self, terminal):
        terminal._stream.feed(b"\x1b[1;1H")      # park the cursor at the top
        assert terminal._screen.cursor.y == 0
        terminal._scroll_by(-5)
        assert terminal._cursor_display_row() == 5


class TestGutter:
    def test_columns_exclude_the_scrollbar_gutter(self, terminal):
        assert terminal._cols == (terminal.width() - terminal._sb_w) // terminal._cw

    def test_resize_keeps_the_scrollback(self, terminal):
        before = terminal._screen.history_len
        terminal.resize(terminal.width(), terminal.height() + 5 * terminal._ch)
        terminal.parent() or terminal.show()
        assert terminal._screen.history_len >= before
        assert row_text(terminal, terminal.base) == "line000"

    def test_resize_notifies_the_remote(self, terminal, qapp):
        terminal.ssh.resizes.clear()
        terminal.resize(terminal.width() + 10 * terminal._cw, terminal.height())
        qapp.processEvents()
        assert terminal.ssh.resizes
        assert terminal.ssh.resizes[-1][0] == terminal._cols
