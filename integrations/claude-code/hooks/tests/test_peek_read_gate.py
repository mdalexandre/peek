"""Tests for peek_read_gate.py (PreToolUse on Read)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

HOOK = Path(__file__).resolve().parent.parent / "peek_read_gate.py"
sys.path.insert(0, str(HOOK.parent))
import peek_read_gate as gate  # noqa: E402


def _file(tmp_path: Path, lines: int, name: str = "f.txt") -> Path:
    p = tmp_path / name
    p.write_text("".join(f"line {i}\n" for i in range(lines)), encoding="utf-8")
    return p


def _payload(path: Path | str, **extra: Any) -> dict[str, Any]:
    return {"tool_name": "Read", "tool_input": {"file_path": str(path), **extra}}


def _run(payload: Any) -> tuple[int, str]:
    raw = payload if isinstance(payload, str) else json.dumps(payload)
    r = subprocess.run(
        [sys.executable, "-X", "utf8", str(HOOK)],
        input=raw,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return r.returncode, r.stdout


def test_unbounded_read_of_201_line_file_is_denied_with_peek_command(tmp_path: Path) -> None:
    p = _file(tmp_path, 201)
    code, out = _run(_payload(p))
    assert code == 0
    spec = json.loads(out)["hookSpecificOutput"]
    assert spec["hookEventName"] == "PreToolUse"
    assert spec["permissionDecision"] == "deny"
    assert f"peek file {p} --lines 1:100" in spec["permissionDecisionReason"]


def test_unbounded_read_of_200_line_file_passes(tmp_path: Path) -> None:
    assert _run(_payload(_file(tmp_path, 200))) == (0, "")


def test_read_with_limit_200_passes(tmp_path: Path) -> None:
    assert _run(_payload(_file(tmp_path, 5000), offset=100, limit=200)) == (0, "")


def test_read_with_limit_201_is_denied(tmp_path: Path) -> None:
    _, out = _run(_payload(_file(tmp_path, 5000), limit=201))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_offset_without_limit_is_denied(tmp_path: Path) -> None:
    _, out = _run(_payload(_file(tmp_path, 500), offset=10))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


@pytest.mark.parametrize("ext", [".png", ".jpg", ".pdf", ".ipynb", ".webp"])
def test_media_pdf_and_notebooks_pass(tmp_path: Path, ext: str) -> None:
    assert _run(_payload(_file(tmp_path, 900, "x" + ext))) == (0, "")


def test_binary_file_with_nul_passes(tmp_path: Path) -> None:
    p = tmp_path / "b.bin"
    p.write_bytes(b"\x00\n" * 900)
    assert _run(_payload(p)) == (0, "")


@pytest.mark.parametrize(
    "payload",
    [
        "not json",
        "",
        "[]",
        {"tool_name": "Bash", "tool_input": {"command": "cat x"}},
        {"tool_name": "Read", "tool_input": "x"},
        {"tool_name": "Read", "tool_input": {"file_path": 7}},
        {"tool_name": "Read", "tool_input": {"file_path": "/no/such/file"}},
        {"tool_name": "Read", "tool_input": {"file_path": "/tmp"}},
    ],
)
def test_faults_and_other_tools_exit_0_silent(payload: Any) -> None:
    assert _run(payload) == (0, "")


def test_non_integer_limit_is_treated_as_unbounded(tmp_path: Path) -> None:
    _, out = _run(_payload(_file(tmp_path, 500), limit="50"))
    assert json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"


def test_path_with_space_is_shell_quoted(tmp_path: Path) -> None:
    p = _file(tmp_path, 300, "a b.txt")
    _, out = _run(_payload(p))
    assert (
        f"peek file '{p}' --lines 1:100"
        in json.loads(out)["hookSpecificOutput"]["permissionDecisionReason"]
    )


def test_env_switch_off_disables_gate(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PEEK_READ_GATE", "off")
    assert gate.decide(_payload(_file(tmp_path, 900))) is None


def test_reason_mentions_bounded_read_escape_for_edit(tmp_path: Path) -> None:
    out = gate.decide(_payload(_file(tmp_path, 900)))
    assert out is not None
    assert "limit of at most 200" in out["hookSpecificOutput"]["permissionDecisionReason"]
