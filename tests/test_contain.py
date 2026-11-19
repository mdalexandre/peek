"""R9: containment. Nothing created but a capped run's spill; no network imports."""

from __future__ import annotations

import ast
import os
import subprocess
from pathlib import Path

from conftest import BIN, LAUNCHER, SRC, Peek, lines_cmd, make_scenarios, peek_dirs, snapshot

FORBIDDEN = {"socket", "urllib", "http", "requests"}


def scan_forbidden_imports(root: Path) -> list[tuple[str, str]]:
    """Static check: (file, module) for every import of a forbidden top level module."""
    found = []
    for py in sorted(root.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                mods = [node.module]
            found += [(str(py), m) for m in mods if m.split(".")[0] in FORBIDDEN]
    return found


def test_source_imports_none_of_socket_urllib_http_requests():
    """R9: the program source imports none of socket, urllib, http, requests."""
    assert list(SRC.rglob("peek/*.py")), "no peek source found"
    assert scan_forbidden_imports(SRC) == []


def test_import_scan_detects_planted_import_socket_and_from_http_client_and_requests(
    tmp_path: Path,
):
    """R9: the scanner flags planted imports, so a clean result means something."""
    d = tmp_path / "planted"
    d.mkdir()
    (d / "a.py").write_text("import socket\n")
    (d / "b.py").write_text("from http.client import HTTPConnection\n")
    (d / "c.py").write_text("import os, requests\n")
    (d / "d.py").write_text("import urllib.request\n")
    (d / "e.py").write_text("import os\nfrom pathlib import Path\n")
    hits = scan_forbidden_imports(d)
    assert sorted(Path(f).name for f, _ in hits) == ["a.py", "b.py", "c.py", "d.py"]


def _quiet(peek: Peek, args: list[str], cwd: Path, tmp: Path, data: Path):
    before = (snapshot(cwd), snapshot(tmp), snapshot(data))
    r = peek(*args)
    after = (snapshot(cwd), snapshot(tmp), snapshot(data))
    assert before == after
    return r


def test_peek_file_creates_nothing_in_cwd_or_tmpdir(peek: Peek, mk, cwd, isolated_tmp, data):
    """R9: peek file creates nothing."""
    f = mk("f.txt", "a\nb\n")
    r = _quiet(peek, ["file", str(f)], cwd, isolated_tmp, data)
    assert r.code == 0


def test_peek_file_error_creates_nothing(peek: Peek, cwd, isolated_tmp, data):
    """R9: a peek file error creates nothing."""
    r = _quiet(peek, ["file", str(data / "missing")], cwd, isolated_tmp, data)
    assert r.code == 2


def test_usage_error_creates_nothing(peek: Peek, cwd, isolated_tmp, data):
    """R9: a usage error creates nothing."""
    r = _quiet(peek, ["bogus"], cwd, isolated_tmp, data)
    assert r.code == 2


def test_uncapped_run_creates_nothing(peek: Peek, cwd, isolated_tmp, data):
    """R9: an uncapped run creates nothing."""
    r = _quiet(peek, ["run", "--", "echo", "hi"], cwd, isolated_tmp, data)
    assert r.code == 0


def test_command_not_found_creates_nothing(peek: Peek, cwd, isolated_tmp, data):
    """R9: command not found creates nothing."""
    r = _quiet(peek, ["run", "--", "peek-no-such-command-9f3a1c"], cwd, isolated_tmp, data)
    assert r.code == 127


def test_capped_run_creates_exactly_one_peek_directory_in_tmpdir_and_nothing_in_cwd(
    peek: Peek, cwd: Path, isolated_tmp: Path
):
    """R9: a capped run creates exactly one peek directory holding only out.txt."""
    peek("run", "--", *lines_cmd(100))
    dirs = peek_dirs(isolated_tmp)
    assert len(dirs) == 1
    assert snapshot(isolated_tmp) == [dirs[0].name, f"{dirs[0].name}/out.txt"]
    assert snapshot(cwd) == []


def test_stderr_is_empty_and_all_output_is_on_stdout_for_every_scenario(peek: Peek, data: Path):
    """R9: stderr stays empty and stdout carries the output for every scenario."""
    for name, args, _ in make_scenarios(data / "sc"):
        r = peek(*args)
        assert r.err == b"", name
        assert r.raw, name


def test_launcher_writes_no_pycache_into_the_source_tree(mk, cwd: Path, isolated_tmp: Path):
    """R9: the launcher leaves no __pycache__ even when the caller has bytecode on."""
    f = mk("f.txt", "a\n")
    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    env["TMPDIR"] = str(isolated_tmp)
    p = subprocess.run(
        [str(LAUNCHER), "file", str(f)],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        capture_output=True,
    )
    assert p.returncode == 0
    assert list(SRC.rglob("__pycache__")) == []
    assert list(BIN.rglob("__pycache__")) == []


def test_wrapped_command_stdin_is_dev_null(peek: Peek):
    """R9: the wrapped command's stdin is /dev/null."""
    code = "import os,sys; sys.stdout.write(os.readlink('/proc/self/fd/0'))"
    r = peek("run", "--", "python3", "-c", code)
    assert r.lines == ["exit 0, 1 lines, 9 bytes", "/dev/null", "done"]
    r2 = peek("run", "--", "cat")
    assert r2.lines == ["exit 0, 0 lines, 0 bytes", "no output: exit 0", "done"]


def test_wrapped_command_runs_in_the_callers_working_directory(peek: Peek, cwd: Path):
    """R9: the wrapped command runs in the caller's cwd."""
    r = peek("run", "--", "python3", "-c", "import os; print(os.getcwd())")
    assert r.lines[1] == str(cwd.resolve())


def test_args_after_double_dash_reach_the_command_unchanged(peek: Peek):
    """R9: every argument after -- reaches the command untouched."""
    code = "import sys; print(repr(sys.argv[1:]))"
    r = peek("run", "--", "python3", "-c", code, "--lines", "1:5", "-x", "a b", "", "--")
    assert r.lines[1] == repr(["--lines", "1:5", "-x", "a b", "", "--"])
