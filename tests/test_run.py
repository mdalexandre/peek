"""R5: a command that ran and printed nothing."""

from __future__ import annotations

import pytest
from conftest import Peek


def zero(c: int) -> list[str]:
    return [f"exit {c}, 0 lines, 0 bytes", f"no output: exit {c}", "done"]


def test_zero_output_exit_0_prints_exactly_header_no_output_done(peek: Peek):
    """R5: a silent exit 0 prints exactly three lines."""
    r = peek("run", "--", "true")
    assert r.code == 0
    assert r.lines == zero(0)


def test_zero_output_exit_3_prints_no_output_exit_3(peek: Peek):
    """R5: a silent exit 3 prints `no output: exit 3`."""
    r = peek("run", "--", "sh", "-c", "exit 3")
    assert r.code == 3
    assert r.lines == zero(3)


def test_zero_output_wrapped_exit_127_is_no_output_not_command_not_found(peek: Peek):
    """R5: a wrapped command that itself exits 127 is a normal silent run."""
    r = peek("run", "--", "sh", "-c", "exit 127")
    assert r.code == 127
    assert r.lines == zero(127)


def test_zero_output_signal_death_prints_no_output_exit_137(peek: Peek):
    """R5: a silent death by SIGKILL prints exit 137 lines."""
    r = peek("run", "--", "sh", "-c", "kill -KILL $$")
    assert r.code == 137
    assert r.lines == zero(137)


def test_single_newline_output_is_one_empty_line_not_empty_output(peek: Peek):
    """R5: output of one newline is one empty line, not empty output."""
    r = peek("run", "--", "printf", "\\n")
    assert r.code == 0
    assert r.lines == ["exit 0, 1 lines, 1 bytes", "", "done"]


@pytest.mark.parametrize("c", [0, 1, 255])
def test_zero_output_any_code_shape(peek: Peek, c):
    """R5: the three line shape holds for any exit code."""
    r = peek("run", "--", "sh", "-c", f"exit {c}")
    assert r.lines == zero(c)
