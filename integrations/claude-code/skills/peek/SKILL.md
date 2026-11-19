---
name: peek
description: Read files and run commands through peek, so no single result floods the context. Use to read any file, page through a large file, run a command whose output may be long, read or verify its full output, branch on its exit code, run a pipeline, or replace a line range safely.
---

# peek

peek has four commands. Every call prints at most about 200 lines, and its last line tells you what to do next.

```
peek file PATH [--lines A:B]     # a window of at most 100 lines (default 1:100)
peek run -- CMD [ARGS...]        # run a command; long output is capped and spilled
peek token PATH                  # SHA-256 of the file now, for a safe write
peek write PATH --lines A:B --token TOKEN --from SRC
```

The last line is always one of:

- `next: <command>`: run it exactly as printed to continue.
- `end: ...`: the file window reached the last line.
- `done`: nothing more to read.

## Read a file

1. `peek file PATH`. The first line is `lines A to B of N`, so you learn the length on the first call.
2. To read the whole file in order, run each `next:` line until the last line starts with `end`.
3. To jump, use `--lines A:B` (at most 100 lines; a larger range is clipped and says so).
4. Lines over 400 characters are cut and tagged `[cut: N chars]`. For an exact copy of such a line, read the file with a tool that does not cut, or hash it.

## Run a command

1. `peek run -- CMD ARGS`. peek exits with the command's own exit code, and the first line is `exit C, L lines, B bytes`.
2. Output over 50 lines or 16,000 characters is capped: the first 30 and last 20 lines are shown, the middle is counted in `omitted M lines of L`, and everything is saved to a spill file named in the `full output: SPILL (S bytes)` line.
3. Lines 1 to 30 exist only in the display; read lines 31 on from the spill with the printed `next:` line, or search the spill directly with `grep` or `wc`.
4. To prove the spill is complete, compare `sha256sum SPILL` with the hash of the raw output, or its size with S.
5. The command gets no stdin, and peek starts no shell.

## Pipelines and conditions

- peek starts no shell. Wrap a pipe, glob or redirect: `peek run -- sh -c 'grep -n foo *.py | head -50'`. The exit code is then the shell's, which is the last stage's unless you `set -o pipefail` in a shell that supports it.
- Use the peek call itself as the condition: `peek run -- make test && echo ok`. Never put a pipe or a trailing command after the peek call that decides the branch, or you lose its exit code.

## Replace a line range

1. `peek token PATH` and keep the hex after `token:`.
2. `peek file PATH --lines A:B` to see the current lines.
3. Put the new lines in a file, or pass them on stdin with a quoted heredoc:
   `peek write PATH --lines A:B --token TOKEN --from /dev/stdin <<'EOF'`
4. The readback shows the new window, `replaced lines A to B with K lines` and a new `token:` for the next write.
5. Exit 3 (`error: stale token`) means the file changed since the token: nothing was written. Take a new token, reread, recompute A:B, and write again. Never reuse an old token.

## Errors

A failure prints `exit C, 0 lines, 0 bytes`, then `error: <cause>`, then `done`. The causes are: no such file, not a regular file, permission denied, bad range, range past end of file (N lines), usage, command not found. Only the exact forms above are accepted; anything else is `error: usage`.
