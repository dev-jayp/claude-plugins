# context-meter.py - UserPromptSubmit hook. Reads the size of the last API call from the session
# transcript and, when it is within a margin of the auto-compact threshold, tells the model to write
# or refresh <config dir>/handoffs/<session_id>/judgment.md before compaction lands.
# Input (stdin JSON): session_id, transcript_path. Silent, exit 0, on any error or below the margin.
# Env: SESSION_HYGIENE_THRESHOLD (tokens at which auto-compact fires, default 167000; 200k or 1m
# forms accepted), SESSION_HYGIENE_MARGIN (default 30000, same forms).
import json
import os
import re
import sys

DEFAULT_THRESHOLD = 167000
DEFAULT_MARGIN = 30000
TAIL_BYTES = 600000


def _config_dir():
    home = os.environ.get('USERPROFILE') or os.path.expanduser('~')
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(home, '.claude')


def _tokens(name, default):
    raw = (os.environ.get(name) or '').strip()
    m = re.match(r'^(\d+(?:\.\d+)?)\s*([kKmM]?)$', raw)
    if not m:
        return default
    n = float(m.group(1))
    unit = m.group(2).lower()
    return int(n * (1000000 if unit == 'm' else 1000 if unit == 'k' else 1))


def _last_call_size(tp):
    with open(tp, 'rb') as f:
        f.seek(0, os.SEEK_END)
        length = f.tell()
        take = min(length, TAIL_BYTES)
        f.seek(length - take)
        tail = f.read(take).decode('utf-8', errors='replace')
    ctx = 0
    for line in tail.split('\n'):
        # A compaction boundary after the last call makes the recorded size stale. Only a real
        # system record counts: a message that merely mentions the marker is still measured.
        if re.search(r'compact_boundary', line, re.IGNORECASE):
            try:
                ev = json.loads(line)
                if isinstance(ev, dict) and ev.get('type') == 'system' and ev.get('subtype') == 'compact_boundary':
                    ctx = 0
                    continue
            except Exception:
                pass
        cm = re.search(r'"cache_creation_input_tokens":\s*(\d+)', line)
        if cm:
            rm = re.search(r'"cache_read_input_tokens":\s*(\d+)', line)
            im = re.search(r'"input_tokens":\s*(\d+)', line)
            ctx = int(cm.group(1)) + (int(rm.group(1)) if rm else 0) + (int(im.group(1)) if im else 0)
    return ctx


def main():
    raw = os.environ.get('HOOK_INPUT') or sys.stdin.buffer.read().decode('utf-8-sig', errors='replace')
    ji = json.loads(raw)
    if not isinstance(ji, dict):
        return
    sid = str(ji.get('session_id') or '')
    tp = str(ji.get('transcript_path') or '')
    if not sid or not tp or not os.path.isfile(tp):
        return

    threshold = _tokens('SESSION_HYGIENE_THRESHOLD', DEFAULT_THRESHOLD)
    margin = _tokens('SESSION_HYGIENE_MARGIN', DEFAULT_MARGIN)
    ctx = _last_call_size(tp)
    if ctx < threshold - margin:
        return

    target = os.path.join(_config_dir(), 'handoffs', sid, 'judgment.md')
    msg = (
        "[context] This session's last call carried about %dK tokens; auto-compact fires near %dK. "
        "Write or refresh %s now, before the compaction lands. Rewrite the whole file each time, "
        "in three sections: (1) what this session is; (2) open threads, each with its concrete "
        "next step; (3) constraints specific to this session. Refresh it at natural pauses while "
        "the context stays this large. A handoff built from the transcript is added at compaction "
        "and this file is placed first in it."
        % (round(ctx / 1000), round(threshold / 1000), target))
    out = {'hookSpecificOutput': {'hookEventName': 'UserPromptSubmit', 'additionalContext': msg}}
    sys.stdout.buffer.write(json.dumps(out).encode('utf-8'))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        pass
    sys.exit(0)
