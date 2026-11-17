"""Phases 1-2: the absolute line id space in ScrollbackScreen.

Every line that has ever occupied the screen gets a stable id, so callers can
anchor to a line of output rather than a row of the viewport.
"""
from __future__ import annotations

import pyte
import pytest

from gingerconnect.terminal_widget import ScrollbackScreen


def screen(cols: int = 20, rows: int = 5, history: int = 1000):
    scr = ScrollbackScreen(cols, rows, max_history=history)
    return scr, pyte.ByteStream(scr)


def feed(stream, count: int, start: int = 0, fmt: str = "line{:03d}") -> None:
    for i in range(start, start + count):
        stream.feed((fmt.format(i) + "\r\n").encode())


def text(scr: ScrollbackScreen, abs_row: int, cols: int = 20) -> str | None:
    line = scr.line_at(abs_row)
    if line is None:
        return None
    out = []
    for col in range(cols):
        char = line.get(col)
        if char is None:
            out.append(" ")
        elif char.data == "":
            continue
        else:
            out.append(char.data)
    return "".join(out).rstrip()


class TestIdSpace:
    def test_fresh_screen_starts_at_zero(self):
        scr, _ = screen()
        assert (scr.lines_scrolled, scr.history_base, scr.history_len) == (0, 0, 0)

    def test_only_scrolled_off_lines_enter_history(self):
        # 50 lines on a 5-row screen: the last 4 are still live.
        scr, st = screen()
        feed(st, 50)
        assert scr.lines_scrolled == 46
        assert scr.history_len == 46

    @pytest.mark.parametrize("abs_row,expected", [
        (0, "line000"),
        (7, "line007"),
        (45, "line045"),   # newest history line
        (46, "line046"),   # first live row
        (49, "line049"),   # last written line, still live
        (50, ""),          # live, never written
    ])
    def test_ids_resolve_across_the_history_live_boundary(self, abs_row, expected):
        scr, st = screen()
        feed(st, 50)
        assert text(scr, abs_row) == expected

    def test_ids_are_stable_under_continuing_output(self):
        scr, st = screen()
        feed(st, 50)
        snapshot = {i: text(scr, i) for i in range(40)}
        feed(st, 70, start=50)
        assert {i: text(scr, i) for i in range(40)} == snapshot

    def test_every_id_resolves_to_its_own_line(self):
        scr, st = screen()
        feed(st, 120)
        assert [i for i in range(120) if text(scr, i) != f"line{i:03d}"] == []

    def test_unknown_ids_are_unavailable(self):
        scr, st = screen()
        feed(st, 50)
        assert scr.line_at(-1) is None
        assert scr.line_at(scr.lines_scrolled + scr.lines) is None


class TestEviction:
    """A full history deque drops the oldest lines; ids must not shift."""

    def test_history_base_advances(self):
        # 40 lines on 5 rows -> 36 scrolled off; maxlen 10 keeps ids 26..35.
        scr, st = screen(history=10)
        feed(st, 40)
        assert scr.history_base == 26
        assert scr.history_len == 10

    def test_surviving_ids_keep_their_text(self):
        scr, st = screen(history=10)
        feed(st, 40)
        assert [i for i in range(26, 40) if text(scr, i) != f"line{i:03d}"] == []

    def test_evicted_ids_report_unavailable(self):
        scr, st = screen(history=10)
        feed(st, 40)
        assert scr.line_at(25) is None
        assert text(scr, 26) == "line026"


class TestResize:
    def test_row_shrink_preserves_ids(self):
        scr, st = screen(rows=10)
        feed(st, 30)
        before = {i: text(scr, i) for i in range(30)}
        scr.resize(5, 20)   # pyte drops the surplus rows off the top
        assert {i: text(scr, i) for i in range(30)} == before

    def test_row_shrink_keeps_history(self):
        scr, st = screen(rows=10)
        feed(st, 30)
        assert scr.history_len > 0
        scr.resize(5, 20)
        assert scr.history_len > 0

    def test_row_growth_preserves_ids(self):
        scr, st = screen(rows=5)
        feed(st, 30)
        before = {i: text(scr, i) for i in range(30)}
        scr.resize(12, 20)
        assert {i: text(scr, i) for i in range(30)} == before

    def test_pristine_shrink_does_not_seed_blank_history(self):
        """A tab resized before any output must not gain phantom scrollback."""
        scr, _ = screen(rows=24)
        scr.resize(12, 20)
        assert scr.history_len == 0
        assert scr.lines_scrolled == 0


class TestSoftWrap:
    def test_autowrapped_line_is_marked(self):
        scr, st = screen(cols=10)
        st.feed(b"0123456789abcde\r\n")
        assert scr.wrapped_at(0) is True
        assert scr.wrapped_at(1) is False
        assert text(scr, 0, 10) == "0123456789"
        assert text(scr, 1, 10) == "abcde"

    def test_exactly_full_line_with_hard_newline_is_not_marked(self):
        """The ambiguous case: a line that fills the width then ends."""
        scr, st = screen(cols=10)
        st.feed(b"0123456789\r\nnext\r\n")
        assert scr.wrapped_at(0) is False
        assert text(scr, 0, 10) == "0123456789"
        assert text(scr, 1, 10) == "next"

    def test_short_lines_are_not_marked(self):
        scr, st = screen(cols=10)
        st.feed(b"short\r\nalso\r\n")
        assert scr.wrapped_at(0) is False
        assert scr.wrapped_at(1) is False

    def test_wrap_flags_follow_lines_into_history(self):
        scr, st = screen(cols=10, rows=5)
        st.feed(b"0123456789abcde\r\n")
        for _ in range(10):
            st.feed(b"filler\r\n")
        assert scr.wrapped_at(0) is True   # now deep in history
        assert scr.wrapped_at(1) is False


class TestAlternateScreen:
    def test_full_screen_app_output_stays_out_of_history(self):
        scr, st = screen()
        feed(st, 10, fmt="real{}")
        scrolled, hist = scr.lines_scrolled, scr.history_len

        st.feed(b"\x1b[?1049h")
        assert scr.alt_screen is True
        feed(st, 30, fmt="vimjunk{}")
        assert scr.history_len == hist
        assert scr.lines_scrolled == scrolled

        st.feed(b"\x1b[?1049l")
        assert scr.alt_screen is False
        assert text(scr, 3) == "real3"

    @pytest.mark.parametrize("mode", [47, 1047, 1049])
    def test_each_alternate_screen_mode_is_recognised(self, mode):
        scr, st = screen()
        st.feed(f"\x1b[?{mode}h".encode())
        assert scr.alt_screen is True
        st.feed(f"\x1b[?{mode}l".encode())
        assert scr.alt_screen is False

    def test_non_private_mode_does_not_toggle_it(self):
        scr, st = screen()
        st.feed(b"\x1b[4h")      # IRM, nothing to do with the alt screen
        assert scr.alt_screen is False


class TestEraseInDisplay:
    def test_esc_3j_drops_the_scrollback(self):
        scr, st = screen()
        feed(st, 20)
        assert scr.history_len > 0
        st.feed(b"\x1b[3J")
        assert scr.history_len == 0
        assert scr.history_base == scr.lines_scrolled
        assert scr.line_at(0) is None

    def test_esc_2j_keeps_the_scrollback(self):
        scr, st = screen()
        feed(st, 20)
        hist = scr.history_len
        st.feed(b"\x1b[2J")
        assert scr.history_len == hist
        assert text(scr, 0) == "line000"
