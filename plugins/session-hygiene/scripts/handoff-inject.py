# handoff-inject.py - SessionStart(compact) hook: after a compaction, inject this session's latest
# handoff so the continued session has the record next to the summary. Plain stdout from
# SessionStart is injected as context. Silent when no handoff exists or it is older than 12 hours.
# The root follows CLAUDE_CONFIG_DIR when that is set, else ~/.claude.
# HANDOFF_ROOT overrides the root (default <config dir>/handoffs) for tests.
import datetime
import json
import os
import sys

MAX_CHARS = 16000


def _home():
    # USERPROFILE can be set but empty, and an unguarded read of it then yields a relative path.
    return os.environ.get('USERPROFILE') or os.path.expanduser('~')


def _config_dir():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(_home(), '.claude')


def run(raw, hook_input):
    """raw is the hook JSON as text, hook_input is the parsed dict (may be {}).
    Returns (exit_code:int, stdout_text:str, stderr_text:str)."""
    if not isinstance(hook_input, dict):
        hook_input = {}
    sid = str(hook_input.get('session_id') or '')
    if not sid:
        return 0, '', ''
    root = os.environ.get('HANDOFF_ROOT') or os.path.join(_config_dir(), 'handoffs')
    f = os.path.normpath(os.path.join(root, sid, 'latest.md'))
    if not os.path.exists(f):
        return 0, '', ''
    mtime = datetime.datetime.fromtimestamp(os.path.getmtime(f))
    if mtime < datetime.datetime.now() - datetime.timedelta(hours=12):
        return 0, '', ''

    with open(f, encoding='utf-8') as fh:
        body = fh.read()
    if len(body) > MAX_CHARS:
        body = body[:MAX_CHARS] + f"\n... (truncated; full file: {f})"

    lines = [
        f"=== HANDOFF FROM BEFORE THIS COMPACTION ({f}) ===",
        body,
        "=== END HANDOFF. The summary above and this record together are the session state; "
        "re-read code, docs and PRs from disk before asserting specifics. ===",
    ]
    out = "\n".join(lines) + "\n"
    return 0, out, ''


def main():
    raw = os.environ.get("HOOK_INPUT") or sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        hook_input = json.loads(raw)
    except Exception:
        hook_input = {}
    try:
        code, out, err = run(raw, hook_input)
    except Exception as e:
        sys.stderr.write(f"handoff-inject: {e}\n")
        code, out, err = 0, '', ''
    if out:
        sys.stdout.buffer.write(out.encode("utf-8"))
    if err:
        sys.stderr.buffer.write(err.encode("utf-8"))
    sys.exit(code)


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
