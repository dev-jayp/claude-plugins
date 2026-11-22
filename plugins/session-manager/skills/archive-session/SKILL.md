---
name: archive-session
description: Use when the user wants to keep a Claude Code session but hide it from the /resume list, for example "archive this session", "stash that chat", "hide session <id> from resume", "I want to keep it but not see it in resume". Reversible via restore-session. Requires a session id (full UUID or unambiguous prefix).
---

# Archive Session

## Overview
Moves a session's transcript + sidecar into the project's `.archive/` folder. `/resume` does **not** scan subfolders, so an archived session stops appearing there while staying fully intact and reversible (see **restore-session**). Backed by the shared `session-manager` script. **Use this, not delete, when the user wants to keep a session.**

## Requires an id
The user must supply a session id (full UUID or unambiguous prefix). If not given, run **session-manager** first so they can pick one. Never guess.

## Safety rails (enforced by the script)
1. **Current session** → hard-blocked. You can't archive the window you're in.
2. **Open in another live window** → blocked (exit 4). The script reads `~/.claude/sessions/<pid>.json` (live process registry) to know this reliably. Tell the user to close that window first; only pass `--force` if they explicitly choose to override (`--yes` is also accepted here as a back-compat synonym). Archive is reversible, so there is no separate confirm flag; the override flag alone proceeds.

## How to run
```bash
python "${CLAUDE_SKILL_DIR}/../session-manager/scripts/sessions.py" archive <id>
```
Exit codes: `0` archived · `3` current (refuse) · `4` open elsewhere (advise closing) · `1` unknown/ambiguous id.

Archiving is a reversible move (not a delete), so no dry-run is needed, but still confirm the id/title in the output matches what the user meant. Report where it moved and that it's now hidden from `/resume`.

## Restoring
Tell the user they can bring it back anytime with **restore-session** (`restore <id>`).
