"""Shared fixtures and helpers for the peek tests.

Every test drives the launcher bin/peek as a subprocess (stdin /dev/null, TMPDIR set to a per
test directory under the pytest basetemp), except the few unit tests that import a module.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path

import pytest

sys.dont_write_bytecode = True

TOOL = Path(__file__).resolve().parents[1]
SRC = TOOL / "src"
BIN = TOOL / "bin"
LAUNCHER = BIN / "peek"
PUBLIC_LAUNCHER = Path(
    os.environ.get("PEEK_PUBLIC_LAUNCHER", str(Path.home() / ".local" / "bin" / "peek"))
)
SCRIPTS = TOOL / "scripts"

SEVEN_CAUSES = re.compile(
    r"^error: (no such file|not a regular file|permission denied|bad range"
    r"|range past end of file \(\d+ lines\)|usage|command not found)$"
)
FIRST_LINE = re.compile(r"^(lines \d+ to \d+ of \d+|exit \d+, \d+ lines, \d+ bytes)$")
BODY = re.compile(r"^L\d+")


@dataclass
class Res:
    """Result of one peek invocation."""

    code: int
    raw: bytes
    err: bytes

    @property
    def text(self) -> str:
        return self.raw.decode("utf-8")

    @property
    def lines(self) -> list[str]:
        t = self.text
        parts = t.split("\n")
        if t.endswith("\n"):
            parts.pop()
        return parts

    @property
    def first(self) -> str:
        return self.lines[0] if self.lines else ""

    @property
    def last(self) -> str:
        return self.lines[-1] if self.lines else ""


def _env(tmpdir: Path, env: dict[str, str] | None, unset: tuple[str, ...]) -> dict[str, str]:
    e = {**os.environ, "TMPDIR": str(tmpdir), "PYTHONDONTWRITEBYTECODE": "1"}
    e.pop("PEEK_PROG", None)
    for k in unset:
        e.pop(k, None)
    e.update(env or {})
    return e


@pytest.fixture(autouse=True)
def isolated_tmp(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    d = tmp_path / "tmp"
    d.mkdir()
    monkeypatch.setenv("TMPDIR", str(d))
    monkeypatch.setattr(tempfile, "tempdir", None)
    yield d


@pytest.fixture
def cwd(tmp_path: Path) -> Path:
    d = tmp_path / "cwd"
    d.mkdir()
    return d


@pytest.fixture
def data(tmp_path: Path) -> Path:
    d = tmp_path / "data"
    d.mkdir()
    return d


Peek = Callable[..., Res]


@pytest.fixture
def peek(cwd: Path, isolated_tmp: Path) -> Peek:
    def run(
        *args: str,
        env: dict[str, str] | None = None,
        unset: tuple[str, ...] = (),
        tmpdir: Path | None = None,
        workdir: Path | None = None,
        timeout: float = 60,
    ) -> Res:
        p = subprocess.run(
            [str(LAUNCHER), *args],
            cwd=workdir or cwd,
            env=_env(tmpdir or isolated_tmp, env, unset),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
        )
        return Res(p.returncode, p.stdout, p.stderr)

    return run


@pytest.fixture
def peek_direct(cwd: Path, isolated_tmp: Path) -> Peek:
    """Runs `python3 -m peek` directly, so PEEK_PROG is whatever the test sets."""

    def run(
        *args: str,
        env: dict[str, str] | None = None,
        unset: tuple[str, ...] = (),
        timeout: float = 60,
    ) -> Res:
        if not (SRC / "peek").is_dir():
            raise FileNotFoundError(f"missing package {SRC / 'peek'}")
        e = _env(isolated_tmp, env, unset)
        e["PYTHONPATH"] = str(SRC)
        p = subprocess.run(
            ["python3", "-X", "utf8", "-P", "-m", "peek", *args],
            cwd=cwd,
            env=e,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=timeout,
        )
        return Res(p.returncode, p.stdout, p.stderr)

    return run


@pytest.fixture
def mk(data: Path) -> Callable[..., Path]:
    def make(name: str, content: str | bytes) -> Path:
        p = data / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return p

    return make


def numbered_text(n: int, width: int = 0, trailing_nl: bool = True) -> str:
    body = "\n".join(f"L{i}".ljust(width, "x") for i in range(1, n + 1))
    return body + ("\n" if trailing_nl and n else "")


def text_from_lengths(lengths: list[int]) -> str:
    return "".join(f"L{i}".ljust(w, "x") + "\n" for i, w in enumerate(lengths, 1))


def lines_cmd(n: int, width: int = 0, tail: str = "") -> list[str]:
    """A command printing L1..Ln, each padded with x to `width` characters."""
    code = f"for i in range(1,{n}+1): print(('L%d' % i).ljust({width},'x'))"
    if tail:
        code = f"{code}\nimport sys; sys.exit({tail})"
    return ["python3", "-c", code]


def costs(n: int, width: int = 0) -> list[int]:
    return [min(max(width, len(f"L{i}")), 400) for i in range(1, n + 1)]


def expect_head_tail(cost: list[int]) -> tuple[int, int]:
    total = len(cost)
    h = 0
    run = 0
    while h < total and h < 30 and run + cost[h] <= 8000:
        run += cost[h]
        h += 1
    t = 0
    run = 0
    while t < 20 and total - 1 - t >= h and run + cost[total - 1 - t] <= 8000:
        run += cost[total - 1 - t]
        t += 1
    return h, t


RAW_EXPR = 'b"".join(b"\\xff\\xfeL%d " % i + b"x"*500 + b"\\n" for i in range(1,61))'


def raw_cmd() -> tuple[list[str], bytes]:
    """A command writing 60 lines of invalid UTF-8 then 500 x; and its exact bytes."""
    argv = ["python3", "-c", f"import sys; sys.stdout.buffer.write({RAW_EXPR})"]
    return argv, eval(RAW_EXPR)


@dataclass
class Capped:
    header: str
    head: list[str]
    m: int
    total: int
    tail: list[str]
    spill: str
    size: int
    after: list[str]
    omitted_index: int
    full_index: int


def parse_capped(res: Res) -> Capped:
    ls = res.lines
    io = next(i for i, x in enumerate(ls) if re.match(r"^omitted \d+ lines of \d+$", x))
    m = re.match(r"^omitted (\d+) lines of (\d+)$", ls[io])
    assert m
    jf = max(i for i, x in enumerate(ls) if x.startswith("full output: "))
    f = re.match(r"^full output: (.+) \((\d+) bytes\)$", ls[jf])
    assert f, ls[jf]
    return Capped(
        ls[0],
        ls[1:io],
        int(m.group(1)),
        int(m.group(2)),
        ls[io + 1 : jf],
        f.group(1),
        int(f.group(2)),
        ls[jf + 1 :],
        io,
        jf,
    )


def peek_dirs(tmp: Path) -> list[Path]:
    return sorted(tmp.glob("peek-*"))


def snapshot(d: Path) -> list[str]:
    return sorted(str(p.relative_to(d)) for p in d.rglob("*")) if d.exists() else []


def make_scenarios(d: Path) -> list[tuple[str, list[str], str]]:
    """(id, peek args, expected terminal kind) for a spread of invocations."""
    d.mkdir(parents=True, exist_ok=True)
    ok = d / "ok.txt"
    ok.write_text("a\nb\nc\n")
    long = d / "long.txt"
    long.write_text(numbered_text(250))
    empty = d / "empty.txt"
    empty.write_bytes(b"")
    adir = d / "adir"
    adir.mkdir(exist_ok=True)
    return [
        ("file_short", ["file", str(ok)], "end"),
        ("file_window", ["file", str(long)], "next"),
        ("file_tail", ["file", str(long), "--lines", "201:250"], "end"),
        ("file_empty", ["file", str(empty)], "end"),
        ("file_missing", ["file", str(d / "missing")], "done"),
        ("file_dir", ["file", str(adir)], "done"),
        ("file_bad_range", ["file", str(ok), "--lines", "0:1"], "done"),
        ("file_past_end", ["file", str(ok), "--lines", "9:9"], "done"),
        ("usage", ["bogus"], "done"),
        ("run_ok", ["run", "--", "echo", "hi"], "done"),
        ("run_zero", ["run", "--", "true"], "done"),
        ("run_fail", ["run", "--", "sh", "-c", "echo x; exit 3"], "done"),
        ("run_capped", ["run", "--", *lines_cmd(100)], "next"),
        ("run_capped_done", ["run", "--", *lines_cmd(40, 450)], "done"),
        ("run_not_found", ["run", "--", "peek-no-such-command-9f3a1c"], "done"),
        ("run_signal", ["run", "--", "sh", "-c", "kill -TERM $$"], "done"),
    ]


TERMINAL = {
    "next": re.compile(r"^next: \S"),
    "end": re.compile(r"^end: lines \d+ to \d+ of \d+$"),
    "done": re.compile(r"^done$"),
}
