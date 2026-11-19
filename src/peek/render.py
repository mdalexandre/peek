"""Output text: every line peek prints is built here."""

from __future__ import annotations

import os
import shlex

from peek.window import LINE_CAP, MAX_LINES, Window

RUN_MAX_LINES = 50
RUN_MAX_CHARS = 16000
HEAD_LINES = 30
TAIL_LINES = 20
PART_BUDGET = 8000


def cut_line(line: str) -> str:
    """Cut a displayed line to 400 characters plus ` [cut: N chars]` when it is longer."""
    if len(line) <= LINE_CAP:
        return line
    return f"{line[:LINE_CAP]} [cut: {len(line)} chars]"


def _cost(line: str) -> int:
    return min(len(line), LINE_CAP)


def program() -> str:
    """The program word of a printed peek command."""
    prog = os.environ.get("PEEK_PROG")
    return shlex.quote(prog) if prog else "peek"


def header_file(a: int, b: int, n: int) -> str:
    return f"lines {a} to {b} of {n}"


def header_run(code: int, lines: int, size: int) -> str:
    return f"exit {code}, {lines} lines, {size} bytes"


def next_line(path: str, b: int) -> str:
    return f"next: {program()} file {shlex.quote(path)} --lines {b + 1}:{b + MAX_LINES}"


def terminal_line(kind: str, text: str = "") -> str:
    """kind is next, end or done; text is the rest of a next or end line."""
    return "done" if kind == "done" else f"{kind}: {text}"


def full_output_line(spill: str, size: int) -> str:
    return f"full output: {spill} ({size} bytes)"


def render_error(code: int, cause: str) -> list[str]:
    return [header_run(code, 0, 0), f"error: {cause}", "done"]


def render_empty_run(code: int) -> list[str]:
    return [header_run(code, 0, 0), f"no output: exit {code}", "done"]


def render_empty_file() -> list[str]:
    return [header_file(0, 0, 0), "no output: file is empty", "end: lines 0 to 0 of 0"]


def render_file(path: str, window: Window, requested: tuple[int, int], n: int) -> list[str]:
    """Header, optional clipped line, cut body lines, then next or end."""
    out = [header_file(window.a, window.b, n)]
    if window.clipped:
        out.append(f"clipped: requested {requested[0]}:{requested[1]}")
    out.extend(cut_line(x) for x in window.lines)
    if window.b < n:
        out.append(next_line(path, window.b))
    else:
        out.append(f"end: lines {window.a} to {n} of {n}")
    return out


def is_capped(text: str, total: int) -> bool:
    return total > RUN_MAX_LINES or len(text) > RUN_MAX_CHARS


def select_head(lines: list[str]) -> int:
    """H: lines taken from the start, at most 30, shown characters at most 8000."""
    count = 0
    spent = 0
    while count < len(lines) and count < HEAD_LINES:
        cost = _cost(lines[count])
        if spent + cost > PART_BUDGET:
            break
        spent += cost
        count += 1
    return count


def select_tail(lines: list[str], head: int) -> int:
    """T: lines taken from the end, at most 20, 8000 shown characters, never from the head."""
    count = 0
    spent = 0
    while count < TAIL_LINES and len(lines) - 1 - count >= head:
        cost = _cost(lines[len(lines) - 1 - count])
        if spent + cost > PART_BUDGET:
            break
        spent += cost
        count += 1
    return count


def render_run(code: int, text: str, lines: list[str], size: int, spill: str | None) -> list[str]:
    """Uncapped: all lines. Capped (spill given): head, omitted, tail, full output, next."""
    total = len(lines)
    out = [header_run(code, total, size)]
    if spill is None:
        out.extend(cut_line(x) for x in lines)
        out.append("done")
        return out
    head = select_head(lines)
    tail = select_tail(lines, head)
    out.extend(cut_line(x) for x in lines[:head])
    out.append(f"omitted {total - head - tail} lines of {total}")
    out.extend(cut_line(x) for x in lines[total - tail :])
    out.append(full_output_line(spill, size))
    if head + tail < total:
        out.append(next_line(spill, head))
    else:
        out.append("done")
    return out
