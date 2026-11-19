"""R3: the launcher exports PEEK_PROG as its own absolute path."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from conftest import LAUNCHER, Peek, numbered_text


def test_launcher_exports_peek_prog_equal_to_its_own_absolute_path(
    peek: Peek, mk, cwd: Path, isolated_tmp: Path
):
    """R3: next lines carry the launcher's absolute path, whatever PEEK_PROG came in."""
    f = mk("f.txt", numbered_text(250))
    expected = str(LAUNCHER.resolve())
    r = peek("file", str(f), env={"PEEK_PROG": "bogus"})
    assert r.last.split(" ")[1] == expected
    rel = os.path.relpath(LAUNCHER, cwd)
    p = subprocess.run(
        [rel, "file", str(f)],
        cwd=cwd,
        env={**os.environ, "TMPDIR": str(isolated_tmp), "PYTHONDONTWRITEBYTECODE": "1"},
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    assert p.stdout.decode().rstrip("\n").split("\n")[-1].split(" ")[1] == expected
