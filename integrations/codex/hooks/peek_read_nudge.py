#!/usr/bin/env python3
"""Codex PostToolUse hook on Bash: advise peek after a shell read of a file over 200 lines.

Files are read with peek (https://github.com/mdalexandre/peek). Codex reads files through shell
commands (cat, head, tail, sed, nl, less, more, bat, awk), so this hook looks at the
command that just ran; when it read a regular text file of more than 200 lines and did
not use peek, it returns additionalContext with the exact peek command. Advisory only:
it never denies, blocks or stops (a deny hook in Codex blocks ordinary work). At most
5 nudges per session. Any fault exits 0 with no output.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import sys
from pathlib import Path
from typing import Any

LIMIT_LINES = 200
MAX_PER_SESSION = 5
READERS = frozenset({"cat", "head", "tail", "sed", "nl", "less", "more", "bat", "batcat", "awk"})
SPLIT = re.compile(r"&&|\|\||[;|&\n()]")
DEFAULT_STATE = (
    Path(os.environ.get("XDG_STATE_HOME") or Path.home() / ".local" / "state")
    / "peek-nudge"
    / "codex"
)


def _peek() -> str:
    return os.environ.get("PEEK_BIN") or shutil.which("peek") or "peek"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def _tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment)
    except ValueError:
        return segment.split()


def _commands(command: str) -> list[list[str]]:
    out: list[list[str]] = []
    for segment in SPLIT.split(command):
        toks = _tokens(segment)
        if (
            len(toks) >= 3
            and Path(toks[0]).name in {"bash", "sh", "zsh"}
            and toks[1].startswith("-")
        ):
            out.extend(_commands(toks[2]))
        elif toks:
            out.append(toks)
    return out


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


def long_file_read(command_parts: list[str], cwd: Path) -> str | None:
    """Return the first file over 200 lines that a reader command read, else None."""
    joined = "\n".join(command_parts)
    if re.search(r"(^|[/\s])peek\s", joined):
        return None
    if len(command_parts) > 1 and Path(command_parts[0]).name in {"bash", "sh", "zsh"}:
        joined = command_parts[-1]
    whole = _tokens(joined)
    while (
        len(whole) == 3
        and Path(whole[0]).name in {"bash", "sh", "zsh"}
        and whole[1].startswith("-")
    ):
        joined = whole[2]
        whole = _tokens(joined)
    base = cwd
    for toks in _commands(joined):
        if toks[0] == "cd" and len(toks) > 1:
            base = (base / toks[1]) if not toks[1].startswith("/") else Path(toks[1])
            continue
        if Path(toks[0]).name not in READERS:
            continue
        for tok in toks[1:]:
            if tok.startswith("-"):
                continue
            path = Path(tok) if tok.startswith("/") else base / tok
            if path.is_file() and _too_long(path):
                return tok if tok.startswith("/") else str(path)
    return None


def _take_slot(state_dir: Path, session_id: str) -> bool:
    state_dir.mkdir(parents=True, exist_ok=True)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id)[:120]
    state = state_dir / f"{safe}.json"
    count = 0
    if state.exists():
        loaded = json.loads(state.read_text(encoding="utf-8"))
        count = loaded if isinstance(loaded, int) else 0
    if count >= MAX_PER_SESSION:
        return False
    tmp = state.with_suffix(".tmp")
    tmp.write_text(json.dumps(count + 1), encoding="utf-8")
    os.replace(tmp, state)
    return True


def decide(payload: Any) -> dict[str, Any] | None:
    if not isinstance(payload, dict) or os.environ.get("PEEK_NUDGE") == "0":
        return None
    session_id = payload.get("session_id")
    tool_input = payload.get("tool_input")
    if not isinstance(session_id, str) or not session_id or not isinstance(tool_input, dict):
        return None
    parts = _strings(tool_input.get("command"))
    if not parts:
        return None
    cwd = Path(payload["cwd"]) if isinstance(payload.get("cwd"), str) else Path.cwd()
    found = long_file_read(parts, cwd)
    if found is None:
        return None
    state_dir = Path(os.environ.get("PEEK_NUDGE_STATE") or DEFAULT_STATE)
    if not _take_slot(state_dir, session_id):
        return None
    message = (
        f"Advisory, nothing was blocked: that command read a file of more than {LIMIT_LINES} lines "
        f"with a shell reader. Read files with peek, not cat, head, tail, sed -n or nl. "
        f"Next read: {_peek()} file {shlex.quote(found)} --lines 1:100 "
        f"and follow its last line (next: run it; end or done: stop)."
    )
    return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": message}}


def main() -> int:
    try:
        raw = sys.stdin.read()
        result = decide(json.loads(raw)) if raw.strip() else None
        if result is not None:
            sys.stdout.write(json.dumps(result))
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
