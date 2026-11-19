"""R1: the 400 character cut and the output size ceilings, in both commands."""

from __future__ import annotations

import re
from pathlib import Path

from conftest import BODY, Peek, lines_cmd, numbered_text, parse_capped, text_from_lengths


def test_cut_line_leaves_400_char_line_unchanged():
    """R1: a line of exactly 400 chars is not cut."""
    from peek.render import cut_line

    s = "a" * 400
    assert cut_line(s) == s


def test_cut_line_cuts_401_char_line_to_400_chars_plus_suffix_cut_401_chars():
    """R1: a 401 char line becomes 400 chars plus ` [cut: 401 chars]`."""
    from peek.render import cut_line

    assert cut_line("a" * 401) == "a" * 400 + " [cut: 401 chars]"


def test_cut_line_one_very_long_line_100000_chars_keeps_400_and_reports_100000():
    """R1: a 100000 char line keeps 400 chars and reports 100000."""
    from peek.render import cut_line

    assert cut_line("x" * 100000) == "x" * 400 + " [cut: 100000 chars]"


def test_cut_line_counts_code_points_not_bytes():
    """R1: 400 two byte chars are not cut, 401 are, and N counts code points."""
    from peek.render import cut_line

    assert cut_line("é" * 400) == "é" * 400
    assert cut_line("é" * 401) == "é" * 400 + " [cut: 401 chars]"
    assert cut_line("\U0001f600" * 401) == "\U0001f600" * 400 + " [cut: 401 chars]"


def test_trailing_cr_is_content_so_399_chars_plus_cr_is_not_cut(peek: Peek, mk):
    """R1: 399 chars plus CR is 400 and stays; 400 chars plus CR is 401 and is cut."""
    f = mk("f.txt", "a" * 399 + "\r\n" + "b" * 400 + "\r\n")
    r = peek("file", str(f))
    assert r.lines[1] == "a" * 399 + "\r"
    assert r.lines[2] == "b" * 400 + " [cut: 401 chars]"


def test_cut_applies_to_every_displayed_line_of_peek_file(peek: Peek, mk):
    """R1: every displayed line of peek file over 400 chars is cut."""
    f = mk("f.txt", text_from_lengths([500] * 5))
    r = peek("file", str(f))
    shown = r.lines[1:-1]
    assert len(shown) == 5
    for x in shown:
        assert re.fullmatch(r"L\d+x+ \[cut: 500 chars\]", x) and len(x) == 400 + 17


def test_cut_applies_to_every_line_of_an_uncapped_run(peek: Peek):
    """R1: an uncapped run cuts each of its long lines."""
    r = peek("run", "--", *lines_cmd(10, 450))
    assert r.first.startswith("exit 0, 10 lines, ")
    assert r.last == "done"
    assert len(r.lines[1:-1]) == 10
    assert all(x.endswith(" [cut: 450 chars]") for x in r.lines[1:-1])


def test_cut_applies_to_capped_head_and_tail_lines(peek: Peek):
    """R1: head and tail lines of a capped run are cut."""
    r = peek("run", "--", *lines_cmd(60, 450))
    c = parse_capped(r)
    assert c.head and c.tail
    assert all(BODY.match(x) and x.endswith(" [cut: 450 chars]") for x in c.head + c.tail)


def test_cut_not_applied_to_header_full_output_and_next_lines_even_over_400_chars(
    peek: Peek, isolated_tmp: Path
):
    """R1: header, full output and next lines stay whole even when longer than 400 chars."""
    long_tmp = isolated_tmp / ("a" * 200) / ("b" * 200)
    long_tmp.mkdir(parents=True)
    r = peek("run", "--", *lines_cmd(60), tmpdir=long_tmp)
    c = parse_capped(r)
    full = r.lines[c.full_index]
    assert len(full) > 400 and "[cut:" not in full
    assert Path(c.spill).is_file()
    assert len(r.last) > 400 and "[cut:" not in r.last
    assert c.spill in r.last
    assert "[cut:" not in r.first


def test_cut_suffix_and_newlines_do_not_count_toward_16000_budget(peek: Peek, mk):
    """R1: 40 cut lines of 401 chars cost 16000, though shown text with suffixes is longer."""
    f = mk("f.txt", text_from_lengths([401] * 100))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 40 of 100"
    shown = "".join(r.lines[1:41])
    assert len(shown) > 16000


def test_worst_case_file_window_stays_under_200_lines_and_20000_chars(peek: Peek, mk):
    """R1: worst case file windows stay within 200 lines and 20000 chars."""
    for lengths in ([10000] * 200, [160] * 300):
        f = mk("w.txt", text_from_lengths(lengths))
        r = peek("file", str(f))
        assert len(r.lines) <= 200
        assert len(r.text) <= 20000


def test_worst_case_capped_run_stays_under_200_lines_and_20000_chars(peek: Peek):
    """R1: worst case capped runs stay within 200 lines and 20000 chars."""
    for n, w in ((1000, 450), (1000, 5000), (300, 0)):
        r = peek("run", "--", *lines_cmd(n, w))
        assert len(r.lines) <= 200
        assert len(r.text) <= 20000


def test_single_line_file_of_one_million_chars_prints_one_cut_line(peek: Peek, mk):
    """R1: a one line file of one million chars prints one cut line."""
    f = mk("big.txt", "x" * 1_000_000)
    r = peek("file", str(f))
    assert r.lines == [
        "lines 1 to 1 of 1",
        "x" * 400 + " [cut: 1000000 chars]",
        "end: lines 1 to 1 of 1",
    ]
    assert numbered_text(0) == ""
