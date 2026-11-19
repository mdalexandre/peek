"""R3: the next line is the terminal line and runs as printed."""

from __future__ import annotations

import os
import shlex
import subprocess
from pathlib import Path

from conftest import LAUNCHER, Peek, lines_cmd, numbered_text, parse_capped, text_from_lengths

PROG = str(LAUNCHER.resolve())


def printed(res, cwd: Path, tmp: Path) -> subprocess.CompletedProcess[bytes]:
    assert res.last.startswith("next: ")
    cmd = res.last[len("next: ") :]
    env = {**os.environ, "PEEK_PROG": PROG, "TMPDIR": str(tmp), "PYTHONDONTWRITEBYTECODE": "1"}
    return subprocess.run(
        ["sh", "-c", cmd],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        timeout=60,
    )


def nxt(path, a: int, b: int, prog: str = PROG) -> str:
    return f"next: {shlex.quote(prog)} file {shlex.quote(str(path))} --lines {a}:{b}"


def test_file_window_next_line_is_peek_file_path_lines_b_plus_1_to_b_plus_100(peek: Peek, mk):
    """R3: a window ending at B prints next with --lines B+1:B+100."""
    f = mk("f.txt", numbered_text(250))
    assert peek("file", str(f)).last == nxt(f, 101, 200)
    assert peek("file", str(f), "--lines", "20:60").last == nxt(f, 61, 160)


def test_next_after_char_budget_early_end_uses_actual_b_41_to_140(peek: Peek, mk):
    """R3: a window cut short at line 40 continues at 41:140."""
    f = mk("f.txt", text_from_lengths([500] * 100))
    r = peek("file", str(f))
    assert r.first == "lines 1 to 40 of 100"
    assert r.last == nxt(f, 41, 140)


def test_next_after_clipped_window_continues_from_actual_b_not_requested_b(peek: Peek, mk):
    """R3: a clipped window 10:500 shows 10 to 109 and continues at 110:209."""
    f = mk("f.txt", numbered_text(250))
    r = peek("file", str(f), "--lines", "10:500")
    assert r.last == nxt(f, 110, 209)


def test_capped_run_next_is_peek_file_spill_lines_31_to_130_after_30_line_head(peek: Peek):
    """R3: a capped run with a 30 line head continues at the spill lines 31:130."""
    r = peek("run", "--", *lines_cmd(100))
    c = parse_capped(r)
    assert len(c.head) == 30
    assert r.last == nxt(c.spill, 31, 130)


def test_capped_run_next_uses_h_plus_1_when_head_is_shortened_by_char_budget(peek: Peek):
    """R3: a 20 line head continues at 21:120."""
    r = peek("run", "--", *lines_cmd(100, 450))
    c = parse_capped(r)
    assert len(c.head) == 20
    assert r.last == nxt(c.spill, 21, 120)


def test_next_line_is_the_terminal_line_and_full_output_line_comes_before_it(peek: Peek):
    """R3: next is last; status lines (full output) come before it."""
    r = peek("run", "--", *lines_cmd(100))
    assert r.last.startswith("next: ")
    assert r.lines[-2].startswith("full output: ")
    assert sum(x.startswith("next: ") for x in r.lines) == 1


def test_next_line_is_one_invocation_without_pipe_semicolon_or_and(peek: Peek, mk):
    """R3: the printed command is one peek call of exactly five words."""
    f = mk("f.txt", numbered_text(250))
    for r in (peek("file", str(f)), peek("run", "--", *lines_cmd(100))):
        cmd = r.last[len("next: ") :]
        words = shlex.split(cmd)
        assert len(words) == 5
        assert words[1] == "file" and words[3] == "--lines"
        assert not any(w in {"|", ";", "&&", "&", "||"} for w in words)
        assert not any(ch in cmd for ch in "|;&\n")


def test_printed_next_line_of_file_window_runs_through_the_shell_with_peek_prog_set_and_exits_0(
    peek: Peek, mk, cwd: Path, isolated_tmp: Path
):
    """R3: the printed next of a file window runs under sh and exits 0."""
    f = mk("f.txt", numbered_text(250))
    p = printed(peek("file", str(f)), cwd, isolated_tmp)
    assert p.returncode == 0
    assert p.stdout.decode().split("\n")[0] == "lines 101 to 200 of 250"


def test_printed_next_line_of_capped_run_runs_through_the_shell_with_peek_prog_set_and_exits_0(
    peek: Peek, cwd: Path, isolated_tmp: Path
):
    """R3: the printed next of a capped run reads the spill and exits 0."""
    p = printed(peek("run", "--", *lines_cmd(100)), cwd, isolated_tmp)
    assert p.returncode == 0
    assert p.stdout.decode().split("\n")[0] == "lines 31 to 100 of 100"


def test_printed_program_equals_peek_prog_when_set(peek_direct: Peek, mk):
    """R3: with PEEK_PROG set the program word is PEEK_PROG."""
    f = mk("f.txt", numbered_text(250))
    r = peek_direct("file", str(f), env={"PEEK_PROG": "/opt/mypeek/peek"})
    assert r.last == nxt(f, 101, 200, "/opt/mypeek/peek")
    assert r.last.startswith("next: /opt/mypeek/peek file ")


def test_printed_program_is_shlex_quoted_when_peek_prog_contains_a_space(peek_direct: Peek, mk):
    """R3: a PEEK_PROG with a space is printed shlex quoted."""
    f = mk("f.txt", numbered_text(250))
    r = peek_direct("file", str(f), env={"PEEK_PROG": "/opt/my peek/peek"})
    assert r.last.startswith("next: '/opt/my peek/peek' file ")
    assert shlex.split(r.last[len("next: ") :])[0] == "/opt/my peek/peek"


def test_printed_program_is_bare_peek_when_peek_prog_is_unset(peek_direct: Peek, mk):
    """R3: without PEEK_PROG the program word is bare peek."""
    f = mk("f.txt", numbered_text(250))
    r = peek_direct("file", str(f), unset=("PEEK_PROG",))
    assert r.last == nxt(f, 101, 200, "peek")
    r2 = peek_direct("file", str(f), env={"PEEK_PROG": ""})
    assert r2.last == nxt(f, 101, 200, "peek")


def test_next_path_is_shlex_quoted_for_a_path_with_space_and_quote_and_runs(
    peek: Peek, mk, cwd: Path, isolated_tmp: Path
):
    """R3: a path with a space and a quote is quoted and the printed line runs."""
    f = mk("a b'c.txt", numbered_text(250))
    r = peek("file", str(f))
    assert shlex.quote(str(f)) in r.last
    assert r.last == nxt(f, 101, 200)
    p = printed(r, cwd, isolated_tmp)
    assert p.returncode == 0
    assert p.stdout.decode().split("\n")[0] == "lines 101 to 200 of 250"


def test_following_next_lines_walks_a_300_line_file_to_the_end_line(
    peek: Peek, mk, cwd: Path, isolated_tmp: Path
):
    """R3: following each printed next reaches the end line and shows every line once."""
    f = mk("f.txt", numbered_text(300))
    r = peek("file", str(f))
    seen = r.lines[1:-1]
    for _ in range(10):
        if not r.last.startswith("next: "):
            break
        p = printed(r, cwd, isolated_tmp)
        assert p.returncode == 0
        out = p.stdout.decode().split("\n")[:-1]
        seen += out[1:-1]
        r = type(r)(p.returncode, p.stdout, p.stderr)
    assert r.last == "end: lines 201 to 300 of 300"
    assert seen == [f"L{i}" for i in range(1, 301)]


def test_no_next_line_when_window_reaches_end_of_file(peek: Peek, mk):
    """R3: a window reaching the end prints end and no next."""
    f = mk("f.txt", numbered_text(100))
    r = peek("file", str(f))
    assert r.last == "end: lines 1 to 100 of 100"
    assert not any(x.startswith("next:") for x in r.lines)
