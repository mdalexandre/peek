<p align="center">
  <img src="assets/peek-logo.png" alt="Peek: tool for agentic systems" width="820">
</p>

# peek

**Bounded file windows and command runs for AI coding agents.**

An agent that runs `cat` on a 5,000 line file, or a test suite that prints 20,000 lines, spends its context window on text it never needed. peek puts a hard ceiling on every call: at most about 200 lines and 20,000 characters, always. Its last line tells the agent exactly what to run next, so it can still read everything, one bounded step at a time.

```
$ peek file src/app.py
lines 1 to 100 of 1602
...
next: peek file src/app.py --lines 101:200

$ peek run -- pytest -q
exit 1, 4210 lines, 389114 bytes
... first 30 lines ...
omitted 4160 lines of 4210
... last 20 lines ...
full output: /tmp/peek-a1b2c3/out.txt (389114 bytes)
next: peek file /tmp/peek-a1b2c3/out.txt --lines 31:130
```

## Why

- **Predictable size.** File windows are at most 100 lines and 16,000 characters, and any line over 400 characters is cut and tagged `[cut: N chars]`. Command output over 50 lines or 16,000 characters shows its first 30 and last 20 lines.
- **Nothing is lost.** Capped output is saved byte for byte to a private spill file (`0700` directory, `0600` file), and the `next:` line walks through it.
- **Machine-readable endings.** The last line is always `next: <command>`, `end: ...` or `done`. The `next:` command runs as printed.
- **Honest exit codes.** `peek run` exits with the wrapped command's code (128+n on a signal), so `&&` and `||` still work.
- **Safe edits.** `peek token` and `peek write` replace a line range only if the file has not changed since you read it (exit 3 otherwise).
- **No dependencies, no network.** Python 3.11+ standard library only.

## Install

```
pipx install git+https://github.com/mdalexandre/peek
```

or run it from a clone without installing:

```
git clone https://github.com/mdalexandre/peek && ./peek/bin/peek file README.md
```

## Usage

```
peek file PATH [--lines A:B]                          # a window of at most 100 lines
peek run -- CMD [ARGS...]                             # run, cap and spill long output
peek token PATH                                       # SHA-256 of the file right now
peek write PATH --lines A:B --token TOKEN --from SRC  # replace lines A to B
```

The grammar is strict on purpose: anything else, `--help` included, prints `error: usage`. An agent that only ever sees these exact forms has nothing to guess. Errors print `exit C, 0 lines, 0 bytes`, then one of seven causes on an `error:` line, then `done`. See [bin/USAGE.md](bin/USAGE.md) for the short reference to give an agent.

peek starts no shell and gives the command no stdin. For pipes and globs, wrap them: `peek run -- sh -c 'grep -n TODO *.py | head'`.

## Agent integrations

- [Claude Code](integrations/claude-code/README.md): a `peek` skill, a `CLAUDE.md` rule, and a PreToolUse hook that refuses an unbounded Read of a file over 200 lines and hands back the exact peek command instead.
- [Codex CLI](integrations/codex/README.md): an `AGENTS.md` rule and an advisory PostToolUse hook that reminds Codex to use peek when a shell command reads a file over 200 lines.

A short rule in the agent's instructions plus a hook makes a large difference: in our own sessions, peek was used for about 1% of shell calls when it was only mentioned in a long instruction file.

## Development

```
python3 -m pytest          # 365 tests, no network
ruff check src tests
```

## License

[MIT](LICENSE)
