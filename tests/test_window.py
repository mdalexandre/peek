"""R1 and R4: the file window, its header, clamping, clipping and range errors."""

from __future__ import annotations

import shlex
from pathlib import Path

import pytest
from conftest import LAUNCHER, Peek, numbered_text, text_from_lengths

THREE = ["exit 2, 0 lines, 0 bytes"]


def body(res):
    return res.lines[1:-1]


def test_default_window_is_lines_1_to_100_of_file_with_250_lines(peek: Peek, mk):
    """R1: a bare peek file shows lines 1 to 100 of a 250 line file."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f))
    assert r.code == 0
    assert r.first == "lines 1 to 100 of 250"
    assert body(r) == [f"L{i}" for i in range(1, 101)]
    assert r.last == f"next: {LAUNCHER.resolve()} file {shlex.quote(str(f))} --lines 101:200"


def test_window_includes_line_reaching_exactly_16000_chars(peek: Peek, mk):
    """R1: a window whose shown text reaches exactly 16000 chars keeps that line."""
    f = mk("f.txt", text_from_lengths([160] * 150))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 100 of 150"
    assert len(body(r)) == 100


def test_window_excludes_line_that_would_reach_16001_chars(peek: Peek, mk):
    """R1: the line that would bring the shown text to 16001 chars is left out."""
    lengths = [160] * 150
    lengths[99] = 161
    f = mk("f.txt", text_from_lengths(lengths))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 99 of 150"
    assert len(body(r)) == 99


def test_window_ends_early_at_40_lines_of_400_chars_and_header_shows_actual_b(peek: Peek, mk):
    """R1: 100 lines of 500 chars: the window ends at line 40 and the header says so."""
    f = mk("f.txt", text_from_lengths([500] * 100))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 40 of 100"
    b = body(r)
    assert len(b) == 40
    assert all(
        x.endswith(" [cut: 500 chars]") and len(x) == 400 + len(" [cut: 500 chars]") for x in b
    )


def test_lines_1_to_100_is_not_clipped(peek: Peek, mk):
    """R1: --lines 1:100 is exactly 100 lines, so no clipped line."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "1:100")
    assert r.first == "lines 1 to 100 of 250"
    assert not any(x.startswith("clipped:") for x in r.lines)
    assert r.lines[1] == "L1"


def test_lines_1_to_101_is_clipped_with_second_line_clipped_requested_1_101(peek: Peek, mk):
    """R1: --lines 1:101 is clipped to 100 lines with `clipped: requested 1:101` second."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "1:101")
    assert r.first == "lines 1 to 100 of 250"
    assert r.lines[1] == "clipped: requested 1:101"
    assert len(r.lines[2:-1]) == 100


def test_clipped_window_for_10_to_500_is_lines_10_to_109(peek: Peek, mk):
    """R1: --lines 10:500 on 250 lines becomes lines 10 to 109, clipped."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "10:500")
    assert r.first == "lines 10 to 109 of 250"
    assert r.lines[1] == "clipped: requested 10:500"
    assert r.lines[2] == "L10"
    assert r.lines[-2] == "L109"


def test_clipped_line_shows_original_b_when_b_exceeds_n(peek: Peek, mk):
    """R1: the clipped line keeps the original B even when B is beyond N."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "1:9999")
    assert r.lines[1] == "clipped: requested 1:9999"
    assert r.first == "lines 1 to 100 of 250"


def test_no_clipped_line_when_b_beyond_n_but_clamped_window_is_within_100(peek: Peek, mk):
    """R1: --lines 100:500 on 150 lines clamps to 51 lines, so no clipped line."""
    f = mk("f.txt", numbered_text(150))
    r = peek("file", str(f), "--lines", "100:500")
    assert r.first == "lines 100 to 150 of 150"
    assert not any(x.startswith("clipped:") for x in r.lines)
    assert r.last == "end: lines 100 to 150 of 150"


def test_no_clipped_line_when_window_shortened_only_by_char_budget(peek: Peek, mk):
    """R1: a 100 line request cut short by the char budget is not clipped."""
    f = mk("f.txt", text_from_lengths([500] * 100))
    r = peek("file", str(f), "--lines", "1:100")
    assert r.first == "lines 1 to 40 of 100"
    assert not any(x.startswith("clipped:") for x in r.lines)


def test_b_above_n_is_clamped_silently_header_shows_n(peek: Peek, mk):
    """R1: B above N is clamped silently and the header shows N."""
    f = mk("f.txt", numbered_text(30))
    r = peek("file", str(f), "--lines", "1:50")
    assert r.first == "lines 1 to 30 of 30"
    assert not any(x.startswith("clipped:") for x in r.lines)
    assert r.last == "end: lines 1 to 30 of 30"


def test_lines_clipped_to_100_when_only_second_line_differs_from_unclipped_output(peek: Peek, mk):
    """R1: the 1:101 output equals the 1:100 output plus the clipped second line."""
    f = mk("f.txt", numbered_text(250))
    a = peek("file", str(f), "--lines", "1:100")
    b = peek("file", str(f), "--lines", "1:101")
    assert b.lines == [a.lines[0], "clipped: requested 1:101", *a.lines[1:]]


def test_first_line_is_lines_a_to_b_of_n_for_a_250_line_file(peek: Peek, mk):
    """R4: lines 120 to 130 of a 250 line file starts with `lines 120 to 130 of 250`."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "120:130")
    assert r.first == "lines 120 to 130 of 250"
    assert body(r) == [f"L{i}" for i in range(120, 131)]
    assert r.last.endswith("--lines 131:230")


def test_window_ending_exactly_at_end_of_file_prints_end_line_and_no_next(peek: Peek, mk):
    """R4: a window ending at line N prints `end: lines A to N of N` and no next."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "151:250")
    assert r.first == "lines 151 to 250 of 250"
    assert r.last == "end: lines 151 to 250 of 250"
    assert not any(x.startswith("next:") for x in r.lines)


def test_window_of_101_line_file_ends_at_100_with_next_101_to_200(peek: Peek, mk):
    """R4: a 101 line file shows 1 to 100 and then next 101:200."""
    f = mk("f.txt", numbered_text(101))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 100 of 101"
    assert r.last.startswith("next: ")
    assert r.last.endswith("--lines 101:200")


def test_single_last_line_window_300_to_300_of_300(peek: Peek, mk):
    """R4: --lines 300:300 of a 300 line file shows the last line and an end line."""
    f = mk("f.txt", numbered_text(300))
    r = peek("file", str(f), "--lines", "300:300")
    assert r.lines == ["lines 300 to 300 of 300", "L300", "end: lines 300 to 300 of 300"]


def test_last_line_without_trailing_newline_counts_as_a_line(peek: Peek, mk):
    """R4: an unterminated last line is a line."""
    f = mk("f.txt", "a\nb\nc")
    r = peek("file", str(f))
    assert r.lines == ["lines 1 to 3 of 3", "a", "b", "c", "end: lines 1 to 3 of 3"]


def test_file_ending_with_blank_line_counts_that_blank_line(peek: Peek, mk):
    """R4: a\\nb\\n\\n is three lines, the last one empty."""
    f = mk("f.txt", "a\nb\n\n")
    r = peek("file", str(f))
    assert r.lines == ["lines 1 to 3 of 3", "a", "b", "", "end: lines 1 to 3 of 3"]


def test_file_containing_only_a_newline_is_one_empty_line_not_an_empty_file(peek: Peek, mk):
    """R4: a file of one newline is one empty line."""
    f = mk("f.txt", "\n")
    r = peek("file", str(f))
    assert r.lines == ["lines 1 to 1 of 1", "", "end: lines 1 to 1 of 1"]


EMPTY = ["lines 0 to 0 of 0", "no output: file is empty", "end: lines 0 to 0 of 0"]


def test_empty_file_output_is_exactly_three_fixed_lines(peek: Peek, mk):
    """R4: an empty file prints exactly the three fixed lines and exits 0."""
    f = mk("e.txt", b"")
    r = peek("file", str(f))
    assert r.code == 0
    assert r.lines == EMPTY
    assert r.text.endswith("lines 0 to 0 of 0\n")


def test_empty_file_ignores_valid_lines_option(peek: Peek, mk):
    """R4: --lines is ignored on an empty file."""
    f = mk("e.txt", b"")
    r = peek("file", str(f), "--lines", "5:9")
    assert r.code == 0
    assert r.lines == EMPTY


@pytest.mark.parametrize("value", ["0:0", "5:2", "abc", "1:2:3"])
def test_empty_file_ignores_bad_lines_option(peek: Peek, mk, value):
    """R4: an invalid --lines value on an empty file is ignored too."""
    f = mk("e.txt", b"")
    r = peek("file", str(f), "--lines", value)
    assert r.code == 0
    assert r.lines == EMPTY


def test_a_equals_n_plus_1_is_range_past_end_with_n_in_message(peek: Peek, mk):
    """R4: A = N+1 is `error: range past end of file (N lines)`, exit 2."""
    f = mk("f.txt", numbered_text(10))
    r = peek("file", str(f), "--lines", "11:12")
    assert r.code == 2
    assert r.lines == [*THREE, "error: range past end of file (10 lines)", "done"]


def test_a_far_past_end_with_huge_integers_is_range_past_end(peek: Peek, mk):
    """R4: huge integers are plain decimals, so the error is range past end."""
    f = mk("f.txt", numbered_text(10))
    r = peek("file", str(f), "--lines", "99999999999999999999:999999999999999999999999")
    assert r.code == 2
    assert r.lines == [*THREE, "error: range past end of file (10 lines)", "done"]


BAD = {
    "0:5": "0:5",
    "1:0": "1:0",
    "5:3": "5:3",
    "1": "1",
    "1:2:3": "1:2:3",
    "a:b": "a:b",
    "+1:5": "+1:5",
    "1:+5": "1:+5",
    "-1:5": "-1:5",
    "01:5": "01:5",
    "1:05": "1:05",
    "1:": "1:",
    ":5": ":5",
    "empty": "",
    "space_padded": " 1:5 ",
    "arabic_digits": "١:٥",
    "1.5:3": "1.5:3",
}


@pytest.mark.parametrize("value", list(BAD.values()), ids=list(BAD))
def test_bad_range_forms_exit_2_error_bad_range(peek: Peek, mk, value):
    """R4: every malformed --lines value is `error: bad range` with exit 2."""
    f = mk("f.txt", numbered_text(10))
    r = peek("file", str(f), "--lines", value)
    assert r.code == 2
    assert r.lines == [*THREE, "error: bad range", "done"]


def test_lines_equal_a_and_b_shows_one_line_window(peek: Peek, mk):
    """R4: --lines 5:5 shows exactly line 5."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "5:5")
    assert r.first == "lines 5 to 5 of 250"
    assert body(r) == ["L5"]


def test_lines_only_split_on_newline_not_on_form_feed_vt_or_unicode_separators(peek: Peek, mk):
    """R4: form feed, vertical tab, U+2028 and U+0085 do not split lines."""
    odd = "a\x0cb\x0bc d\x85e"
    f = mk("f.txt", odd + "\nsecond\n")
    r = peek("file", str(f))
    assert r.first == "lines 1 to 2 of 2"
    assert r.lines[1] == odd
    assert r.lines[2] == "second"


def test_crlf_file_keeps_trailing_cr_in_displayed_line(peek: Peek, mk):
    """R4: a CRLF file keeps the carriage return as part of each line."""
    f = mk("f.txt", b"a\r\nb\r\n")
    r = peek("file", str(f))
    assert r.lines == ["lines 1 to 2 of 2", "a\r", "b\r", "end: lines 1 to 2 of 2"]


def test_invalid_utf8_bytes_are_replaced_and_do_not_crash(peek: Peek, mk):
    """R4: invalid UTF-8 becomes U+FFFD and the output is valid UTF-8."""
    f = mk("f.txt", b"ok\xff\xfe line\nsecond\n")
    r = peek("file", str(f))
    assert r.code == 0
    assert r.first == "lines 1 to 2 of 2"
    assert r.lines[1] == "ok�� line"
    assert r.err == b""


def test_window_path_is_used_as_given(peek: Peek, mk, cwd: Path):
    """R4: a relative PATH is read relative to the working directory."""
    (cwd / "rel.txt").write_text("x\n")
    r = peek("file", "rel.txt")
    assert r.lines == ["lines 1 to 1 of 1", "x", "end: lines 1 to 1 of 1"]
