# peek for Claude Code

Three pieces, each optional. Use all three for the strongest effect: the rule says what to do, the skill says how, and the hook catches the case the rule misses.

## 1. The rule

Add this to `~/.claude/CLAUDE.md` (or a project `CLAUDE.md`):

```markdown
- Reading files: read every file to understand it with `peek file PATH [--lines A:B]` and follow its last line (`next:` run it; `end` or `done` stop). This overrides any advice to read with the Read tool or with cat, head, tail or sed -n. Use Read only on a file you are about to Edit, with offset and a `limit` of at most 200 lines. When a command's output may be long, or its exit code matters, run it as `peek run -- CMD`.
```

Keep it short and unconditional. A rule like "for a file over 200 lines, use peek" fails in practice, because the agent does not know a file's length before it reads it.

## 2. The skill

```
mkdir -p ~/.claude/skills && cp -r skills/peek ~/.claude/skills/
```

It teaches paging, capped runs, spill files, pipelines, exit codes and safe line range edits.

## 3. The Read gate hook

`hooks/peek_read_gate.py` is a PreToolUse hook on `Read`. It refuses an unbounded Read of a text file over 200 lines and returns the exact `peek file PATH --lines 1:100` command in the refusal. It lets through a Read with a `limit` of at most 200 (Edit needs a prior Read), files of 200 lines or fewer, images, PDFs, notebooks and binary files. On any error it stays silent and the Read proceeds. `PEEK_READ_GATE=off` turns it off; `PEEK_BIN` sets the launcher path, else `peek` is taken from `PATH`.

```
mkdir -p ~/.claude/hooks && cp hooks/peek_read_gate.py ~/.claude/hooks/
```

Then add to `~/.claude/settings.json`:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Read",
        "hooks": [
          { "type": "command", "command": "python3 ~/.claude/hooks/peek_read_gate.py", "timeout": 5 }
        ]
      }
    ]
  }
}
```

Tests: `python3 -m pytest hooks/tests`.
