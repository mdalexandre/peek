"""File windows: line splitting, range parsing, path classification, window selection."""

from __future__ import annotations

import errno
import os
import re
import stat
from dataclasses import dataclass

MAX_LINES = 100
CHAR_BUDGET = 16000
LINE_CAP = 400

_RANGE = re.compile(r"[1-9][0-9]*:[1-9][0-9]*", re.ASCII)


def split_lines(text: str) -> list[str]:
    """Split on newline only; an unterminated last piece is a line; zero bytes is no lines."""
    if not text:
        return []
    parts = text.split("\n")
    if text.endswith("\n"):
        parts.pop()
    return parts


def parse_range(value: str) -> tuple[int, int] | None:
    """Return (A, B) for two plain decimals with 1 <= A <= B, else None."""
    if not _RANGE.fullmatch(value):
        return None
    a_text, b_text = value.split(":")
    a, b = int(a_text), int(b_text)
    if a > b:
        return None
    return a, b


def classify_path(path: str) -> str | None:
    """Return the error cause for a path peek file cannot read, or None when it is a file."""
    try:
        mode = os.stat(path).st_mode
    except OSError as exc:
        if exc.errno == errno.EACCES:
            return "permission denied"
        return "no such file"
    except ValueError:
        return "no such file"
    if not stat.S_ISREG(mode):
        return "not a regular file"
    return None


@dataclass(frozen=True)
class Window:
    """A shown window: first line a, actual last line b, clipped flag, raw lines shown."""

    a: int
    b: int
    clipped: bool
    lines: list[str]


def file_window(lines: list[str], a: int, b: int) -> Window:
    """Select the window a..b (1 based) of lines, clamped, clipped and char budgeted."""
    n = len(lines)
    clamped = min(b, n)
    clipped = clamped - a + 1 > MAX_LINES
    last = a + MAX_LINES - 1 if clipped else clamped
    shown: list[str] = []
    cost = 0
    for index in range(a, last + 1):
        line = lines[index - 1]
        add = min(len(line), LINE_CAP)
        if cost + add > CHAR_BUDGET:
            break
        cost += add
        shown.append(line)
    return Window(a, a + len(shown) - 1, clipped, shown)
