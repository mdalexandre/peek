"""R7: the capped run shape: head, omitted, tail, full output, terminal line."""

from __future__ import annotations

from pathlib import Path

import pytest
from conftest import (
    BODY,
    Peek,
    costs,
    expect_head_tail,
    lines_cmd,
    parse_capped,
    peek_dirs,
    raw_cmd,
)


def run(peek: Peek, n: int, w: int = 0):
    return peek("run", "--", *lines_cmd(n, w))


def L(a: int, b: int) -> list[str]:
    return [f"L{i}" for i in range(a, b + 1)]


def test_run_of_exactly_50_lines_is_uncapped_and_shows_all_lines(peek: Peek):
    """R7: exactly 50 lines is uncapped and shows every line."""
    r = run(peek, 50)
    assert r.first.startswith("exit 0, 50 lines, ")
    assert r.lines[1:-1] == L(1, 50)
    assert r.last == "done"
    assert not any(x.startswith(("omitted", "full output")) for x in r.lines)


def test_run_of_51_lines_is_capped_with_h_30_t_20_omitted_1(peek: Peek):
    """R7: 51 lines is capped with H 30, T 20 and `omitted 1 lines of 51`."""
    c = parse_capped(run(peek, 51))
    assert c.head == L(1, 30)
    assert c.tail == L(32, 51)
    assert (c.m, c.total) == (1, 51)


def test_run_of_100_lines_is_capped_with_omitted_50_of_100(peek: Peek):
    """R7: 100 lines is capped with `omitted 50 lines of 100`."""
    r = run(peek, 100)
    c = parse_capped(r)
    assert (c.m, c.total) == (50, 100)
    assert r.lines[c.omitted_index] == "omitted 50 lines of 100"


def test_capped_run_order_is_header_head_omitted_tail_full_output_terminal(peek: Peek):
    """R7: the order is header, head, omitted, tail, full output, terminal."""
    r = run(peek, 100)
    c = parse_capped(r)
    assert r.first.startswith("exit 0, 100 lines, ")
    assert c.omitted_index == 1 + len(c.head)
    assert c.full_index == c.omitted_index + 1 + len(c.tail)
    assert c.full_index == len(r.lines) - 2
    assert len(c.after) == 1 and c.after[0].startswith("next: ")


def test_run_of_exactly_16000_chars_including_newlines_is_uncapped(peek: Peek):
    """R7: 40 lines of 399 chars plus newline is exactly 16000 chars and uncapped."""
    r = run(peek, 40, 399)
    assert r.first == "exit 0, 40 lines, 16000 bytes"
    assert not any(x.startswith("omitted") for x in r.lines)
    assert len(r.lines) == 42


def test_run_of_16001_chars_is_capped(peek: Peek):
    """R7: one more char makes the run capped."""
    code = "for i in range(1,40): print(('L%d' % i).ljust(399,'x'))\nprint('L40'.ljust(400,'x'))"
    r = peek("run", "--", "python3", "-c", code)
    assert r.first == "exit 0, 40 lines, 16001 bytes"
    c = parse_capped(r)
    assert c.total == 40


def test_cap_decision_uses_raw_length_not_cut_length(peek: Peek):
    """R7: 10 lines of 1700 chars are capped on raw length though cut text is short."""
    r = run(peek, 10, 1700)
    c = parse_capped(r)
    assert c.total == 10
    assert c.after == ["done"]


def test_cap_decision_counts_code_points_not_bytes(peek: Peek):
    """R7: 40 lines of 399 two byte chars are 16000 code points, so uncapped."""
    code = "import sys\nfor i in range(40): sys.stdout.buffer.write(('\\u00e9'*399+'\\n').encode())"
    r = peek("run", "--", "python3", "-c", code)
    assert r.first == "exit 0, 40 lines, 31960 bytes"
    assert not any(x.startswith("omitted") for x in r.lines)
    assert r.last == "done"


def test_one_very_long_line_run_is_capped_h_1_t_0_omitted_0_and_ends_done(peek: Peek):
    """R7: one 100000 char line is capped with H 1, T 0, omitted 0 and ends with done."""
    r = peek("run", "--", "python3", "-c", "print('x'*100000)")
    c = parse_capped(r)
    assert c.head == ["x" * 400 + " [cut: 100000 chars]"]
    assert c.tail == []
    assert (c.m, c.total) == (0, 1)
    assert r.last == "done"
    assert len(r.lines) == 5


def test_capped_with_h_plus_t_equals_l_ends_with_done_not_next(peek: Peek):
    """R7: 40 lines of 450 chars give H 20, T 20: the terminal line is done."""
    r = run(peek, 40, 450)
    c = parse_capped(r)
    assert len(c.head) + len(c.tail) == c.total == 40
    assert c.after == ["done"]
    assert not any(x.startswith("next:") for x in r.lines)


def test_capped_with_h_plus_t_equals_l_still_prints_omitted_0_and_full_output_line(peek: Peek):
    """R7: H+T = L still prints `omitted 0 lines of L` and the full output line."""
    r = run(peek, 40, 450)
    c = parse_capped(r)
    assert r.lines[c.omitted_index] == "omitted 0 lines of 40"
    assert Path(c.spill).is_file()


def test_capped_with_h_plus_t_equals_l_spill_holds_the_uncut_text(peek: Peek):
    """R7: the spill of an H+T = L run holds the uncut lines."""
    r = run(peek, 40, 450)
    c = parse_capped(r)
    expected = "".join(f"L{i}".ljust(450, "x") + "\n" for i in range(1, 41)).encode()
    assert Path(c.spill).read_bytes() == expected


def test_head_stops_at_30_lines(peek: Peek):
    """R7: with short lines the head stops at 30 lines."""
    c = parse_capped(run(peek, 100))
    assert len(c.head) == 30 and c.head[-1] == "L30"


def test_head_stops_before_the_line_that_would_pass_8000_chars(peek: Peek):
    """R7: lines of 350 chars give H 22 (7700), the 23rd would pass 8000."""
    c = parse_capped(run(peek, 60, 350))
    assert len(c.head) == 22


def test_head_budget_8000_is_inclusive_20_lines_of_400(peek: Peek):
    """R7: 20 lines of 400 shown chars is exactly 8000 and is kept."""
    c = parse_capped(run(peek, 60, 400))
    assert len(c.head) == 20


def test_head_is_maximal_26_lines_of_300_chars_not_fewer(peek: Peek):
    """R7: 26 lines of 300 chars is 7800, the longest head within 8000."""
    c = parse_capped(run(peek, 60, 300))
    assert len(c.head) == 26


def test_head_budget_counts_cut_chars_not_raw_chars(peek: Peek):
    """R7: lines of 1000 raw chars cost 400 shown chars, so H is 20 not 8."""
    c = parse_capped(run(peek, 60, 1000))
    assert len(c.head) == 20


def test_tail_never_includes_head_lines_when_few_lines_follow_the_head(peek: Peek):
    """R7: 36 lines of 450: H 20, only 16 lines follow, so T is 16 and nothing repeats."""
    r = run(peek, 36, 450)
    c = parse_capped(r)
    assert (len(c.head), len(c.tail)) == (20, 16)
    assert [x.split("x")[0] for x in c.head + c.tail] == L(1, 36)
    assert r.lines[c.omitted_index] == "omitted 0 lines of 36"
    assert c.after == ["done"]


def test_tail_stops_at_20_lines(peek: Peek):
    """R7: the tail is the last 20 lines."""
    c = parse_capped(run(peek, 100))
    assert c.tail == L(81, 100)


def test_tail_budget_8000_never_binds_because_20_cut_lines_fit_exactly(peek: Peek):
    """R7: 20 cut lines cost exactly 8000, so the tail still has 20 lines."""
    c = parse_capped(run(peek, 100, 1000))
    assert len(c.tail) == 20
    assert all(x.endswith("[cut: 1000 chars]") for x in c.tail)


@pytest.mark.parametrize(
    ("n", "w"),
    [(51, 0), (100, 0), (45, 400), (33, 500)],
    ids=["51_lines", "100_lines", "45_lines_of_400", "33_lines_of_500"],
)
def test_omitted_m_equals_l_minus_h_minus_t(peek: Peek, n, w):
    """R7: M equals L minus H minus T and matches the maximal head and tail."""
    c = parse_capped(run(peek, n, w))
    h, t = expect_head_tail(costs(n, w))
    assert (len(c.head), len(c.tail)) == (h, t)
    assert c.total == n
    assert c.m == n - h - t


def test_displayed_head_and_tail_equal_spill_slices_and_omitted_are_the_middle(peek: Peek):
    """R7: head and tail are the spill's first and last lines; the middle is omitted."""
    r = run(peek, 100)
    c = parse_capped(r)
    spill = Path(c.spill).read_text().split("\n")[:-1]
    assert c.head == spill[: len(c.head)]
    assert c.tail == spill[len(spill) - len(c.tail) :]
    middle = spill[len(c.head) : len(spill) - len(c.tail)]
    assert len(middle) == c.m
    assert not set(middle) & set(r.lines)


def test_uncapped_run_omits_no_line(peek: Peek):
    """R7: 50 lines of 300 chars (15050 chars) is uncapped and every line is shown."""
    r = run(peek, 50, 300)
    assert len(r.lines[1:-1]) == 50
    assert all(BODY.match(x) for x in r.lines[1:-1])
    assert not any(x.startswith("omitted") for x in r.lines)


def test_empty_lines_count_as_lines_50_uncapped_51_capped(peek: Peek):
    """R7: 50 empty lines are uncapped, 51 are capped."""
    r50 = peek("run", "--", "python3", "-c", "import sys; sys.stdout.write('\\n'*50)")
    assert r50.first == "exit 0, 50 lines, 50 bytes"
    assert not any(x.startswith("omitted") for x in r50.lines)
    r51 = peek("run", "--", "python3", "-c", "import sys; sys.stdout.write('\\n'*51)")
    assert parse_capped(r51).total == 51


def test_final_line_without_newline_counts_toward_the_cap(peek: Peek):
    """R7: an unterminated last line is a line: 51 capped, 50 not."""
    code = "import sys; sys.stdout.write('\\n'.join('L%d' % i for i in range(1,{n}+1)))"
    r51 = peek("run", "--", "python3", "-c", code.format(n=51))
    assert r51.first.startswith("exit 0, 51 lines, ")
    assert parse_capped(r51).total == 51
    r50 = peek("run", "--", "python3", "-c", code.format(n=50))
    assert r50.first.startswith("exit 0, 50 lines, ")
    assert not any(x.startswith("omitted") for x in r50.lines)


def test_stdout_and_stderr_are_merged_in_arrival_order(peek: Peek):
    """R7: stdout and stderr arrive in one stream in order."""
    r = peek("run", "--", "sh", "-c", "echo out1; echo err1 >&2; echo out2; echo err2 >&2")
    assert r.lines[1:-1] == ["out1", "err1", "out2", "err2"]


def test_stderr_only_output_is_shown(peek: Peek):
    """R7: output that is only stderr is shown."""
    r = peek("run", "--", "sh", "-c", "echo onlyerr >&2")
    assert r.lines == ["exit 0, 1 lines, 8 bytes", "onlyerr", "done"]


def test_invalid_utf8_output_is_replaced_in_display_and_raw_in_spill(peek: Peek):
    """R7: display shows U+FFFD, the spill keeps the raw bytes."""
    argv, expected = raw_cmd()
    r = peek("run", "--", *argv)
    c = parse_capped(r)
    assert "�" in c.head[0]
    assert Path(c.spill).read_bytes() == expected


def test_one_megabyte_of_output_does_not_deadlock_on_pipe_buffer(peek: Peek):
    """R7: a megabyte of output is read to the end and spilled whole."""
    code = "import sys; sys.stdout.write(('x'*99+'\\n')*10000)"
    r = peek("run", "--", "python3", "-c", code, timeout=60)
    assert r.code == 0
    assert r.first == "exit 0, 10000 lines, 1000000 bytes"
    c = parse_capped(r)
    assert Path(c.spill).stat().st_size == 1_000_000 == c.size


def test_capped_run_creates_one_spill_directory(peek: Peek, isolated_tmp: Path):
    """R7: a capped run leaves exactly one peek directory."""
    run(peek, 60)
    assert len(peek_dirs(isolated_tmp)) == 1
