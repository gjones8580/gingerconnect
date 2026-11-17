"""Phase 6: keyboard scrollback navigation and selection shortcuts.

Navigation keys must move the view without disturbing the selection or
reaching the remote; ordinary typing must snap back to the live view.
"""
from __future__ import annotations

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent

from conftest import select

K = Qt.Key
M = Qt.KeyboardModifier


def key(term, k, mods=M.NoModifier, text=""):
    term.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, k, mods, text))


class TestNavigation:
    @pytest.mark.parametrize("k", [K.Key_PageUp, K.Key_PageDown,
                                   K.Key_Home, K.Key_End])
    def test_shifted_navigation_sends_nothing_to_the_remote(self, terminal, k):
        terminal.ssh.sent.clear()
        key(terminal, k, M.ShiftModifier)
        assert terminal.ssh.sent == []

    def test_shift_pageup_scrolls_back_a_screenful(self, terminal):
        before = terminal._view_top_abs()
        key(terminal, K.Key_PageUp, M.ShiftModifier)
        assert terminal._view_top_abs() == before - (terminal._rows - 1)
        assert terminal._follow is False

    def test_shift_pagedown_scrolls_forward_a_screenful(self, terminal):
        terminal._scroll_by(-50)
        before = terminal._view_top_abs()
        key(terminal, K.Key_PageDown, M.ShiftModifier)
        assert terminal._view_top_abs() == before + (terminal._rows - 1)

    def test_shift_home_jumps_to_the_oldest_line(self, terminal):
        key(terminal, K.Key_Home, M.ShiftModifier)
        assert terminal._view_top_abs() == terminal._screen.history_base

    def test_shift_end_returns_to_the_live_screen(self, terminal):
        key(terminal, K.Key_Home, M.ShiftModifier)
        key(terminal, K.Key_End, M.ShiftModifier)
        assert terminal._view_top_abs() == terminal._screen.lines_scrolled
        assert terminal._follow is True

    @pytest.mark.parametrize("k", [K.Key_PageUp, K.Key_PageDown,
                                   K.Key_Home, K.Key_End])
    def test_navigation_keeps_the_selection(self, terminal, k):
        base = terminal._screen.history_base
        select(terminal, (base, 0), (base + 3, terminal._cols - 1))
        expected = terminal._selected_text()
        key(terminal, k, M.ShiftModifier)
        assert terminal._selected_text() == expected

    @pytest.mark.parametrize("k,expected", [
        (K.Key_PageUp, b"\x1b[5~"),
        (K.Key_PageDown, b"\x1b[6~"),
        (K.Key_Home, b"\x1b[H"),
        (K.Key_End, b"\x1b[F"),
    ])
    def test_unmodified_keys_still_reach_the_remote(self, terminal, k, expected):
        key(terminal, k)
        assert terminal.ssh.sent[-1] == expected


class TestShortcuts:
    def test_ctrl_shift_a_selects_everything(self, terminal):
        key(terminal, K.Key_A, M.ControlModifier | M.ShiftModifier)
        lines = [l for l in terminal._selected_text().splitlines() if l]
        assert lines == [f"line{i:03d}" for i in range(200)]

    def test_ctrl_shift_c_copies(self, terminal, qapp):
        select(terminal, (terminal.base, 0), (terminal.base + 1, terminal._cols - 1))
        key(terminal, K.Key_C, M.ControlModifier | M.ShiftModifier)
        assert qapp.clipboard().text() == "line000\nline001"

    def test_ctrl_shift_v_pastes(self, terminal, qapp):
        qapp.clipboard().setText("pasted")
        key(terminal, K.Key_V, M.ControlModifier | M.ShiftModifier)
        assert terminal.ssh.sent[-1] == b"pasted"

    @pytest.mark.parametrize("k", [K.Key_A, K.Key_C, K.Key_V])
    def test_shortcuts_do_not_disturb_the_view(self, terminal, k):
        terminal._scroll_to(terminal._screen.history_base + 40)
        before = terminal._view_top_abs()
        key(terminal, k, M.ControlModifier | M.ShiftModifier)
        assert terminal._view_top_abs() == before

    def test_ctrl_c_still_sends_sigint(self, terminal):
        key(terminal, K.Key_C, M.ControlModifier, "c")
        assert terminal.ssh.sent[-1] == b"\x03"


class TestTypingResetsTheView:
    def test_typing_snaps_back_to_the_live_screen(self, terminal):
        terminal._scroll_to(terminal._screen.history_base)
        key(terminal, K.Key_X, M.NoModifier, "x")
        assert terminal._follow is True
        assert terminal._view_top_abs() == terminal._screen.lines_scrolled

    def test_typing_clears_the_selection(self, terminal):
        terminal._select_all()
        key(terminal, K.Key_X, M.NoModifier, "x")
        assert terminal._has_selection() is False

    def test_typing_reaches_the_remote(self, terminal):
        key(terminal, K.Key_X, M.NoModifier, "x")
        assert terminal.ssh.sent[-1] == b"x"

    def test_typing_resyncs_the_scrollbar(self, terminal):
        terminal._scroll_to(terminal._screen.history_base)
        key(terminal, K.Key_X, M.NoModifier, "x")
        bar = terminal._scrollbar
        assert bar.value() == bar.maximum()

    @pytest.mark.parametrize("k,expected", [
        (K.Key_Return, b"\r"),
        (K.Key_Tab, b"\t"),
        (K.Key_Up, b"\x1b[A"),
        (K.Key_Backspace, b"\x7f"),
    ])
    def test_special_keys_still_work(self, terminal, k, expected):
        terminal._scroll_to(terminal._screen.history_base)
        key(terminal, k)
        assert terminal.ssh.sent[-1] == expected
        assert terminal._follow is True
