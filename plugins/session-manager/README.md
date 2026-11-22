# Session Manager

List, archive, restore, and delete your Claude Code sessions across every project, from inside Claude Code.

Four skills share one Python script that uses only the standard library:

| Skill | What it does |
|---|---|
| `session-manager` | Lists sessions across every project (archived ones too with `--show-archived`): id, title, last access, size, message count. Marks the current session, sessions open in another live window, and archived ones. **Read-only.** |
| `delete-session` | Permanently deletes one session (transcript, sidecar, scratchpad, and its handoff folder when present) behind dry-run and confirmation safety rails. |
| `archive-session` | Hides a session from `/resume` by moving it into the project's `.archive/` folder. Fully reversible. |
| `restore-session` | Brings an archived session back so `/resume` lists it again. |

## Why

`/resume` lists every session you have ever started and offers no way to prune, hide, or audit them. This plugin adds that, with checks to help avoid deleting the wrong session or the one you are in.

## Safety model

- **The current session** (found through the `CLAUDE_CODE_SESSION_ID` variable) can never be archived or deleted; no flag overrides this. If the variable is missing, the list shows a warning.
- **Sessions open in another live window** are detected from `~/.claude/sessions/<pid>.json` (the live process registry, with the process checked as alive) and blocked unless you pass `--force`.
- **Delete is a dry run by default.** Nothing is removed until you run it again with `--yes`, and the skill shows you the file list first. Deletion cannot be undone.
- **Archive is reversible.** It moves files into `.archive/`; restore moves them back.

## Install

```text
/plugin marketplace add dev-jayp/claude-plugins
/plugin install session-manager@dev-jayp-plugins
```

Then ask naturally ("show my sessions", "delete session <id>", "archive this chat", "restore <id>") or call a skill directly, for example `/session-manager:delete-session <id>`.

## Requirements

- Python 3, runnable as `python` on your `PATH`.
- Windows, macOS, or Linux.

## License

MIT, see [LICENSE](LICENSE).
