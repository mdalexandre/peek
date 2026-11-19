"""R8: peek run exits with the wrapped command's code, which is also C in line 1."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from conftest import SRC, Peek, lines_cmd, numbered_text


@pytest.mark.parametrize("c", [0, 1, 2, 3, 42, 126, 127, 255])
def test_peek_run_exit_code_equals_wrapped_code(peek: Peek, c):
    """R8: the exit code of peek run equals the wrapped command's code."""
    r = peek("run", "--", "sh", "-c", f"exit {c}")
    assert r.code == c


@pytest.mark.parametrize("c", [0, 1, 42, 255])
def test_peek_run_exit_code_equals_c_in_first_line(peek: Peek, c):
    """R8: the exit code equals the C in `exit C, L lines, S bytes`."""
    r = peek("run", "--", "sh", "-c", f"echo hi; exit {c}")
    m = re.match(r"^exit (\d+), 1 lines, 3 bytes$", r.first)
    assert m
    assert int(m.group(1)) == r.code == c


def test_signal_death_exit_code_equals_128_plus_n_and_header_c(peek: Peek):
    """R8: death by SIGTERM exits 143 and the header says 143."""
    r = peek("run", "--", "sh", "-c", "kill -TERM $$")
    assert r.code == 143
    assert r.first.startswith("exit 143, ")


def test_capped_run_exit_code_is_still_the_wrapped_code(peek: Peek):
    """R8: a capped run exits with the wrapped code."""
    r = peek("run", "--", *lines_cmd(100, tail="7"))
    assert r.code == 7
    assert r.first.startswith("exit 7, 100 lines, ")


def test_peek_file_success_exits_0(peek: Peek, mk):
    """R8: a successful peek file exits 0."""
    assert peek("file", str(mk("f.txt", numbered_text(3)))).code == 0


def test_peek_file_error_exits_2(peek: Peek, data: Path):
    """R8: a peek file error exits 2."""
    assert peek("file", str(data / "missing")).code == 2


def test_main_returns_int_and_package_main_exits_with_it(
    mk, capfd: pytest.CaptureFixture[str], cwd: Path, isolated_tmp: Path
):
    """R8: main returns an int and python -m peek exits with it."""
    from peek.cli import main

    f = mk("f.txt", numbered_text(3))
    rc = main(["file", str(f)])
    assert isinstance(rc, int) and rc == 0
    assert capfd.readouterr().out.startswith("lines 1 to 3 of 3\n")
    assert main(["bogus"]) == 2
    p = subprocess.run(
        ["python3", "-X", "utf8", "-P", "-m", "peek", "run", "--", "sh", "-c", "exit 5"],
        cwd=cwd,
        env={
            "PATH": "/usr/bin:/bin",
            "PYTHONPATH": str(SRC),
            "TMPDIR": str(isolated_tmp),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    assert p.returncode == 5
    assert p.stdout.decode().startswith("exit 5, 0 lines, 0 bytes\n")
