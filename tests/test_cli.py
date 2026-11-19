"""R10: the grammar, usage errors, first line and terminal line."""

from __future__ import annotations

import dataclasses
import inspect
import tomllib
from importlib import import_module
from pathlib import Path

import pytest
from conftest import (
    FIRST_LINE,
    LAUNCHER,
    SRC,
    TERMINAL,
    TOOL,
    Peek,
    lines_cmd,
    make_scenarios,
    numbered_text,
)

USAGE = ["exit 2, 0 lines, 0 bytes", "error: usage", "done"]


def leaves(obj) -> list:
    """Every scalar inside a parse result, whatever its field names are."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return leaves([getattr(obj, f.name) for f in dataclasses.fields(obj)])
    if isinstance(obj, list | tuple):
        return [x for y in obj for x in leaves(y)]
    if hasattr(obj, "__dict__"):
        return leaves(list(vars(obj).values()))
    return [obj]


def parse(argv: list[str]):
    from peek.cli import parse_args

    try:
        return parse_args(argv)
    except Exception as e:  # a raised UsageError is an allowed way to report usage
        return e


def test_parse_args_accepts_file_path_alone():
    """R10: `file PATH` parses as a FileCall."""
    call = parse(["file", "x.txt"])
    assert type(call).__name__ == "FileCall"
    assert "x.txt" in leaves(call)


def test_parse_args_accepts_file_path_with_lines():
    """R10: `file PATH --lines 1:5` parses as a FileCall with the range."""
    call = parse(["file", "x.txt", "--lines", "1:5"])
    assert type(call).__name__ == "FileCall"
    lv = leaves(call)
    assert "x.txt" in lv
    assert "1:5" in lv or (1 in lv and 5 in lv)


def test_parse_args_accepts_run_double_dash_command_and_args():
    """R10: `run -- CMD ARGS` parses as a RunCall."""
    call = parse(["run", "--", "echo", "hi", "--lines"])
    assert type(call).__name__ == "RunCall"
    lv = leaves(call)
    assert "echo" in lv and "hi" in lv and "--lines" in lv


USAGE_CASES = {
    "no_args": [],
    "file": ["file"],
    "run": ["run"],
    "run_dd": ["run", "--"],
    "run_no_dd": ["run", "echo"],
    "file_two_paths": ["file", "a", "b"],
    "file_lines_no_value": ["file", "a", "--lines"],
    "lines_before_file": ["--lines", "1:2", "file", "a"],
    "file_unknown_option": ["file", "a", "--foo"],
    "file_short_option": ["file", "a", "-n", "5"],
    "file_lines_equals_form": ["file", "a", "--lines=1:2"],
    "file_lines_before_path": ["file", "--lines", "1:2", "a"],
    "file_dd": ["file", "--", "a"],
    "file_trailing_dd": ["file", "a", "--"],
    "run_option_before_dd": ["run", "-x", "--", "echo"],
    "run_lines_before_dd": ["run", "--lines", "1:2", "--", "echo"],
    "bogus_command": ["bogus"],
    "uppercase_FILE": ["FILE", "a"],
    "help": ["help"],
    "dash_dash_help": ["--help"],
    "version": ["--version"],
}


@pytest.mark.parametrize("args", list(USAGE_CASES.values()), ids=list(USAGE_CASES))
def test_usage_error_output_is_exactly_exit_2_error_usage_done(peek: Peek, args):
    """R10: every call outside the two grammars prints the usage error and exits 2."""
    r = peek(*args)
    assert r.code == 2
    assert r.lines == USAGE
    assert r.err == b""


def test_repeated_lines_is_usage_even_with_identical_values(peek: Peek, mk):
    """R10: a repeated --lines is usage even when both values are equal."""
    f = mk("f.txt", numbered_text(5))
    r = peek("file", str(f), "--lines", "1:2", "--lines", "1:2")
    assert r.code == 2 and r.lines == USAGE


def test_repeated_lines_is_usage_even_when_second_value_is_bad(peek: Peek, mk):
    """R10: a repeated --lines is usage, not bad range, when the second value is bad."""
    f = mk("f.txt", numbered_text(5))
    r = peek("file", str(f), "--lines", "1:2", "--lines", "x")
    assert r.code == 2 and r.lines == USAGE


PYARGS = "import sys; print(' '.join(sys.argv[1:]))"


def test_lines_after_double_dash_is_passed_to_the_command_not_parsed(peek: Peek):
    """R10: --lines after -- belongs to the command."""
    r = peek("run", "--", "python3", "-c", PYARGS, "--lines", "1:2")
    assert r.lines == ["exit 0, 1 lines, 12 bytes", "--lines 1:2", "done"]


def test_option_after_double_dash_is_not_parsed(peek: Peek):
    """R10: other options after -- belong to the command."""
    r = peek("run", "--", "python3", "-c", PYARGS, "-x", "--foo", "--help")
    assert r.lines[1] == "-x --foo --help"
    assert r.code == 0


def test_file_with_empty_path_is_no_such_file_not_usage(peek: Peek):
    """R10: an empty PATH is no such file, not usage."""
    r = peek("file", "")
    assert r.lines == ["exit 2, 0 lines, 0 bytes", "error: no such file", "done"]


def test_first_line_matches_one_of_the_two_grammars_for_every_scenario(peek: Peek, data: Path):
    """R10: line 1 is `lines A to B of N` or `exit C, L lines, S bytes`."""
    for name, args, _ in make_scenarios(data / "sc"):
        r = peek(*args)
        assert FIRST_LINE.match(r.first), (name, r.first)


def test_file_error_first_line_is_exit_2_0_lines_0_bytes(peek: Peek, data: Path):
    """R10: peek file errors start with `exit 2, 0 lines, 0 bytes`."""
    for name, args, _ in make_scenarios(data / "sc"):
        if name in {"file_missing", "file_dir", "file_bad_range", "file_past_end"}:
            assert peek(*args).first == "exit 2, 0 lines, 0 bytes", name


def test_terminal_line_is_exactly_one_of_next_end_done_for_every_scenario(peek: Peek, data: Path):
    """R10: the last line is next, end or done, matching the scenario."""
    for name, args, kind in make_scenarios(data / "sc"):
        r = peek(*args)
        assert TERMINAL[kind].match(r.last), (name, r.last)
        others = [k for k in TERMINAL if k != kind]
        assert not any(TERMINAL[k].match(r.last) for k in others), name


def test_body_lines_starting_with_done_next_or_end_do_not_change_the_final_line(peek: Peek, mk):
    """R10: body lines named done, next:, end: leave the real final line alone."""
    code = "print('done'); print('next: foo'); print('end: lines 1 to 1 of 1')"
    r = peek("run", "--", "python3", "-c", code)
    assert r.lines[1:4] == ["done", "next: foo", "end: lines 1 to 1 of 1"]
    assert r.last == "done" and len(r.lines) == 5
    f = mk("f.txt", "done\nnext: foo\nend: x\n")
    r2 = peek("file", str(f))
    assert r2.lines == [
        "lines 1 to 3 of 3",
        "done",
        "next: foo",
        "end: x",
        "end: lines 1 to 3 of 3",
    ]
    g = mk("g.txt", "done\n" * 250)
    r3 = peek("file", str(g))
    assert r3.last.startswith("next: ") and " file " in r3.last


def test_next_and_end_are_never_both_printed(peek: Peek, data: Path):
    """R10: no scenario prints both a next line and an end line."""
    for name, args, _ in make_scenarios(data / "sc"):
        r = peek(*args)
        nexts = [x for x in r.lines if x.startswith("next: ")]
        ends = [x for x in r.lines if x.startswith("end: ")]
        assert not (nexts and ends), name
        assert len(nexts) + len(ends) <= 1, name


def test_output_ends_with_exactly_one_newline_and_no_blank_final_line(peek: Peek, data: Path):
    """R10: stdout ends with one newline after a non blank last line."""
    for name, args, _ in make_scenarios(data / "sc"):
        t = peek(*args).text
        assert t.endswith("\n") and not t.endswith("\n\n"), name


def test_main_takes_argv_and_returns_int(mk, capfd: pytest.CaptureFixture[str]):
    """R10: main(argv) returns an int and its argv defaults to None."""
    from peek.cli import main

    assert inspect.signature(main).parameters["argv"].default is None
    f = mk("f.txt", numbered_text(3))
    rc = main(["file", str(f), "--lines", "1:2"])
    out = capfd.readouterr().out
    assert isinstance(rc, int) and rc == 0
    assert out.startswith("lines 1 to 2 of 3\n")
    assert main(["file"]) == 2
    assert capfd.readouterr().out == "\n".join(USAGE) + "\n"


def test_pyproject_declares_peek_equals_peek_cli_main_and_it_resolves():
    """R10: pyproject maps peek to peek.cli:main and that callable exists."""
    meta = tomllib.loads((TOOL / "pyproject.toml").read_text())
    target = meta["project"]["scripts"]["peek"]
    assert target == "peek.cli:main"
    mod, func = target.split(":")
    assert callable(getattr(import_module(mod), func))
    assert meta["project"].get("dependencies", []) == []


def test_launcher_without_arguments_prints_usage_and_exits_2(peek: Peek):
    """R10: bin/peek with no arguments prints the usage error and exits 2."""
    r = peek()
    assert r.code == 2
    assert r.lines == USAGE


def test_python_dash_m_peek_matches_launcher_output(peek: Peek, peek_direct: Peek, mk):
    """R10: python -m peek prints what the launcher prints."""
    f = mk("f.txt", numbered_text(250))
    env = {"PEEK_PROG": str(LAUNCHER.resolve())}
    assert peek_direct("file", str(f), env=env).raw == peek("file", str(f)).raw
    assert peek_direct("bogus").raw == peek("bogus").raw
    argv = ["run", "--", *lines_cmd(100)]
    a, b = peek_direct(*argv, env=env), peek(*argv)
    assert a.code == b.code == 0
    assert a.lines[:32] == b.lines[:32]
    assert SRC.is_dir()
