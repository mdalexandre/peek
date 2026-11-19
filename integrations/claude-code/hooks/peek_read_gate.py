#!/usr/bin/env python3
"""PreToolUse hook on Read: refuse an unbounded Read of a text file over 200 lines.

Files are read with peek (https://github.com/mdalexandre/peek). A Read passes when it sets
`limit` to at most 200 lines (the bounded read Edit needs), when the file has
200 lines or fewer, or when the file is media, PDF, a notebook or binary. A
refusal names the exact peek command to run instead. Any fault exits 0 with no
output, so the hook never blocks a Read it cannot judge. PEEK_READ_GATE=off
disables it.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

LIMIT_LINES = 200
SKIP_SUFFIXES = frozenset(
    {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".ico", ".pdf", ".ipynb"}
)


def _peek() -> str:
    return os.environ.get("PEEK_BIN") or shutil.which("peek") or "peek"


def _bounded(tool_input: dict[str, Any]) -> bool:
    limit = tool_input.get("limit")
    return isinstance(limit, int) and not isinstance(limit, bool) and 0 < limit <= LIMIT_LINES


def _too_long(path: Path) -> bool:
    with path.open("rb") as handle:
        if b"\x00" in handle.read(8192):
            return False
        handle.seek(0)
        count = 0
        last = b""
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            count += chunk.count(b"\n")
            last = chunk
            if count > LIMIT_LINES:
                return True
        if last and not last.endswith(b"\n"):
            count += 1
    return count > LIMIT_LINES


def decide(payload: Any) -> dict[str, Any] | None:
    if os.environ.get("PEEK_READ_GATE", "").strip().casefold() == "off":
        return None
    if not isinstance(payload, dict) or payload.get("tool_name") != "Read":
        return None
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict) or _bounded(tool_input):
        return None
    file_path = tool_input.get("file_path")
    if not isinstance(file_path, str) or not file_path:
        return None
    path = Path(file_path)
    if path.suffix.casefold() in SKIP_SUFFIXES or not path.is_file():
        return None
    if not _too_long(path):
        return None
    command = f"{_peek()} file {shlex.quote(file_path)} --lines 1:100"
    reason = (
        f"This file has more than {LIMIT_LINES} lines; read it with peek, not an unbounded Read "
        f"(the peek reading rule). Run: {command} and follow its last line (next: run it; "
        f"end or done: stop). If you are about to Edit this file, Read it with offset and a "
        f"limit of at most {LIMIT_LINES} lines around the part you will change."
    )
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def main() -> int:
    try:
        result = decide(json.loads(sys.stdin.read()))
    except Exception:
        return 0
    if result is not None:
        sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
