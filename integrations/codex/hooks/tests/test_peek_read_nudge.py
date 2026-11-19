"""Tests for peek_read_nudge.py (Codex PostToolUse on Bash, advisory only)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HOOK = Path(__file__).resolve().parent.parent / "peek_read_nudge.py"


def _file(tmp_path: Path, lines: int, name: str = "big.py") -> Path:
    p = tmp_path / name
    p.write_text("".join(f"x = {i}\n" for i in range(lines)), encoding="utf-8")
    return p


def _run(payload: Any, state: Path) -> tuple[int, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    env = {"PATH": "/usr/bin:/bin", "PEEK_NUDGE_STATE": str(state)}
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
        env=env,
    )
    return r.returncode, r.stdout


def _payload(command: Any, cwd: Path, session: str = "s1") -> dict[str, Any]:
    return {
        "session_id": session,
        "cwd": str(cwd),
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "tool_response": "...",
    }


@pytest.mark.parametrize("verb", ["sed -n '1,200p'", "cat", "head -n 400", "tail -n 50", "nl -ba"])
def test_shell_read_of_a_file_over_200_lines_gets_advisory_peek_command(
    tmp_path: Path, verb: str
) -> None:
    p = _file(tmp_path, 300)
    code, out = _run(_payload(f"{verb} {p}", tmp_path), tmp_path / "st")
    assert code == 0
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PostToolUse"
    assert set(spec) == {"hookEventName", "additionalContext"}
    assert f"peek file {p} --lines 1:100" in spec["additionalContext"]


def test_relative_path_resolves_against_cwd(tmp_path: Path) -> None:
    _file(tmp_path, 300, "rel.py")
    _, out = _run(_payload("sed -n '1,80p' rel.py", tmp_path), tmp_path / "st")
    assert "peek file" in json.loads(out)["hookSpecificOutput"]["additionalContext"]


def test_bash_lc_wrapper_and_list_command_are_parsed(tmp_path: Path) -> None:
    p = _file(tmp_path, 300)
    _, out1 = _run(_payload(["bash", "-lc", f"cat {p}"], tmp_path), tmp_path / "a")
    _, out2 = _run(
        _payload(f"bash -lc 'cd {tmp_path} && sed -n 1,50p big.py'", tmp_path), tmp_path / "b"
    )
    assert "peek file" in out1 and "peek file" in out2


def test_file_of_200_lines_is_silent(tmp_path: Path) -> None:
    p = _file(tmp_path, 200)
    assert _run(_payload(f"cat {p}", tmp_path), tmp_path / "st") == (0, "")


def test_command_already_using_peek_is_silent(tmp_path: Path) -> None:
    p = _file(tmp_path, 300)
    cmd = f"peek file {p} --lines 1:100"
    assert _run(_payload(cmd, tmp_path), tmp_path / "st") == (0, "")


def test_non_reader_command_on_big_file_is_silent(tmp_path: Path) -> None:
    p = _file(tmp_path, 300)
    assert _run(_payload(f"python3 {p}", tmp_path), tmp_path / "st") == (0, "")
    assert _run(_payload(f"wc -l {p}", tmp_path), tmp_path / "st") == (0, "")


def test_binary_file_is_silent(tmp_path: Path) -> None:
    p = tmp_path / "b.bin"
    p.write_bytes(b"\x00\n" * 900)
    assert _run(_payload(f"cat {p}", tmp_path), tmp_path / "st") == (0, "")


def test_at_most_five_nudges_per_session(tmp_path: Path) -> None:
    p = _file(tmp_path, 300)
    outs = [_run(_payload(f"cat {p}", tmp_path), tmp_path / "st")[1] for _ in range(7)]
    assert sum(1 for o in outs if o) == 5
    assert _run(_payload(f"cat {p}", tmp_path, session="s2"), tmp_path / "st")[1] != ""


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "not json",
        "[]",
        {"tool_name": "Bash"},
        {"session_id": "s", "tool_name": "Bash", "tool_input": {"command": 7}},
    ],
)
def test_faults_exit_0_silent(tmp_path: Path, payload: Any) -> None:
    assert _run(payload, tmp_path / "st") == (0, "")


def test_output_never_carries_a_blocking_field(tmp_path: Path) -> None:
    p = _file(tmp_path, 300)
    _, out = _run(_payload(f"cat {p}", tmp_path), tmp_path / "st")
    for word in ("permissionDecision", "decision", "continue", "stopReason", "updatedInput"):
        assert word not in json.loads(out) and word not in json.loads(out)["hookSpecificOutput"]
