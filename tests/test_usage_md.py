"""R11: USAGE.md beside the launcher."""

from __future__ import annotations

import os
import subprocess

import pytest
from conftest import BIN, LAUNCHER, PUBLIC_LAUNCHER

SENTENCE = "For a file over 200 lines, use peek file instead of Read."


def check_usage(text: str) -> list[str]:
    """The R11 checker: a list of failures, empty when the text passes."""
    out = []
    if len(text.splitlines()) > 30:
        out.append("longer than 30 lines")
    for need in ("peek file", "peek run", SENTENCE):
        if need not in text:
            out.append(f"missing {need}")
    return out


GOOD = f"# peek\n\npeek file PATH\npeek run -- CMD\n\n{SENTENCE}\n"


def read() -> str:
    return (BIN / "USAGE.md").read_text(encoding="utf-8")


def test_usage_md_exists_beside_the_launcher_in_bin():
    """R11: USAGE.md is a file in bin/, beside bin/peek."""
    assert LAUNCHER.is_file()
    assert (BIN / "USAGE.md").is_file()
    assert (BIN / "USAGE.md").parent == LAUNCHER.parent


def test_usage_md_has_at_most_30_lines():
    """R11: USAGE.md has at most 30 lines."""
    assert len(read().splitlines()) <= 30


def test_usage_md_contains_peek_file_and_peek_run():
    """R11: USAGE.md contains `peek file` and `peek run`."""
    t = read()
    assert "peek file" in t and "peek run" in t


def test_usage_md_contains_the_exact_200_line_sentence():
    """R11: USAGE.md contains the exact 200 line sentence."""
    assert SENTENCE in read()


def test_checker_rejects_a_31_line_usage_text():
    """R11: the checker passes a good text and rejects 31 lines."""
    assert check_usage(GOOD) == []
    assert check_usage(GOOD + "x\n" * 30) != []
    assert check_usage("\n".join(["peek file peek run " + SENTENCE] + ["x"] * 30)) != []


def test_checker_rejects_text_missing_peek_run():
    """R11: the checker rejects a text without `peek run`."""
    assert check_usage(GOOD.replace("peek run", "peek go")) != []


def test_checker_rejects_text_with_the_sentence_altered_by_one_word():
    """R11: the checker rejects the sentence with one word changed."""
    assert check_usage(GOOD.replace("instead of Read", "instead of Open")) != []
    assert check_usage(GOOD.replace("over 200", "over 300")) != []


def test_usage_md_shows_both_command_forms():
    """R11: USAGE.md shows the file and run forms as they are typed."""
    t = read()
    assert "peek file " in t
    assert "peek run -- " in t


def test_public_launcher_runs_and_prints_itself_in_the_next_line(tmp_path):
    """The installed public launcher pages long output and names itself in next:."""
    if not PUBLIC_LAUNCHER.exists():
        pytest.skip("public launcher not installed")
    env = {**os.environ, "TMPDIR": str(tmp_path)}
    r = subprocess.run(
        [str(PUBLIC_LAUNCHER), "run", "--", "seq", "300"],
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert r.returncode == 0, r.stderr
    last = r.stdout.rstrip("\n").splitlines()[-1]
    assert last.startswith(f"next: {PUBLIC_LAUNCHER}")
