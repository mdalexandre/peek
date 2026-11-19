"""The write command: token computation, range splice and atomic replace.

Two entry points, run_token and run_write, each return (exit_code, output_lines) like the
file and run functions of cli.py. Their argument is the argv list that starts with the verb.
"""

from __future__ import annotations

import hashlib
import os
import re
import stat
import tempfile
from dataclasses import dataclass

from peek import render
from peek.window import classify_path, file_window, parse_range, split_lines

_TOKEN = re.compile(r"[0-9a-f]{64}", re.ASCII)

EXIT_ERROR = 2
EXIT_STALE = 3


class WriteUsageError(Exception):
    """The argv is not a valid token or write form."""


class _Fail(Exception):
    """A closed failure row: exit code and cause."""

    def __init__(self, code: int, cause: str) -> None:
        super().__init__(cause)
        self.code = code
        self.cause = cause


@dataclass(frozen=True)
class TokenCall:
    path: str


@dataclass(frozen=True)
class WriteCall:
    path: str
    lines: str
    token: str
    source: str


def parse_token(argv: list[str]) -> TokenCall:
    """Parse `token PATH`, or raise WriteUsageError."""
    if len(argv) == 2 and argv[0] == "token" and not argv[1].startswith("-"):
        return TokenCall(argv[1])
    raise WriteUsageError("usage")


def parse_write(argv: list[str]) -> WriteCall:
    """Parse `write PATH --lines A:B --token TOKEN --from SRC` (fixed order), or raise."""
    if (
        len(argv) == 8
        and argv[0] == "write"
        and not argv[1].startswith("-")
        and argv[2] == "--lines"
        and argv[4] == "--token"
        and argv[6] == "--from"
        and not argv[7].startswith("-")
    ):
        return WriteCall(argv[1], argv[3], argv[5], argv[7])
    raise WriteUsageError("usage")


def token_of(raw: bytes) -> str:
    """The token: SHA-256 hex of the raw bytes."""
    return hashlib.sha256(raw).hexdigest()


def line_starts(raw: bytes) -> list[int]:
    """Byte offset of the start of each line; one entry per line (zero bytes is no lines)."""
    starts = [0]
    index = raw.find(b"\n")
    while index != -1:
        starts.append(index + 1)
        index = raw.find(b"\n", index + 1)
    if starts[-1] == len(raw):
        starts.pop()
    return starts


def splice(raw: bytes, a: int, b: int, source: bytes) -> tuple[bytes, bytes]:
    """Replace lines a..b (1 based, b <= line count) of raw by source, byte exact outside.

    Return (new bytes, the final replacement R after the newline rule).
    """
    starts = line_starts(raw)
    start = starts[a - 1]
    end = starts[b] if b < len(starts) else len(raw)
    replacement = source
    if (
        replacement
        and not replacement.endswith(b"\n")
        and (end < len(raw) or raw[start:end].endswith(b"\n"))
    ):
        replacement += b"\n"
    return raw[:start] + replacement + raw[end:], replacement


def _read_target(path: str) -> bytes:
    """Whole file as raw bytes; PermissionError and other OSError map to closed causes."""
    try:
        with open(path, "rb") as handle:
            return handle.read()
    except PermissionError:
        raise _Fail(EXIT_ERROR, "permission denied") from None
    except OSError:
        raise _Fail(EXIT_ERROR, "no such file") from None


def _error(fail: _Fail) -> tuple[int, list[str]]:
    return fail.code, render.render_error(fail.code, fail.cause)


def run_token(argv: list[str]) -> tuple[int, list[str]]:
    """peek token PATH: header, token line, done."""
    try:
        call = parse_token(argv)
    except WriteUsageError:
        return 2, render.render_error(2, "usage")
    cause = classify_path(call.path)
    if cause is not None:
        return 2, render.render_error(2, cause)
    try:
        raw = _read_target(os.path.realpath(call.path))
    except _Fail as fail:
        return _error(fail)
    count = len(split_lines(raw.decode("utf-8", "replace")))
    return 0, [render.header_run(0, count, len(raw)), f"token: {token_of(raw)}", "done"]


def _build_output(path: str, new: bytes, a: int, b: int, k: int, sync_failed: bool) -> list[str]:
    new_lines = split_lines(new.decode("utf-8", "replace"))
    n_new = len(new_lines)
    status = [
        f"replaced lines {a} to {b} with {k} lines",
        f"wrote {len(new)} bytes, file now {n_new} lines",
        f"token: {token_of(new)}",
    ]
    if sync_failed:
        status.append("sync: directory fsync failed")
    if n_new == 0:
        out = render.render_empty_file()
    else:
        if k > 0:
            requested = (a, a + k - 1)
        else:
            context = min(a, n_new)
            requested = (context, context)
        window = file_window(new_lines, requested[0], requested[1])
        out = render.render_file(path, window, requested, n_new)
    return out[:-1] + status + out[-1:]


def _replace_atomically(call: WriteCall, real: str, st: os.stat_result, new: bytes) -> bool:
    """Steps 8 to 14. Return True when the directory fsync failed after the rename."""
    directory = os.path.dirname(real)
    try:
        fd, tmp = tempfile.mkstemp(dir=directory, prefix=".peek-write-")
    except PermissionError:
        raise _Fail(EXIT_ERROR, "permission denied") from None
    except OSError:
        raise _Fail(EXIT_ERROR, "write failed") from None
    renamed = False
    try:
        try:
            view = memoryview(new)
            while view:
                view = view[os.write(fd, view) :]
            os.fsync(fd)
            os.fchmod(fd, stat.S_IMODE(st.st_mode))
            try:
                os.fchown(fd, -1, st.st_gid)
            except PermissionError:
                pass
        except PermissionError:
            raise _Fail(EXIT_ERROR, "permission denied") from None
        except OSError:
            raise _Fail(EXIT_ERROR, "write failed") from None
        try:
            ok = (
                os.path.realpath(call.path) == real
                and os.stat(real).st_nlink == 1
                and token_of(_read_raw(real)) == call.token
            )
        except Exception:
            ok = False
        if not ok:
            raise _Fail(EXIT_STALE, "stale token")
        try:
            os.replace(tmp, real)
        except PermissionError:
            raise _Fail(EXIT_ERROR, "permission denied") from None
        except OSError:
            raise _Fail(EXIT_ERROR, "write failed") from None
        renamed = True
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        if not renamed:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
    try:
        dfd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(dfd)
        finally:
            os.close(dfd)
    except OSError:
        return True
    return False


def _read_raw(path: str) -> bytes:
    with open(path, "rb") as handle:
        return handle.read()


def _write(call: WriteCall) -> tuple[int, list[str]]:
    cause = classify_path(call.path)
    if cause is not None:
        raise _Fail(EXIT_ERROR, cause)
    if not _TOKEN.fullmatch(call.token):
        raise _Fail(EXIT_ERROR, "bad token")
    requested = parse_range(call.lines)
    if requested is None:
        raise _Fail(EXIT_ERROR, "bad range")
    a, b = requested
    try:
        source = _read_raw(call.source)
    except (OSError, ValueError):
        raise _Fail(EXIT_ERROR, "cannot read source") from None
    try:
        source.decode("utf-8")
    except UnicodeDecodeError:
        raise _Fail(EXIT_ERROR, "source not utf-8") from None
    real = os.path.realpath(call.path)
    try:
        st = os.stat(real)
    except PermissionError:
        raise _Fail(EXIT_ERROR, "permission denied") from None
    except OSError:
        raise _Fail(EXIT_ERROR, "no such file") from None
    if st.st_nlink > 1:
        raise _Fail(EXIT_ERROR, "hard link refused")
    if st.st_uid != os.geteuid():
        raise _Fail(EXIT_ERROR, "permission denied")
    raw = _read_target(real)
    if token_of(raw) != call.token:
        raise _Fail(EXIT_STALE, "stale token")
    n = len(line_starts(raw))
    if a > n or b > n:
        raise _Fail(EXIT_ERROR, f"range past end of file ({n} lines)")
    new, replacement = splice(raw, a, b, source)
    k = len(split_lines(replacement.decode("utf-8")))
    sync_failed = _replace_atomically(call, real, st, new)
    return 0, _build_output(call.path, new, a, b, k, sync_failed)


def run_write(argv: list[str]) -> tuple[int, list[str]]:
    """peek write PATH --lines A:B --token TOKEN --from SRC."""
    try:
        call = parse_write(argv)
    except WriteUsageError:
        return 2, render.render_error(2, "usage")
    try:
        return _write(call)
    except _Fail as fail:
        return _error(fail)
