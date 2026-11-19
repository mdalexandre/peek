"""The write command: `peek token PATH` and `peek write PATH --lines A:B --token T --from SRC`.

Behaviour follows design.md (sections 2 to 9). Most tests drive the launcher as a subprocess like
the rest of the suite. Tests that force a failure at a given step call `peek.cli.main` in process,
with monkeypatch on os functions, and read stdout through capfd.
"""

from __future__ import annotations

import errno
import hashlib
import os
import re
import shlex
import stat
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from conftest import (
    BIN,
    LAUNCHER,
    SRC,
    Peek,
    Res,
    lines_cmd,
    make_scenarios,
    numbered_text,
    snapshot,
)

HEX64 = re.compile(r"^[0-9a-f]{64}$")
TMP_PREFIX = ".peek-write-"
WRITE_CAUSES = re.compile(
    r"^error: (no such file|not a regular file|permission denied|bad range"
    r"|range past end of file \(\d+ lines\)|usage|bad token|cannot read source"
    r"|source not utf-8|hard link refused|write failed|stale token)$"
)
LAST = re.compile(r"^(next: \S.*|end: lines \d+ to \d+ of \d+|done)$")
PROG = shlex.quote(str(LAUNCHER.resolve()))

InProc = Callable[..., tuple[int, str]]
Mksrc = Callable[[bytes | str], Path]


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def err_lines(code: int, cause: str) -> list[str]:
    return [f"exit {code}, 0 lines, 0 bytes", f"error: {cause}", "done"]


def temps(d: Path) -> list[str]:
    return sorted(p.name for p in d.iterdir() if p.name.startswith(TMP_PREFIX))


def get_token(peek: Peek, path: Path | str) -> str:
    r = peek("token", str(path))
    assert r.code == 0, r.text
    assert r.lines[1].startswith("token: ")
    return r.lines[1].removeprefix("token: ")


def do_write(peek: Peek, path: Path | str, rng: str, token: str, src: Path | str, **kw: Any) -> Res:
    return peek("write", str(path), "--lines", rng, "--token", token, "--from", str(src), **kw)


def argv_write(path: Path | str, rng: str, token: str, src: Path | str) -> list[str]:
    return ["write", str(path), "--lines", rng, "--token", token, "--from", str(src)]


def assert_err(res: Res, code: int, cause: str) -> None:
    assert res.lines == err_lines(code, cause), res.text
    assert res.code == code
    assert res.err == b""


def assert_err_text(rc: int, out: str, code: int, cause: str) -> None:
    assert out.split("\n")[:-1] == err_lines(code, cause), out
    assert rc == code


def status_tail(lines: list[str]) -> list[str]:
    """The status lines (replaced, wrote, token, optional sync) before the final line."""
    i = next(k for k, x in enumerate(lines) if x.startswith("replaced lines "))
    return lines[i:-1]


@pytest.fixture
def srcdir(tmp_path: Path) -> Path:
    d = tmp_path / "srcdir"
    d.mkdir()
    return d


@pytest.fixture
def mksrc(srcdir: Path) -> Mksrc:
    def make(content: bytes | str) -> Path:
        p = srcdir / "new.txt"
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)
        return p

    return make


@pytest.fixture
def inproc(capfd: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch) -> InProc:
    monkeypatch.delenv("PEEK_PROG", raising=False)

    def run(*args: str) -> tuple[int, str]:
        from peek.cli import main

        capfd.readouterr()
        rc = main(list(args))
        return rc, capfd.readouterr().out

    return run


@pytest.fixture
def six(mk: Callable[..., Path]) -> Path:
    return mk("six.txt", numbered_text(6))


# ---------------------------------------------------------------------------------------------
# Grammar
# ---------------------------------------------------------------------------------------------


def test_token_ok(peek: Peek, mk: Callable[..., Path]) -> None:
    """1: three lines, exit 0, token is the SHA-256 of the raw bytes."""
    raw = b"a\nb\r\n\xff\xfe\nlast"
    f = mk("f.bin", raw)
    r = peek("token", str(f))
    assert r.code == 0
    assert r.lines == [f"exit 0, 4 lines, {len(raw)} bytes", f"token: {sha(raw)}", "done"]
    assert HEX64.match(r.lines[1].removeprefix("token: "))
    assert r.err == b""


def test_token_empty_file(peek: Peek, mk: Callable[..., Path]) -> None:
    """2: an empty file has 0 lines, 0 bytes and the SHA-256 of empty bytes."""
    f = mk("e.txt", b"")
    r = peek("token", str(f))
    assert r.code == 0
    assert r.lines == ["exit 0, 0 lines, 0 bytes", f"token: {sha(b'')}", "done"]


def test_token_errors(peek: Peek, mk: Callable[..., Path], data: Path) -> None:
    """3: the read causes, exit 2; unreadable case skipped for root."""
    assert_err(peek("token", str(data / "missing")), 2, "no such file")
    assert_err(peek("token", str(data)), 2, "not a regular file")
    assert_err(peek("token", ""), 2, "no such file")
    if os.geteuid() != 0:
        f = mk("secret.txt", "x\n")
        f.chmod(0)
        assert_err(peek("token", str(f)), 2, "permission denied")


USAGE_CASES: list[list[str]] = [
    ["token"],
    ["token", "{f}", "x"],
    ["token", "-f"],
    ["write"],
    ["write", "{f}"],
    ["write", "{f}", "--lines", "1:1", "--token", "{t}"],
    ["write", "{f}", "--token", "{t}", "--lines", "1:1", "--from", "{s}"],
    ["write", "{f}", "--lines=1:1", "--token", "{t}", "--from", "{s}"],
    ["write", "{f}", "--lines", "1:1", "--lines", "1:1", "--token", "{t}", "--from", "{s}"],
    ["write", "{f}", "--lines", "1:1", "--token", "{t}", "--from", "{s}", "--help"],
    ["write", "-f", "--lines", "1:1", "--token", "{t}", "--from", "{s}"],
    ["write", "{f}", "--lines", "1:1", "--token", "{t}", "--from", "-s"],
]


@pytest.mark.parametrize("tmpl", USAGE_CASES, ids=[str(i) for i in range(len(USAGE_CASES))])
def test_usage_cases(peek: Peek, six: Path, mksrc: Mksrc, tmpl: list[str]) -> None:
    """4: bad shapes print the usage error and leave the target alone."""
    before = six.read_bytes()
    subst = {"{f}": str(six), "{t}": sha(before), "{s}": str(mksrc("X\n"))}
    r = peek(*[subst.get(a, a) for a in tmpl])
    assert_err(r, 2, "usage")
    assert six.read_bytes() == before
    assert temps(six.parent) == []


def test_parse_args_unchanged() -> None:
    """5: the old parser still says usage for the new words and parses the old forms as before."""
    from peek.cli import FileCall, RunCall, UsageError, parse_args

    with pytest.raises(UsageError):
        parse_args(["token", "f"])
    with pytest.raises(UsageError):
        parse_args(argv_write("f", "1:1", "0" * 64, "s"))
    assert parse_args(["file", "x"]) == FileCall("x")
    assert parse_args(["file", "x", "--lines", "1:2"]) == FileCall("x", "1:2")
    assert parse_args(["run", "--", "echo", "hi"]) == RunCall(["echo", "hi"])


def test_run_write_is_a_command(peek: Peek) -> None:
    """6: `peek run -- write x` runs a command named write (header with its code), not a write."""
    r = peek("run", "--", "write", "x")
    assert r.lines[0].startswith("exit ")
    assert r.lines[0].startswith(f"exit {r.code}, ")
    assert r.lines != err_lines(2, "usage")
    assert r.last == "done"


def test_file_named_write(peek: Peek, cwd: Path) -> None:
    """7: `peek file write` still reads a file called write."""
    (cwd / "write").write_text("hello\n")
    r = peek("file", "write")
    assert r.code == 0
    assert r.lines == ["lines 1 to 1 of 1", "hello", "end: lines 1 to 1 of 1"]


# ---------------------------------------------------------------------------------------------
# Success and byte exactness
# ---------------------------------------------------------------------------------------------


def test_write_ok_middle(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """8: lines 2:3 replaced; bytes are before + R + after; full output list; token on disk."""
    raw = six.read_bytes()
    tok = get_token(peek, six)
    new = b"L1\nX\nY\nZ\nL4\nL5\nL6\n"
    r = do_write(peek, six, "2:3", tok, mksrc("X\nY\nZ\n"))
    assert r.code == 0
    assert six.read_bytes() == new
    assert raw.startswith(b"L1\n") and new.startswith(b"L1\n")
    assert r.lines == [
        "lines 2 to 4 of 7",
        "X",
        "Y",
        "Z",
        "replaced lines 2 to 3 with 3 lines",
        f"wrote {len(new)} bytes, file now 7 lines",
        f"token: {sha(new)}",
        f"next: {PROG} file {shlex.quote(str(six))} --lines 5:104",
    ]
    assert r.err == b""


def test_write_ends_with_end_line(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """8: a window that reaches the last line ends with `end:`."""
    tok = get_token(peek, six)
    r = do_write(peek, six, "5:6", tok, mksrc("P\nQ\n"))
    assert r.code == 0
    assert r.lines[0] == "lines 5 to 6 of 6"
    assert r.last == "end: lines 5 to 6 of 6"
    assert six.read_bytes() == b"L1\nL2\nL3\nL4\nP\nQ\n"


def test_bytes_outside_range_identical(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """9: CRLF, invalid UTF-8, NUL and blank lines outside the range survive byte for byte."""
    before = b"crlf one\r\n\xff\xfe bad\n\x00nul\n\nOLD1\nOLD2\r\n\n\xc3\x28 tail\r\nlast"
    f = mk("mixed.bin", before)
    tok = get_token(peek, f)
    start = before.index(b"OLD1")
    old = b"OLD1\nOLD2\r\n"
    assert before[start : start + len(old)] == old
    end = start + len(old)
    r = do_write(peek, f, "5:6", tok, mksrc("NEW\n"))
    assert r.code == 0, r.text
    after = f.read_bytes()
    assert after[:start] == before[:start]
    assert after[start:].startswith(b"NEW\n")
    assert after[start + 4 :] == before[end:]


def test_crlf_not_added_or_removed(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """9: a CRLF file edited with an LF source gets exactly the LF the source has."""
    f = mk("crlf.txt", b"a\r\nb\r\nc\r\n")
    tok = get_token(peek, f)
    assert do_write(peek, f, "2:2", tok, mksrc(b"B\r\n")).code == 0
    assert f.read_bytes() == b"a\r\nB\r\nc\r\n"
    tok = get_token(peek, f)
    assert do_write(peek, f, "2:2", tok, mksrc(b"x\n")).code == 0
    assert f.read_bytes() == b"a\r\nx\nc\r\n"


def test_final_newline_kept(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """10: no final newline stays so; a source ending in newline on the last line adds one."""
    f = mk("nofinal.txt", b"a\nb\nc")
    assert do_write(peek, f, "2:2", get_token(peek, f), mksrc(b"B")).code == 0
    assert f.read_bytes() == b"a\nB\nc"
    assert do_write(peek, f, "3:3", get_token(peek, f), mksrc(b"C")).code == 0
    assert f.read_bytes() == b"a\nB\nC"
    assert do_write(peek, f, "3:3", get_token(peek, f), mksrc(b"D\n")).code == 0
    assert f.read_bytes() == b"a\nB\nD\n"


def test_final_newline_present_stays(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """10: a terminated file stays terminated when the source has no newline."""
    f = mk("final.txt", b"a\nb\nc\n")
    assert do_write(peek, f, "3:3", get_token(peek, f), mksrc(b"C")).code == 0
    assert f.read_bytes() == b"a\nb\nC\n"


def test_newline_added_in_middle(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """11: a source without final newline is not glued onto the next line."""
    tok = get_token(peek, six)
    assert do_write(peek, six, "2:3", tok, mksrc(b"X\nY")).code == 0
    assert six.read_bytes() == b"L1\nX\nY\nL4\nL5\nL6\n"


def test_delete_range(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """12: an empty source deletes the lines; one context line is shown."""
    f = mk("five.txt", numbered_text(5))
    tok = get_token(peek, f)
    r = do_write(peek, f, "2:3", tok, mksrc(b""))
    assert r.code == 0
    new = b"L1\nL4\nL5\n"
    assert f.read_bytes() == new
    assert r.lines == [
        "lines 2 to 2 of 3",
        "L4",
        "replaced lines 2 to 3 with 0 lines",
        f"wrote {len(new)} bytes, file now 3 lines",
        f"token: {sha(new)}",
        f"next: {PROG} file {shlex.quote(str(f))} --lines 3:102",
    ]


def test_delete_all_lines(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """13: result is an empty file; empty file lines, status lines, end line."""
    f = mk("two.txt", "a\nb\n")
    tok = get_token(peek, f)
    r = do_write(peek, f, "1:2", tok, mksrc(b""))
    assert r.code == 0
    assert f.read_bytes() == b""
    assert r.lines == [
        "lines 0 to 0 of 0",
        "no output: file is empty",
        "replaced lines 1 to 2 with 0 lines",
        "wrote 0 bytes, file now 0 lines",
        f"token: {sha(b'')}",
        "end: lines 0 to 0 of 0",
    ]


def test_readback_bounds(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """14: 150 new lines show 100, clipped line, next that runs as printed; 400 char cut."""
    f = mk("three.txt", "a\nb\nc\n")
    body = "".join(f"R{i}\n" for i in range(1, 151))
    r = do_write(peek, f, "1:1", get_token(peek, f), mksrc(body))
    assert r.code == 0
    assert r.lines[0] == "lines 1 to 100 of 152"
    assert r.lines[1] == "clipped: requested 1:150"
    assert r.lines[2 : 2 + 100] == [f"R{i}" for i in range(1, 101)]
    assert r.last == f"next: {PROG} file {shlex.quote(str(f))} --lines 101:200"
    nxt = subprocess.run(
        shlex.split(r.last.removeprefix("next: ")),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    assert nxt.returncode == 0
    assert nxt.stdout.decode().split("\n")[0] == "lines 101 to 152 of 152"

    g = mk("one.txt", "a\n")
    r2 = do_write(peek, g, "1:1", get_token(peek, g), mksrc("y" * 500 + "\n"))
    assert r2.code == 0
    assert r2.lines[1] == "y" * 400 + " [cut: 500 chars]"
    assert g.read_bytes() == b"y" * 500 + b"\n"


def test_source_from_stdin(six: Path, cwd: Path, isolated_tmp: Path) -> None:
    """15: `--from /dev/stdin` with piped bytes works."""
    before = six.read_bytes()
    tok = sha(before)
    p = subprocess.run(
        [str(LAUNCHER), *argv_write(six, "1:1", tok, "/dev/stdin")],
        cwd=cwd,
        env={**os.environ, "TMPDIR": str(isolated_tmp), "PYTHONDONTWRITEBYTECODE": "1"},
        input=b"PIPED\n",
        capture_output=True,
    )
    assert p.returncode == 0, p.stdout
    assert six.read_bytes() == b"PIPED\n" + before.split(b"\n", 1)[1]


def test_chained_write(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """16: the token printed by one write is accepted by the next, with no `peek token`."""
    r1 = do_write(peek, six, "1:1", get_token(peek, six), mksrc("A\n"))
    assert r1.code == 0
    tok2 = next(x for x in r1.lines if x.startswith("token: ")).removeprefix("token: ")
    r2 = do_write(peek, six, "2:2", tok2, mksrc("B\n"))
    assert r2.code == 0, r2.text
    assert six.read_bytes() == b"A\nB\nL3\nL4\nL5\nL6\n"


def test_last_line_and_exit_on_success(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """Done condition: exit 0 and the last printed line is next:, end: or done."""
    r = do_write(peek, six, "6:6", get_token(peek, six), mksrc("Z\n"))
    assert r.code == 0
    assert LAST.match(r.last)
    assert r.last.startswith(("next:", "end:")) or r.last == "done"


# ---------------------------------------------------------------------------------------------
# Range
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("rng", ["0:1", "2:1", "a:b", "1:2:3", "", "-1:2", "1:"])
def test_bad_range(peek: Peek, six: Path, mksrc: Mksrc, rng: str) -> None:
    """17: malformed ranges give `bad range`, exit 2, target unchanged."""
    before = six.read_bytes()
    r = do_write(peek, six, rng, sha(before), mksrc("X\n"))
    assert_err(r, 2, "bad range")
    assert six.read_bytes() == before
    assert temps(six.parent) == []


@pytest.mark.parametrize("rng", ["7:7", "5:7", "9:12", "1:100"])
def test_range_past_end(peek: Peek, six: Path, mksrc: Mksrc, rng: str) -> None:
    """18: A or B above N is refused (a write never clamps); target unchanged."""
    before = six.read_bytes()
    r = do_write(peek, six, rng, sha(before), mksrc("X\n"))
    assert_err(r, 2, "range past end of file (6 lines)")
    assert six.read_bytes() == before
    assert temps(six.parent) == []


def test_range_past_end_empty_file(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc) -> None:
    """18: a file with no line refuses every range."""
    f = mk("empty.txt", b"")
    r = do_write(peek, f, "1:1", sha(b""), mksrc("X\n"))
    assert_err(r, 2, "range past end of file (0 lines)")
    assert f.read_bytes() == b""


# ---------------------------------------------------------------------------------------------
# Precondition
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "change",
    [
        b"L1\nL2\nL3\nL4\nL5\nL6X\n",
        b"CHANGED\nL2\nL3\nL4\nL5\nL6\n",
        b"NEW TOP\nL1\nL2\nL3\nL4\nL5\nL6\n",
        b"L1\nL2\nL3\nL4\nL5\nL6",
        b"L1\r\nL2\nL3\nL4\nL5\nL6\n",
        b"",
    ],
    ids=["tail", "top", "shift", "no_final_nl", "crlf", "empty"],
)
def test_stale_token_byte_identical(peek: Peek, six: Path, mksrc: Mksrc, change: bytes) -> None:
    """19: a changed file (also outside the range, also a pure shift) gives exit 3, no change."""
    tok = get_token(peek, six)
    six.write_bytes(change)
    r = do_write(peek, six, "2:3", tok, mksrc("X\n"))
    assert_err(r, 3, "stale token")
    assert six.read_bytes() == change
    assert temps(six.parent) == []


def test_stale_token_after_other_write(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """19: replaying a token after a successful write is stale."""
    tok = get_token(peek, six)
    assert do_write(peek, six, "1:1", tok, mksrc("A\n")).code == 0
    after = six.read_bytes()
    assert_err(do_write(peek, six, "1:1", tok, mksrc("B\n")), 3, "stale token")
    assert six.read_bytes() == after


@pytest.mark.parametrize("bad", ["A" * 64, "a" * 63, "a" * 65, "g" * 64, "", "0x" + "a" * 62])
def test_bad_token(peek: Peek, six: Path, mksrc: Mksrc, bad: str) -> None:
    """20: uppercase, wrong length or non hex tokens give `bad token`, exit 2."""
    before = six.read_bytes()
    r = do_write(peek, six, "1:1", bad, mksrc("X\n"))
    assert_err(r, 2, "bad token")
    assert six.read_bytes() == before


def test_error_precedence(peek: Peek, six: Path, mksrc: Mksrc, data: Path) -> None:
    """22: missing file, bad token, bad range, source errors, stale, range past end, in order."""
    good = sha(six.read_bytes())
    src = mksrc("X\n")
    missing = data / "missing.txt"
    assert_err(do_write(peek, missing, "0:0", "zz", data / "nosrc"), 2, "no such file")
    assert_err(do_write(peek, six, "0:1", "zz", src), 2, "bad token")
    assert_err(do_write(peek, six, "0:1", good, data / "nosrc"), 2, "bad range")
    assert_err(do_write(peek, six, "1:1", "0" * 64, data / "nosrc"), 2, "cannot read source")
    assert_err(do_write(peek, six, "9:9", "0" * 64, src), 3, "stale token")
    assert_err(do_write(peek, six, "9:9", good, src), 2, "range past end of file (6 lines)")


# ---------------------------------------------------------------------------------------------
# Atomicity and temp file (in process, with hooks on os functions)
# ---------------------------------------------------------------------------------------------


@dataclass
class Ctx:
    """One write scenario in process: a six line target and a source, with hook helpers."""

    data: Path
    target: Path
    src: Path
    mp: pytest.MonkeyPatch
    run: InProc

    @property
    def real(self) -> str:
        return str(self.target.resolve())

    @property
    def original(self) -> bytes:
        return b"".join(f"L{i}\n".encode() for i in range(1, 7))

    def write(
        self, rng: str = "2:3", token: str | None = None, src: Path | str | None = None
    ) -> tuple[int, str]:
        tok = sha(self.original) if token is None else token
        return self.run(*argv_write(self.target, rng, tok, self.src if src is None else src))

    def on_file_fsync(self, action: Callable[[], object]) -> None:
        """Run `action` after the first fsync of a non directory descriptor."""
        real_fsync = os.fsync
        state = {"done": False}

        def fsync(fd: int) -> None:
            real_fsync(fd)
            if not state["done"] and not stat.S_ISDIR(os.fstat(fd).st_mode):
                state["done"] = True
                action()

        self.mp.setattr(os, "fsync", fsync)

    def fail_file_fsync(self, exc: BaseException) -> None:
        real_fsync = os.fsync

        def fsync(fd: int) -> None:
            if not stat.S_ISDIR(os.fstat(fd).st_mode):
                raise exc
            real_fsync(fd)

        self.mp.setattr(os, "fsync", fsync)

    def fail_dir_fsync(self) -> None:
        real_fsync = os.fsync

        def fsync(fd: int) -> None:
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError(errno.EIO, "dir fsync")
            real_fsync(fd)

        self.mp.setattr(os, "fsync", fsync)

    def after_realpath(self, action: Callable[[], object]) -> None:
        """Run `action` once, at the first os.path.realpath call on the target (step 5)."""
        real_realpath = os.path.realpath
        state = {"done": False}

        def realpath(p: Any, *a: Any, **k: Any) -> str:
            if not state["done"] and os.fspath(p) == str(self.target):
                state["done"] = True
                action()
            return str(real_realpath(p, *a, **k))

        self.mp.setattr(os.path, "realpath", realpath)

    def armed_open_error(self, exc: OSError) -> None:
        """After step 5, opening the target for reading raises `exc`."""
        import builtins

        real = self.real
        real_open = builtins.open
        state = {"armed": False}

        def fake_open(file: Any, *a: Any, **k: Any) -> Any:
            if state["armed"] and isinstance(file, str | os.PathLike) and (os.fspath(file) == real):
                raise exc
            return real_open(file, *a, **k)

        self.after_realpath(lambda: state.update(armed=True))
        self.mp.setattr(builtins, "open", fake_open)

    def armed_stat_error(self, exc: OSError) -> None:
        real = self.real
        real_stat = os.stat
        state = {"armed": False}

        def fake_stat(p: Any, *a: Any, **k: Any) -> os.stat_result:
            if state["armed"] and isinstance(p, str | os.PathLike) and os.fspath(p) == real:
                raise exc
            return real_stat(p, *a, **k)

        self.after_realpath(lambda: state.update(armed=True))
        self.mp.setattr(os, "stat", fake_stat)

    def check_clean(self, expected: bytes | None) -> None:
        if expected is None:
            assert not self.target.exists()
        else:
            assert self.target.read_bytes() == expected
        assert temps(self.data) == []


@pytest.fixture
def ctx(
    data: Path,
    mk: Callable[..., Path],
    mksrc: Mksrc,
    monkeypatch: pytest.MonkeyPatch,
    inproc: InProc,
) -> Ctx:
    return Ctx(data, mk("six.txt", numbered_text(6)), mksrc("X\nY\n"), monkeypatch, inproc)


def test_stale_at_recheck(ctx: Ctx) -> None:
    """21: a change made between the temp write and the rename gives exit 3, file as changed."""
    changed = b"changed by someone else\n"
    ctx.on_file_fsync(lambda: ctx.target.write_bytes(changed))
    rc, out = ctx.write()
    assert_err_text(rc, out, 3, "stale token")
    ctx.check_clean(changed)


@pytest.mark.parametrize("which", ["fsync", "replace", "fchmod"])
def test_failure_cleans_temp(ctx: Ctx, which: str) -> None:
    """23: an OSError at fsync, replace or fchmod: exit 2 `write failed`, nothing left behind."""
    before = sorted(p.name for p in ctx.data.iterdir())
    if which == "fsync":
        ctx.fail_file_fsync(OSError(errno.EIO, "boom"))
    else:

        def boom(*a: Any, **k: Any) -> None:
            raise OSError(errno.EIO, "boom")

        ctx.mp.setattr(os, which, boom)
    rc, out = ctx.write()
    assert_err_text(rc, out, 2, "write failed")
    ctx.check_clean(ctx.original)
    assert sorted(p.name for p in ctx.data.iterdir()) == before


def test_unexpected_exception_propagates(ctx: Ctx, capfd: pytest.CaptureFixture[str]) -> None:
    """24: a non OSError at step 10 propagates (exit 1 under python), no output, no temp file."""
    ctx.fail_file_fsync(RuntimeError("boom"))
    capfd.readouterr()
    with pytest.raises(RuntimeError):
        ctx.write()
    assert capfd.readouterr().out == ""
    ctx.check_clean(ctx.original)


def test_unexpected_exception_exit_code_1(ctx: Ctx) -> None:
    """24: through python -m peek the same failure ends with exit 1 and an empty stdout."""
    shim = ctx.data.parent / "shim"
    shim.mkdir()
    (shim / "run.py").write_text(
        "import os, sys\n"
        "from peek.cli import main\n"
        "def f(fd):\n"
        "    raise RuntimeError('boom')\n"
        "os.fsync = f\n"
        "sys.exit(main(sys.argv[1:]))\n"
    )
    p = subprocess.run(
        [
            "python3",
            "-X",
            "utf8",
            str(shim / "run.py"),
            *argv_write(ctx.target, "2:3", sha(ctx.original), ctx.src),
        ],
        env={**os.environ, "PYTHONPATH": str(SRC), "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    assert p.returncode == 1
    assert p.stdout == b""
    assert b"RuntimeError" in p.stderr
    ctx.check_clean(ctx.original)


def test_no_partial_file(ctx: Ctx) -> None:
    """25: a write that fails after half the bytes leaves the original bytes."""
    real_write = os.write

    def half(fd: int, data: Any) -> int:
        b = bytes(data)
        real_write(fd, b[: len(b) // 2])
        raise OSError(errno.ENOSPC, "disk full")

    ctx.mp.setattr(os, "write", half)
    rc, out = ctx.write()
    assert rc in (2,)
    assert out.split("\n")[1] == "error: write failed"
    ctx.check_clean(ctx.original)


def test_temp_in_real_dir(data: Path, tmp_path: Path, mksrc: Mksrc, ctx: Ctx) -> None:
    """26: with a symlink in another directory, the temp file is created beside the real file."""
    other = tmp_path / "other"
    other.mkdir()
    link = other / "link.txt"
    link.symlink_to(ctx.target)
    seen: dict[str, list[str]] = {}

    def look() -> None:
        seen["real"] = temps(data)
        seen["link"] = temps(other)

    ctx.on_file_fsync(look)
    rc, out = ctx.run(*argv_write(link, "2:3", sha(ctx.original), ctx.src))
    assert rc == 0, out
    assert len(seen["real"]) == 1
    assert seen["link"] == []
    assert temps(data) == [] and temps(other) == []


def test_sync_order(ctx: Ctx) -> None:
    """27: fsync of the temp file before os.replace, fsync of the directory after it."""
    events: list[str] = []
    real_fsync, real_replace = os.fsync, os.replace

    def fsync(fd: int) -> None:
        events.append("fsync-dir" if stat.S_ISDIR(os.fstat(fd).st_mode) else "fsync-file")
        real_fsync(fd)

    def replace(a: Any, b: Any) -> None:
        events.append("replace")
        real_replace(a, b)

    ctx.mp.setattr(os, "fsync", fsync)
    ctx.mp.setattr(os, "replace", replace)
    rc, out = ctx.write()
    assert rc == 0, out
    assert events.count("replace") == 1
    i = events.index("replace")
    assert "fsync-file" in events[:i]
    assert "fsync-dir" not in events[:i]
    assert "fsync-dir" in events[i + 1 :]


def test_dir_fsync_failure_is_success(ctx: Ctx) -> None:
    """28: a failing directory fsync is still success, with the sync line."""
    ctx.fail_dir_fsync()
    rc, out = ctx.write()
    lines = out.split("\n")[:-1]
    assert rc == 0, out
    assert ctx.target.read_bytes() == b"L1\nX\nY\nL4\nL5\nL6\n"
    assert status_tail(lines)[-1] == "sync: directory fsync failed"
    assert lines[-1].startswith(("next:", "end:"))
    assert temps(ctx.data) == []


# ---------------------------------------------------------------------------------------------
# Metadata, links
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", [0o644, 0o755, 0o600, 0o664, 0o640])
def test_mode_kept(peek: Peek, mk: Callable[..., Path], mksrc: Mksrc, mode: int) -> None:
    """29: permission bits survive the replace."""
    f = mk("m.txt", numbered_text(3))
    f.chmod(mode)
    r = do_write(peek, f, "1:1", get_token(peek, f), mksrc("Z\n"))
    assert r.code == 0, r.text
    assert stat.S_IMODE(f.stat().st_mode) == mode
    assert f.read_bytes() == b"Z\nL2\nL3\n"


def test_symlink_target_written(
    peek: Peek, data: Path, mk: Callable[..., Path], mksrc: Mksrc
) -> None:
    """30: the target of a symlink is written and the link stays a link to the same target."""
    real = mk("real/target.txt", numbered_text(3))
    link = data / "link.txt"
    link.symlink_to(real)
    tok = get_token(peek, link)
    r = do_write(peek, link, "2:2", tok, mksrc("S\n"))
    assert r.code == 0, r.text
    assert link.is_symlink()
    assert os.readlink(link) == str(real)
    assert real.read_bytes() == b"L1\nS\nL3\n"
    assert temps(real.parent) == [] and temps(data) == []


def test_hard_link_refused(peek: Peek, mk: Callable[..., Path], data: Path, mksrc: Mksrc) -> None:
    """31: two names of one inode: refused, both files unchanged, no temp file."""
    a = mk("a.txt", numbered_text(3))
    b = data / "b.txt"
    os.link(a, b)
    before = a.read_bytes()
    r = do_write(peek, a, "1:1", sha(before), mksrc("X\n"))
    assert_err(r, 2, "hard link refused")
    assert a.read_bytes() == before and b.read_bytes() == before
    assert a.stat().st_ino == b.stat().st_ino
    assert temps(data) == []


def test_foreign_owner_refused(ctx: Ctx) -> None:
    """32: a file not owned by the caller is refused (geteuid patched; a real owner needs root)."""
    ctx.mp.setattr(os, "geteuid", lambda: ctx.target.stat().st_uid + 1)
    rc, out = ctx.write()
    assert_err_text(rc, out, 2, "permission denied")
    ctx.check_clean(ctx.original)


def test_source_errors(peek: Peek, six: Path, mksrc: Mksrc, data: Path, srcdir: Path) -> None:
    """33: missing, directory and empty path sources; invalid UTF-8 source; target unchanged."""
    before = six.read_bytes()
    tok = sha(before)
    assert_err(do_write(peek, six, "1:1", tok, data / "nosrc"), 2, "cannot read source")
    assert_err(do_write(peek, six, "1:1", tok, srcdir), 2, "cannot read source")
    assert_err(do_write(peek, six, "1:1", tok, ""), 2, "cannot read source")
    assert_err(do_write(peek, six, "1:1", tok, mksrc(b"ok\n\xff\xfe\n")), 2, "source not utf-8")
    assert six.read_bytes() == before
    assert temps(data) == []


# ---------------------------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------------------------


READ_CASES: list[tuple[list[str], int, list[str]]] = [
    (["file", "{ok}"], 0, ["lines 1 to 3 of 3", "a", "b", "c", "end: lines 1 to 3 of 3"]),
    (
        ["file", "{ok}", "--lines", "2:9"],
        0,
        ["lines 2 to 3 of 3", "b", "c", "end: lines 2 to 3 of 3"],
    ),
    (["file", "{missing}"], 2, err_lines(2, "no such file")),
    (["file", "{ok}", "--lines", "9:9"], 2, err_lines(2, "range past end of file (3 lines)")),
    (["file", "{ok}", "--lines", "0:1"], 2, err_lines(2, "bad range")),
    (["run", "--", "echo", "hi"], 0, ["exit 0, 1 lines, 3 bytes", "hi", "done"]),
    (
        ["run", "--", "sh", "-c", "exit 3"],
        3,
        ["exit 3, 0 lines, 0 bytes", "no output: exit 3", "done"],
    ),
    (["run", "--", "peek-no-such-command-9f3a1c"], 127, err_lines(127, "command not found")),
    (["bogus"], 2, err_lines(2, "usage")),
]


@pytest.mark.parametrize(
    "tmpl,code,expected", READ_CASES, ids=[str(i) for i in range(len(READ_CASES))]
)
def test_reads_unchanged(
    peek: Peek, mk: Callable[..., Path], data: Path, tmpl: list[str], code: int, expected: list[str]
) -> None:
    """34: `peek file` and `peek run` output and exit codes equal literals recorded before."""
    ok = mk("ok.txt", "a\nb\nc\n")
    subst = {"{ok}": str(ok), "{missing}": str(data / "missing")}
    r = peek(*[subst.get(a, a) for a in tmpl])
    assert r.code == code
    assert r.lines == expected
    assert r.err == b""


def test_reads_unchanged_all_scenarios(peek: Peek, tmp_path: Path) -> None:
    """34: the shared scenarios still end in the closed kinds and never print a write cause only."""
    for name, args, kind in make_scenarios(tmp_path / "sc"):
        r = peek(*args)
        assert r.last.startswith(kind) if kind != "done" else r.last == "done", name
        assert r.err == b"", name


def test_lines_cmd_run_output_unchanged(peek: Peek) -> None:
    """34: a capped run keeps its shape (header, omitted line, full output, next)."""
    r = peek("run", "--", *lines_cmd(100))
    assert r.code == 0
    assert r.first == "exit 0, 100 lines, 392 bytes"
    assert any(x.startswith("omitted ") for x in r.lines)
    assert r.last.startswith("next: ")


def test_token_creates_nothing(peek: Peek, six: Path, cwd: Path, isolated_tmp: Path) -> None:
    """35: `peek token` creates nothing in the data dir, cwd or tmp dir."""
    snaps = (snapshot(six.parent), snapshot(cwd), snapshot(isolated_tmp))
    assert peek("token", str(six)).code == 0
    assert (snapshot(six.parent), snapshot(cwd), snapshot(isolated_tmp)) == snaps


def test_write_creates_nothing_else(
    peek: Peek, six: Path, mksrc: Mksrc, cwd: Path, isolated_tmp: Path
) -> None:
    """36: after a success the directory holds the same names and no spill appears."""
    names = sorted(p.name for p in six.parent.iterdir())
    snaps = (snapshot(cwd), snapshot(isolated_tmp))
    r = do_write(peek, six, "2:3", get_token(peek, six), mksrc("X\n"))
    assert r.code == 0
    assert sorted(p.name for p in six.parent.iterdir()) == names
    assert (snapshot(cwd), snapshot(isolated_tmp)) == snaps


def test_no_forbidden_imports() -> None:
    """37: the source tree (including the write module) imports no network module."""
    from test_contain import scan_forbidden_imports

    assert scan_forbidden_imports(SRC) == []


def test_write_output_is_one_write(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """38: one stdout text ending in a newline, nothing on stderr, on success and on error."""
    ok = do_write(peek, six, "1:1", get_token(peek, six), mksrc("A\n"))
    bad = do_write(peek, six, "1:1", "0" * 64, mksrc("A\n"))
    for r in (ok, bad):
        assert r.err == b""
        assert r.raw.endswith(b"\n") and not r.raw.endswith(b"\n\n")
    tok = peek("token", str(six))
    assert tok.err == b"" and tok.raw.endswith(b"\n")


def test_usage_md_still_valid() -> None:
    """39: bin/USAGE.md keeps its limits and the sentence the usage test pins."""
    text = (BIN / "USAGE.md").read_text(encoding="utf-8")
    assert len(text.splitlines()) <= 30
    assert "For a file over 200 lines, use peek file instead of Read." in text


def test_stat_vanishes_step6(ctx: Ctx) -> None:
    """40: the target vanishes after step 2: `no such file`, exit 2 (row F8)."""
    ctx.after_realpath(lambda: ctx.target.unlink())
    rc, out = ctx.write()
    assert_err_text(rc, out, 2, "no such file")
    ctx.check_clean(None)


def test_deleted_during_recheck(ctx: Ctx) -> None:
    """41: deleted at step 12 is `stale token`, exit 3, not `write failed`; temp file removed."""
    ctx.on_file_fsync(lambda: ctx.target.unlink())
    rc, out = ctx.write()
    assert_err_text(rc, out, 3, "stale token")
    ctx.check_clean(None)


def test_link_added_at_recheck(ctx: Ctx) -> None:
    """42: a hard link made between steps 6 and 12 is `stale token`, not `hard link refused`."""
    ctx.on_file_fsync(lambda: os.link(ctx.target, ctx.data / "extra-link.txt"))
    rc, out = ctx.write()
    assert_err_text(rc, out, 3, "stale token")
    assert ctx.target.read_bytes() == ctx.original
    assert (ctx.data / "extra-link.txt").read_bytes() == ctx.original
    assert temps(ctx.data) == []


def test_empty_file_sync_line(ctx: Ctx) -> None:
    """43: delete all lines with a directory fsync failure: status lines 4 to 7 incl. sync."""
    ctx.fail_dir_fsync()
    empty = ctx.data.parent / "srcdir" / "empty.txt"
    empty.write_bytes(b"")
    rc, out = ctx.write(rng="1:6", src=empty)
    assert rc == 0, out
    assert out.split("\n")[:-1] == [
        "lines 0 to 0 of 0",
        "no output: file is empty",
        "replaced lines 1 to 6 with 0 lines",
        "wrote 0 bytes, file now 0 lines",
        f"token: {sha(b'')}",
        "sync: directory fsync failed",
        "end: lines 0 to 0 of 0",
    ]
    assert ctx.target.read_bytes() == b""


# ---------------------------------------------------------------------------------------------
# 44: the failure table, one scenario per row F1 to F22
# ---------------------------------------------------------------------------------------------


def _f1(c: Ctx) -> None:
    rc, out = c.run("write", str(c.target))
    assert_err_text(rc, out, 2, "usage")
    c.check_clean(c.original)


def _f2(c: Ctx) -> None:
    rc, out = c.run(*argv_write(c.data / "missing", "1:1", "0" * 64, c.src))
    assert_err_text(rc, out, 2, "no such file")
    rc, out = c.run(*argv_write(c.data, "1:1", "0" * 64, c.src))
    assert_err_text(rc, out, 2, "not a regular file")


def _f3(c: Ctx) -> None:
    assert_err_text(*c.write(token="XYZ"), 2, "bad token")
    c.check_clean(c.original)


def _f4(c: Ctx) -> None:
    assert_err_text(*c.write(rng="3:2"), 2, "bad range")
    c.check_clean(c.original)


def _f5(c: Ctx) -> None:
    assert_err_text(*c.write(src=c.data / "nosrc"), 2, "cannot read source")
    c.check_clean(c.original)


def _f6(c: Ctx) -> None:
    c.src.write_bytes(b"\xff\xfe")
    assert_err_text(*c.write(), 2, "source not utf-8")
    c.check_clean(c.original)


def _f7(c: Ctx) -> None:
    c.armed_stat_error(PermissionError(errno.EACCES, "denied"))
    assert_err_text(*c.write(), 2, "permission denied")
    c.check_clean(c.original)


def _f8(c: Ctx) -> None:
    c.armed_stat_error(OSError(errno.EIO, "gone"))
    assert_err_text(*c.write(), 2, "no such file")
    c.check_clean(c.original)


def _f9(c: Ctx) -> None:
    os.link(c.target, c.data / "second.txt")
    assert_err_text(*c.write(), 2, "hard link refused")
    c.check_clean(c.original)


def _f10(c: Ctx) -> None:
    c.mp.setattr(os, "geteuid", lambda: c.target.stat().st_uid + 1)
    assert_err_text(*c.write(), 2, "permission denied")
    c.check_clean(c.original)


def _f11(c: Ctx) -> None:
    c.armed_open_error(PermissionError(errno.EACCES, "denied"))
    assert_err_text(*c.write(), 2, "permission denied")
    c.check_clean(c.original)


def _f12(c: Ctx) -> None:
    c.armed_open_error(OSError(errno.EIO, "io"))
    assert_err_text(*c.write(), 2, "no such file")
    c.check_clean(c.original)


def _f13(c: Ctx) -> None:
    assert_err_text(*c.write(token="0" * 64), 3, "stale token")
    c.check_clean(c.original)


def _f14(c: Ctx) -> None:
    assert_err_text(*c.write(rng="5:9"), 2, "range past end of file (6 lines)")
    c.check_clean(c.original)


def _f15(c: Ctx) -> None:
    c.fail_file_fsync(PermissionError(errno.EACCES, "denied"))
    assert_err_text(*c.write(), 2, "permission denied")
    c.check_clean(c.original)


def _f16(c: Ctx) -> None:
    c.fail_file_fsync(OSError(errno.ENOSPC, "full"))
    assert_err_text(*c.write(), 2, "write failed")
    c.check_clean(c.original)


def _f17(c: Ctx) -> None:
    changed = b"changed\n"
    c.on_file_fsync(lambda: c.target.write_bytes(changed))
    assert_err_text(*c.write(), 3, "stale token")
    c.check_clean(changed)


def _replace_fails(c: Ctx, exc: OSError) -> None:
    def boom(*a: Any, **k: Any) -> None:
        raise exc

    c.mp.setattr(os, "replace", boom)


def _f18(c: Ctx) -> None:
    _replace_fails(c, PermissionError(errno.EACCES, "denied"))
    assert_err_text(*c.write(), 2, "permission denied")
    c.check_clean(c.original)


def _f19(c: Ctx) -> None:
    _replace_fails(c, OSError(errno.EXDEV, "cross device"))
    assert_err_text(*c.write(), 2, "write failed")
    c.check_clean(c.original)


def _f20(c: Ctx) -> None:
    c.fail_dir_fsync()
    rc, out = c.write()
    assert rc == 0
    assert "sync: directory fsync failed" in out.split("\n")
    assert c.target.read_bytes() == b"L1\nX\nY\nL4\nL5\nL6\n"
    assert temps(c.data) == []


def _f21(c: Ctx) -> None:
    rc, out = c.write()
    assert rc == 0
    assert "sync: directory fsync failed" not in out
    assert out.split("\n")[-2].startswith(("next:", "end:"))
    assert c.target.read_bytes() == b"L1\nX\nY\nL4\nL5\nL6\n"
    assert temps(c.data) == []


def _f22(c: Ctx) -> None:
    c.fail_file_fsync(RuntimeError("boom"))
    with pytest.raises(RuntimeError):
        c.write()
    c.check_clean(c.original)


ROWS: dict[str, Callable[[Ctx], None]] = {
    "F1": _f1,
    "F2": _f2,
    "F3": _f3,
    "F4": _f4,
    "F5": _f5,
    "F6": _f6,
    "F7": _f7,
    "F8": _f8,
    "F9": _f9,
    "F10": _f10,
    "F11": _f11,
    "F12": _f12,
    "F13": _f13,
    "F14": _f14,
    "F15": _f15,
    "F16": _f16,
    "F17": _f17,
    "F18": _f18,
    "F19": _f19,
    "F20": _f20,
    "F21": _f21,
    "F22": _f22,
}


@pytest.mark.parametrize("row", list(ROWS))
def test_failure_table_walk(ctx: Ctx, row: str) -> None:
    """44: each row forces its own condition and shows exactly its lines and exit code."""
    ROWS[row](ctx)


def test_write_causes_are_a_closed_list(peek: Peek, six: Path, mksrc: Mksrc) -> None:
    """Every write error line is one of the closed write causes."""
    src = mksrc("X\n")
    for rng, tok in [("0:1", sha(six.read_bytes())), ("1:1", "0" * 64), ("1:1", "bad")]:
        r = do_write(peek, six, rng, tok, src)
        assert WRITE_CAUSES.match(r.lines[1]), r.text
        assert r.lines[0] == f"exit {r.code}, 0 lines, 0 bytes"
        assert r.last == "done"
