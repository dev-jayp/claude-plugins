---
name: restore-session
description: Use when the user wants to bring an archived Claude Code session back so /resume shows it again, for example "restore session <id>", "unarchive that chat", "bring back the archived session", "un-stash it". Counterpart to archive-session. Requires a session id (full UUID or unambiguous prefix).
---

# Restore Session

## Overview
Moves an archived session (from the project's `.archive/` folder) back to the active set so `/resume` lists it again. Reverses **archive-session**. Backed by the shared `session-manager` script.

## Requires an id
The user must supply the archived session's id (full UUID or unambiguous prefix). To see what's archived, run **session-manager** with `list --show-archived`; archived sessions are tagged `A`. Never guess the id.

## How to run
```bash
python "${CLAUDE_SKILL_DIR}/../session-manager/scripts/sessions.py" restore <id>
```
Exit codes: `0` restored · `1` no archived session matches that id, or a same-named active session already exists (it won't overwrite). Report where it moved back to and that `/resume` will show it again.

## Notes
- Only resolves against **archived** sessions, so an id that's already active returns a clear "no archived session matches" error.
- It refuses to overwrite an existing active transcript of the same id.
