---
name: session-manager
description: Use when the user wants to see, list, inventory, browse, or audit their Claude Code sessions/chats, including questions like "what sessions do I have", "which session is this", "show my chats", "how many sessions", finding old/temporary sessions to clean up, or seeing which sessions are archived.
---

# Session Manager

## Overview
Inventories Claude Code sessions on disk (across every project) and shows each session's id, title, last-accessed time, size, and message count. Marks the **current** session and any session **open in another live window**. By default it lists **active sessions only**; pass `--show-archived` to also get a separate table of archived sessions. Backed by `scripts/sessions.py`.

## When to use
- "List / show my sessions", "what chats do I have", "which one am I in"
- Finding throwaway/temporary sessions to delete (pair with **delete-session**)
- Seeing what's archived / picking one to **restore-session**
- Confirming a session id before archiving or deleting

## How to run
```bash
python "${CLAUDE_SKILL_DIR}/scripts/sessions.py" list
```
Options:
- `--project <substr>`: only sessions whose project path contains `<substr>` (e.g. `--project my-repo`).
- `--show-archived`: also print a second table of archived sessions (omitted by default, active only).
- `--json`: machine-readable output (active only unless combined with `--show-archived`).
- `info <id>`: full detail for one session (`<id>` = full UUID or any unambiguous prefix).

Run it and present the table(s) to the user. Do not re-implement the listing by hand.

When you present a table, it MUST include one column per session, in this order: **Short ID** (the 8-char prefix, e.g. `43c79452`), marker (★/▶/A), Title, Last access, Size, Msgs, Folder. The Short ID column is required; it is what the user copies into `/delete-session`, `/archive-session`, and `/restore-session`, so never omit or collapse it. The Folder column is the clean leaf directory a session was started from (derived from the session's logged `cwd`, e.g. `my-repo`, `notes`), not the raw encoded project-directory string. Titles longer than the display width print on a wrapped `↳` line beneath the row rather than being silently truncated; preserve that in any hand-built table too. When `--show-archived` is used, present the active and archived sessions as **two separate tables**, mirroring the script's output. Do **not** add a "Full IDs" block: the Short ID is sufficient for the action skills.

## Reading the output
| Marker | Meaning |
|---|---|
| `★` | **Current** session (this window). Protected: cannot be archived or deleted. |
| `▶` | **Open in another live window.** Detected reliably from `~/.claude/sessions/<pid>.json` (live process registry, pid verified alive), not a heuristic. Archive/delete is blocked until that window is closed. |
| `A` | **Archived**: hidden from `/resume`, restorable via **restore-session**. Only shown with `--show-archived`, in its own table. |
| (blank) | Idle / safe to manage. |

## Related skills
- **archive-session** `<id>`: keep a session but hide it from `/resume` (reversible move).
- **restore-session** `<id>`: bring an archived session back.
- **delete-session** `<id>`: permanently delete (owns the destructive safety rails).

## Notes
- "Current session" is detected via the `CLAUDE_CODE_SESSION_ID` env var. If the table shows no `★` and warns the var is unset, you are likely running outside a normal interactive session; flag that before any archive/delete.
- This skill is read-only; the action skills above own their safety rails.
