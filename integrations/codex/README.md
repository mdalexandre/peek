# peek for Codex CLI

Codex has no separate Read tool: it reads files with shell commands such as `sed -n` and `cat`. So the Codex integration is a rule plus an advisory reminder, never a blocking hook. A deny hook in Codex fires on ordinary shell work and can stall a session.

## 1. The rule

Add this as a section of `~/.codex/AGENTS.md`:

```markdown
## Reading files (peek)

Read every file to understand it with `peek file PATH [--lines A:B]` and follow its last line (`next:` run it; `end` or `done` stop). This replaces reading with `cat`, `head`, `tail`, `sed -n` or `nl`: do not use those to read a file, even a window of one. Before you edit a file, read the part you will change with peek, then apply the patch. When a command's output may be long, or its exit code matters, run it as `peek run -- CMD`.
```

Check that Codex loads it: `codex debug prompt-input "read a file"` should show the section once. Do not create `~/.codex/AGENTS.override.md`; it replaces `AGENTS.md` entirely.

## 2. The reminder hook

`hooks/peek_read_nudge.py` is a PostToolUse hook on `Bash`. When a command read a text file over 200 lines with `cat`, `head`, `tail`, `sed`, `nl`, `less`, `more`, `bat` or `awk` and did not use peek, it adds a reminder with the exact `peek file` command to Codex's context. It understands Codex's `/bin/bash -lc '...'` form and `cd DIR && ...` chains. It never denies or blocks, sends at most 5 reminders per session (state under `$XDG_STATE_HOME/peek-nudge/codex`), and stays silent on any error. `PEEK_NUDGE=0` turns it off; `PEEK_BIN` sets the launcher path.

```
mkdir -p ~/.codex/hooks && cp hooks/peek_read_nudge.py ~/.codex/hooks/
```

Then add a group to `~/.codex/hooks.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          { "type": "command", "command": "python3 ~/.codex/hooks/peek_read_nudge.py", "timeout": 5 }
        ]
      }
    ]
  }
}
```

A new hook runs only after you review and trust it in Codex with `/hooks`.

Tests: `python3 -m pytest hooks/tests`.
