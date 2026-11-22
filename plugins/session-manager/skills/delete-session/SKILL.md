---
name: delete-session
description: Use when the user wants to delete, remove, purge, or clean up a specific Claude Code session/chat by id. Triggers include "delete session <id>", "remove this chat", "purge that session", "clean up the temp session". Requires a session id (full UUID or unambiguous prefix).
---

# Delete Session

## Overview
Permanently deletes one Claude Code session: its transcript (`<id>.jsonl`), sidecar dir (`<id>/`), scratchpad, and, when present, its handoff folder (`~/.claude/handoffs/<id>/`) and turn-stamp file (`~/.claude/tmp/turnstart-<id>.txt`) written by the compaction-handoff and toast hooks, after enforcing safety rails. **Deleting the handoff folder also removes `handoffs/<id>/stamps.tsv`, which `/timeline` needs, so run `/timeline` for that session first if its time log is still wanted.** Backed by the shared `session-manager` script. **Deletion is irreversible: there is no recycle bin and no `/resume` afterward.**

## Requires an id
The user must supply a session id (full UUID or any unambiguous prefix). If they didn't, run the **session-manager** skill first so they can pick one. Never guess the id.

## The two flags (independent, don't conflate them)
- `--yes` **confirms** the deletion. Without it the script only dry-runs. It does **not** override any safety rail.
- `--force` **overrides** the "open in another live window" rail (rail 2) only. On its own it does not delete.
- To delete a session that is open in another live window you must pass **both**: `--yes --force`.
- Neither flag can override rail 1 (current session).

## Safety rails (enforced by the script)
1. **Current session** → hard-blocked, even with `--yes --force`. Cannot delete the window you're in.
2. **Open in another live window** → blocked unless overridden with `--force`. Detected reliably from `~/.claude/sessions/<pid>.json` (live process registry, pid verified alive), not a guess. Advise the user to close that window first. (`--yes` alone does **not** bypass this.)
3. **Dry-run by default** → without `--yes` the script only reports what it *would* remove. Nothing is deleted until you re-run with `--yes`. (A session touched in the last 10 min but held by no live window still dry-runs with a note: see exit 5.)
4. **Archived sessions** are deletable too (they resolve normally); the plan shows `[ARCHIVED]`.

## Workflow
Always do the dry-run pass first, then get explicit confirmation, then delete.

**Step 1: dry-run / safety check (no `--yes`):**
```bash
python "${CLAUDE_SKILL_DIR}/../session-manager/scripts/sessions.py" delete <id>
```
Interpret the exit code:
| Exit | Meaning | What you do |
|---|---|---|
| `3` | Target is the current session | Refuse. Tell the user to switch to/close that window and delete it from elsewhere. Stop. |
| `4` | Open in another live window (with pid) | Show the warning + file plan. Ask the user to **close that window** first. Only if they explicitly choose to override, delete with `--yes --force` (plain `--yes` will not bypass this). |
| `5` | Clean dry-run plan | Show the plan to the user and ask for explicit confirmation to delete. |
| `1` | Unknown / ambiguous id | Report it; offer to run session-manager to find the right id. Stop. |

**Step 2: delete, only after explicit user approval:**
```bash
python "${CLAUDE_SKILL_DIR}/../session-manager/scripts/sessions.py" delete <id> --yes
```
If the dry-run returned exit 4 (open in another live window) and the user explicitly chose to override, add `--force`:
```bash
python "${CLAUDE_SKILL_DIR}/../session-manager/scripts/sessions.py" delete <id> --yes --force
```
Report exactly what was removed (the script lists each path).

## Rules
- Never run with `--yes` before the user has seen the dry-run plan and explicitly approved.
- Add `--force` only to override an exit-4 (open in another live window) block, and only when the user explicitly chooses to override after being told to close the window. Never add `--force` reflexively; `--yes` alone is the normal path.
- Never attempt to bypass rail 1 (current session). If the user insists, explain they must do it from another session/window.
- Treat the operation as final: confirm the id and title in the plan match what the user intends before deleting.
