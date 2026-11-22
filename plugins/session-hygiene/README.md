# session-hygiene

Saves the model's working notes before Claude Code auto-compacts a conversation, and hands them back afterwards.
Compaction keeps a summary but loses detail.
This plugin keeps two extra records so the next stretch of work starts with more than the summary.

## Install

```text
/plugin marketplace add dev-jayp/claude-plugins
/plugin install session-hygiene@dev-jayp-plugins
```

## The three moments it acts

1. **Before the limit (every prompt).**
   A small hook measures how large the last model call was.
   When it is within a margin of the auto-compact threshold, it tells the model to write or refresh `judgment.md`.
   The file is rewritten whole each time, in three sections: what this session is, open threads with the next step for each, and constraints specific to this session.
2. **At compaction (PreCompact).**
   A handoff file is built from the transcript: ticket and PR numbers, the user's recent instructions, files edited, git and PR commands run, subagents dispatched, and messages to and from other sessions.
   If `judgment.md` exists, it goes first.
3. **After compaction (SessionStart, matcher `compact`).**
   The latest handoff is printed into the new context, next to the summary.
   It is skipped when the file is older than 12 hours.

## Environment variables

| Variable | Default | Meaning |
|---|---|---|
| `SESSION_HYGIENE_THRESHOLD` | `167000` | Tokens at which auto-compact fires. Accepts `200000`, `200k` or `1m`. Set it to match your setup. |
| `SESSION_HYGIENE_MARGIN` | `30000` | The reminder starts this many tokens below the threshold. Same forms. |
| `CLAUDE_CONFIG_DIR` | `~/.claude` | Where Claude Code keeps its files; handoffs follow it. |

## Where files land

`<config dir>/handoffs/<session_id>/`

- `judgment.md`: written by the model when reminded.
- `latest.md`: the newest handoff, the one printed after compaction.
- `<YYYYMMDD-HHMMSS>.md`: one file per compaction.

If the assistant ends a reply with a `Needs you` heading listing questions, the handoff also records those questions next to your answers. Without that heading the section stays empty.

## Requirements

Python 3, runnable as `python` on your PATH. On macOS and Linux that may need the `python-is-python3` package or an alias.
Standard library only.

Every hook ends quietly with exit code 0 on any error, so it never blocks a prompt or a compaction.

## License

MIT, see [LICENSE](LICENSE).
