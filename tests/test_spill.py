"""R2: the spill directory and file of a capped run."""

from __future__ import annotations

import re
import stat
import tempfile
from pathlib import Path

import pytest
from conftest import Peek, lines_cmd, parse_capped, peek_dirs, raw_cmd

FULL = re.compile(r"^full output: (.+) \((\d+) bytes\)$")


def capped(peek: Peek, **kw):
    return peek("run", "--", *lines_cmd(100, 20), **kw)


def test_capped_run_full_output_line_is_within_last_3_lines(peek: Peek):
    """R2: the full output line is among the last 3 lines."""
    r = capped(peek)
    assert any(FULL.match(x) for x in r.lines[-3:])


def test_spill_path_starts_with_gettempdir_slash_peek_dash(peek: Peek, isolated_tmp: Path):
    """R2: SPILL starts with gettempdir() and /peek-."""
    c = parse_capped(capped(peek))
    assert c.spill.startswith(str(isolated_tmp) + "/peek-")
    assert c.spill.endswith("/out.txt")


def test_spill_directory_mode_is_0700(peek: Peek):
    """R2: the spill directory has mode 0700."""
    c = parse_capped(capped(peek))
    assert stat.S_IMODE(Path(c.spill).parent.stat().st_mode) == 0o700


def test_spill_file_is_named_out_txt_with_mode_0600(peek: Peek):
    """R2: the file is out.txt with mode 0600."""
    c = parse_capped(capped(peek))
    p = Path(c.spill)
    assert p.name == "out.txt"
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_spill_content_equals_raw_bytes_including_invalid_utf8_and_uncut_long_lines(peek: Peek):
    """R2: the spill is the raw merged bytes, uncut."""
    argv, expected = raw_cmd()
    c = parse_capped(peek("run", "--", *argv))
    assert Path(c.spill).read_bytes() == expected


def test_spill_size_equals_printed_s(peek: Peek):
    """R2: the file size equals S in the full output line and the header."""
    r = capped(peek)
    c = parse_capped(r)
    assert Path(c.spill).stat().st_size == c.size
    assert r.first == f"exit 0, 100 lines, {c.size} bytes"


def test_write_spill_calls_tempfile_mkdtemp_with_prefix_peek_dash(
    monkeypatch: pytest.MonkeyPatch, isolated_tmp: Path
):
    """R2: write_spill makes its directory with tempfile.mkdtemp(prefix="peek-")."""
    from peek.spill import write_spill

    calls = []
    real = tempfile.mkdtemp

    def spy(*a, **k):
        calls.append((a, k))
        return real(*a, **k)

    monkeypatch.setattr(tempfile, "mkdtemp", spy)
    path = write_spill(b"abc\n")
    assert len(calls) == 1
    a, k = calls[0]
    assert k.get("prefix", a[1] if len(a) > 1 else None) == "peek-"
    p = Path(path)
    assert p.name == "out.txt" and p.read_bytes() == b"abc\n"
    assert p.parent.parent == isolated_tmp
    assert stat.S_IMODE(p.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(p.stat().st_mode) == 0o600


def test_two_capped_runs_make_two_distinct_spill_directories(peek: Peek, isolated_tmp: Path):
    """R2: two capped runs give two directories and two paths."""
    a = parse_capped(capped(peek))
    b = parse_capped(capped(peek))
    assert a.spill != b.spill
    assert len(peek_dirs(isolated_tmp)) == 2


def test_uncapped_run_creates_no_spill_directory(peek: Peek, isolated_tmp: Path):
    """R2: an uncapped run creates no spill."""
    r = peek("run", "--", *lines_cmd(10))
    assert r.code == 0
    assert peek_dirs(isolated_tmp) == []
    assert not any(x.startswith("full output") for x in r.lines)


def test_empty_output_run_creates_no_spill_directory(peek: Peek, isolated_tmp: Path):
    """R2: a silent run creates no spill."""
    peek("run", "--", "true")
    assert peek_dirs(isolated_tmp) == []


def test_capped_failed_run_spills_and_names_the_file(peek: Peek):
    """R2: a failed capped run still spills."""
    script = "i=1; while [ $i -le 100 ]; do echo L$i; i=$((i+1)); done; exit 3"
    r = peek("run", "--", "sh", "-c", script)
    assert r.code == 3
    c = parse_capped(r)
    assert Path(c.spill).is_file()
    assert Path(c.spill).read_text() == "".join(f"L{i}\n" for i in range(1, 101))


def test_full_output_line_prints_spill_path_unquoted_even_when_tmpdir_has_a_space(
    peek: Peek, isolated_tmp: Path
):
    """R2: the full output line prints SPILL unquoted even with a space in TMPDIR."""
    spaced = isolated_tmp / "with space"
    spaced.mkdir()
    r = capped(peek, tmpdir=spaced)
    line = next(x for x in r.lines if x.startswith("full output: "))
    m = FULL.match(line)
    assert m
    assert m.group(1).startswith(f"{spaced}/peek-")
    assert "'" not in line
    assert Path(m.group(1)).is_file()
