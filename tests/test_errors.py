"""R6: failures, exit codes, causes and precedence."""

from __future__ import annotations

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest
from conftest import SEVEN_CAUSES, Peek, lines_cmd, numbered_text, parse_capped, peek_dirs, snapshot

needs_user = pytest.mark.skipif(os.geteuid() == 0, reason="permission tests need a non root user")


def three(cause: str, code: int = 2) -> list[str]:
    return [f"exit {code}, 0 lines, 0 bytes", f"error: {cause}", "done"]


@contextmanager
def mode(path: Path, m: int) -> Iterator[None]:
    old = stat.S_IMODE(path.stat().st_mode)
    path.chmod(m)
    try:
        yield
    finally:
        path.chmod(old)


def test_file_no_such_file_exit_2_exactly_three_lines(peek: Peek, data: Path):
    """R6: a missing file is exit 2 with exactly three lines."""
    r = peek("file", str(data / "missing.txt"))
    assert r.code == 2
    assert r.lines == three("no such file")


def test_file_directory_is_not_a_regular_file(peek: Peek, data: Path):
    """R6: a directory is `not a regular file`."""
    r = peek("file", str(data))
    assert r.code == 2
    assert r.lines == three("not a regular file")


def test_file_fifo_is_not_a_regular_file(peek: Peek, data: Path):
    """R6: a FIFO is `not a regular file` and peek does not hang."""
    fifo = data / "fifo"
    os.mkfifo(fifo)
    r = peek("file", str(fifo), timeout=20)
    assert r.code == 2
    assert r.lines == three("not a regular file")


@needs_user
def test_file_chmod_000_is_permission_denied_exit_2(peek: Peek, mk):
    """R6: an unreadable file is `permission denied`, exit 2."""
    f = mk("secret.txt", "x\n")
    with mode(f, 0o000):
        r = peek("file", str(f))
    assert r.code == 2
    assert r.lines == three("permission denied")


@needs_user
def test_file_in_directory_without_search_permission_is_permission_denied(peek: Peek, mk, data):
    """R6: a file under a directory without search permission is `permission denied`."""
    f = mk("locked/inner.txt", "x\n")
    with mode(f.parent, 0o600):
        r = peek("file", str(f))
    assert r.code == 2
    assert r.lines == three("permission denied")


def test_file_broken_symlink_is_no_such_file(peek: Peek, data: Path):
    """R6: a broken symlink is `no such file`."""
    link = data / "link"
    link.symlink_to(data / "nowhere")
    r = peek("file", str(link))
    assert r.code == 2
    assert r.lines == three("no such file")


def test_file_path_through_a_regular_file_component_is_no_such_file(peek: Peek, mk):
    """R6: PATH below a regular file (ENOTDIR) is `no such file`."""
    f = mk("plain.txt", "x\n")
    r = peek("file", str(f / "child"))
    assert r.code == 2
    assert r.lines == three("no such file")


def test_file_empty_path_string_is_no_such_file(peek: Peek):
    """R6: an empty PATH is `no such file`."""
    r = peek("file", "")
    assert r.code == 2
    assert r.lines == three("no such file")


def test_every_file_error_first_line_is_exit_2_0_lines_0_bytes_and_last_line_is_done(
    peek: Peek, mk, data: Path
):
    """R6: every peek file error starts `exit 2, 0 lines, 0 bytes` and ends `done`."""
    f = mk("f.txt", numbered_text(5))
    cases = [
        ["file", str(data / "missing")],
        ["file", str(data)],
        ["file", str(f), "--lines", "0:1"],
        ["file", str(f), "--lines", "9:9"],
        ["file", str(f), "--bogus"],
        ["file"],
    ]
    for args in cases:
        r = peek(*args)
        assert r.code == 2, args
        assert r.first == "exit 2, 0 lines, 0 bytes", args
        assert r.last == "done", args
        assert len(r.lines) == 3, args


def test_error_cause_is_one_of_the_seven_allowed_causes(peek: Peek, mk, data: Path):
    """R6: every failing invocation carries an error line from the closed list of seven."""
    f = mk("f.txt", numbered_text(5))
    cases = [
        ["file", str(data / "missing")],
        ["file", str(data)],
        ["file", str(f), "--lines", "0:1"],
        ["file", str(f), "--lines", "9:9"],
        ["file"],
        ["run", "--", "peek-no-such-command-9f3a1c"],
        ["run", "--", str(f)],
    ]
    for args in cases:
        r = peek(*args)
        assert r.code != 0, args
        errs = [x for x in r.lines if x.startswith("error: ")]
        assert len(errs) == 1 and SEVEN_CAUSES.match(errs[0]), (args, errs)


def test_run_command_not_found_is_exactly_three_lines_exit_127(peek: Peek):
    """R6: a command that cannot be found prints exactly three lines and exits 127."""
    r = peek("run", "--", "peek-no-such-command-9f3a1c")
    assert r.code == 127
    assert r.lines == three("command not found", 127)


def test_run_command_not_found_for_relative_path_and_for_empty_command_string(peek: Peek):
    """R6: a relative path that does not exist and an empty command are exit 127."""
    for cmd in ("./no/such/cmd", ""):
        r = peek("run", "--", cmd)
        assert r.code == 127, cmd
        assert r.lines == three("command not found", 127), cmd


def test_run_command_under_a_regular_file_component_is_exit_127(peek: Peek, mk):
    """R6: a command path below a regular file (ENOTDIR) is exit 127."""
    f = mk("plain.txt", "x\n")
    r = peek("run", "--", str(f / "cmd"))
    assert r.code == 127
    assert r.lines == three("command not found", 127)


def test_run_command_not_found_creates_no_spill(peek: Peek, isolated_tmp: Path, cwd: Path):
    """R6: command not found creates nothing."""
    peek("run", "--", "peek-no-such-command-9f3a1c")
    assert peek_dirs(isolated_tmp) == []
    assert snapshot(isolated_tmp) == [] and snapshot(cwd) == []


@needs_user
def test_run_non_executable_file_is_exit_126_error_permission_denied(peek: Peek, mk):
    """R6: a file without execute permission is exit 126 `permission denied`."""
    f = mk("noexec.sh", "#!/bin/sh\necho hi\n")
    f.chmod(0o644)
    r = peek("run", "--", str(f))
    assert r.code == 126
    assert r.lines == three("permission denied", 126)


@needs_user
def test_run_directory_as_command_is_exit_126(peek: Peek, data: Path):
    """R6: a directory as the command is exit 126."""
    r = peek("run", "--", str(data))
    assert r.code == 126
    assert r.lines == three("permission denied", 126)


def test_run_exec_format_error_is_exit_126(peek: Peek, mk):
    """R6: an executable file the kernel cannot run (ENOEXEC) is exit 126."""
    f = mk("junk.bin", b"\x00\x01\x02\x03 not a program\n")
    f.chmod(0o755)
    r = peek("run", "--", str(f))
    assert r.code == 126
    assert r.lines == three("permission denied", 126)


@pytest.mark.parametrize("c", [1, 2, 42, 255])
def test_run_nonzero_wrapped_code_is_the_first_line_code(peek: Peek, c):
    """R6: a non zero wrapped code is the code in line 1 and the exit code."""
    r = peek("run", "--", "sh", "-c", f"echo hi; exit {c}")
    assert r.code == c
    assert r.lines == [f"exit {c}, 1 lines, 3 bytes", "hi", "done"]


def test_run_wrapped_exit_127_with_output_has_no_error_line(peek: Peek):
    """R6: a wrapped 127 with output is a normal run without an error line."""
    r = peek("run", "--", "sh", "-c", "echo hi; exit 127")
    assert r.code == 127
    assert r.lines == ["exit 127, 1 lines, 3 bytes", "hi", "done"]
    assert not any(x.startswith("error:") for x in r.lines)


@pytest.mark.parametrize("n", [1, 2, 9, 11, 15])
def test_run_signal_death_exit_is_128_plus_n(peek: Peek, n):
    """R6: death by signal n exits 128+n."""
    r = peek("run", "--", "sh", "-c", f"kill -{n} $$")
    assert r.code == 128 + n
    assert r.first == f"exit {128 + n}, 0 lines, 0 bytes"


def test_run_signal_death_with_long_output_follows_cap_and_spill_rules(peek: Peek):
    """R6: a signalled run with long output is capped and spilled."""
    script = "i=1; while [ $i -le 100 ]; do echo L$i; i=$((i+1)); done; kill -TERM $$"
    r = peek("run", "--", "sh", "-c", script)
    assert r.code == 143
    c = parse_capped(r)
    assert c.header.startswith("exit 143, 100 lines, ")
    assert Path(c.spill).is_file()
    assert c.after[0].startswith("next: ")


def test_capped_failed_run_exit_3_follows_cap_spill_and_next(peek: Peek):
    """R6: a capped run that exits 3 still has omitted, full output and next."""
    r = peek("run", "--", *lines_cmd(100, tail="3"))
    assert r.code == 3
    c = parse_capped(r)
    assert c.header.startswith("exit 3, 100 lines, ")
    assert (c.m, c.total) == (50, 100)
    assert Path(c.spill).is_file()
    assert c.after[0].startswith("next: ")


def test_stderr_of_failing_command_is_shown_merged_with_stdout(peek: Peek):
    """R6: stderr of a failing command is shown in the output."""
    r = peek("run", "--", "sh", "-c", "echo oops >&2; exit 4")
    assert r.code == 4
    assert r.lines == ["exit 4, 1 lines, 5 bytes", "oops", "done"]
    assert r.err == b""


def test_precedence_usage_beats_no_such_file(peek: Peek, data: Path):
    """R6: usage beats no such file."""
    r = peek("file", str(data / "missing"), "--bogus")
    assert r.code == 2
    assert r.lines == three("usage")


def test_precedence_repeated_lines_usage_beats_no_such_file(peek: Peek, data: Path):
    """R6: a repeated --lines is usage even for a missing file."""
    r = peek("file", str(data / "missing"), "--lines", "1:2", "--lines", "1:2")
    assert r.lines == three("usage")


def test_precedence_no_such_file_beats_bad_range(peek: Peek, data: Path):
    """R6: no such file beats bad range."""
    r = peek("file", str(data / "missing"), "--lines", "0:0")
    assert r.lines == three("no such file")


def test_precedence_not_a_regular_file_beats_bad_range(peek: Peek, data: Path):
    """R6: not a regular file beats bad range."""
    r = peek("file", str(data), "--lines", "0:0")
    assert r.lines == three("not a regular file")


@needs_user
def test_precedence_permission_denied_beats_bad_range(peek: Peek, mk):
    """R6: permission denied beats bad range."""
    f = mk("secret.txt", "x\n")
    with mode(f, 0o000):
        r = peek("file", str(f), "--lines", "0:0")
    assert r.lines == three("permission denied")


def test_precedence_bad_range_beats_range_past_end(peek: Peek, mk):
    """R6: bad range beats range past end."""
    f = mk("f.txt", numbered_text(10))
    assert peek("file", str(f), "--lines", "20:5").lines == three("bad range")
    assert peek("file", str(f), "--lines", "0:20").lines == three("bad range")
