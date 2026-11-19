"""Run a wrapped command: stdin /dev/null, stdout and stderr merged in arrival order."""

from __future__ import annotations

import errno
import subprocess
from dataclasses import dataclass

NOT_FOUND = "command not found"
NOT_EXECUTABLE = "permission denied"


@dataclass(frozen=True)
class RunResult:
    """Outcome of one wrapped command. exec_error is set when it never ran."""

    code: int
    raw: bytes
    exec_error: str | None = None


def run_command(argv: list[str]) -> RunResult:
    """Run argv in the current directory and return its exit code and merged raw output."""
    if not argv[0]:
        return RunResult(127, b"", NOT_FOUND)
    try:
        proc = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
    except OSError as exc:
        if exc.errno in (errno.ENOENT, errno.ENOTDIR, errno.ENAMETOOLONG):
            return RunResult(127, b"", NOT_FOUND)
        return RunResult(126, b"", NOT_EXECUTABLE)
    except ValueError:
        return RunResult(127, b"", NOT_FOUND)
    raw, _ = proc.communicate()
    code = proc.returncode
    if code < 0:
        code = 128 + (-code)
    return RunResult(code, raw)
