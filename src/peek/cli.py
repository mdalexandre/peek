"""Command line: route the four words, run them, print one text on stdout."""

from __future__ import annotations

import sys
from dataclasses import dataclass

from peek import render, write
from peek.run import run_command
from peek.spill import write_spill
from peek.window import MAX_LINES, classify_path, file_window, parse_range, split_lines


@dataclass(frozen=True)
class FileCall:
    path: str
    lines: str | None = None


@dataclass(frozen=True)
class RunCall:
    argv: list[str]


class UsageError(Exception):
    """The invocation is not one of the two valid grammars."""


Call = FileCall | RunCall


def parse_args(argv: list[str]) -> Call:
    """Parse argv into a FileCall or RunCall, or raise UsageError."""
    if len(argv) >= 3 and argv[0] == "run" and argv[1] == "--":
        return RunCall(list(argv[2:]))
    if argv[:1] == ["file"]:
        if len(argv) == 2 and not argv[1].startswith("-"):
            return FileCall(argv[1])
        if len(argv) == 4 and not argv[1].startswith("-") and argv[2] == "--lines":
            return FileCall(argv[1], argv[3])
    raise UsageError("usage")


def _file(call: FileCall) -> tuple[int, list[str]]:
    cause = classify_path(call.path)
    if cause is None:
        try:
            with open(call.path, "rb") as handle:
                raw = handle.read()
        except PermissionError:
            cause = "permission denied"
        except OSError:
            cause = "no such file"
    if cause is not None:
        return 2, render.render_error(2, cause)
    text = raw.decode("utf-8", "replace")
    lines = split_lines(text)
    n = len(lines)
    if n == 0:
        return 0, render.render_empty_file()
    requested = (1, MAX_LINES) if call.lines is None else parse_range(call.lines)
    if requested is None:
        return 2, render.render_error(2, "bad range")
    if requested[0] > n:
        return 2, render.render_error(2, f"range past end of file ({n} lines)")
    window = file_window(lines, requested[0], requested[1])
    return 0, render.render_file(call.path, window, requested, n)


def _run(call: RunCall) -> tuple[int, list[str]]:
    result = run_command(call.argv)
    if result.exec_error is not None:
        return result.code, render.render_error(result.code, result.exec_error)
    if not result.raw:
        return result.code, render.render_empty_run(result.code)
    text = result.raw.decode("utf-8", "replace")
    lines = split_lines(text)
    spill = write_spill(result.raw) if render.is_capped(text, len(lines)) else None
    return result.code, render.render_run(result.code, text, lines, len(result.raw), spill)


def main(argv: list[str] | None = None) -> int:
    """Run peek and return the exit code; all output goes to stdout in one write."""
    args = sys.argv[1:] if argv is None else argv
    if args[:1] == ["token"]:
        code, out = write.run_token(args)
    elif args[:1] == ["write"]:
        code, out = write.run_write(args)
    else:
        try:
            call = parse_args(args)
        except UsageError:
            code, out = 2, render.render_error(2, "usage")
        else:
            code, out = _file(call) if isinstance(call, FileCall) else _run(call)
    data = ("\n".join(out) + "\n").encode("utf-8", "replace")
    try:
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()
    except BrokenPipeError:
        pass
    return code
