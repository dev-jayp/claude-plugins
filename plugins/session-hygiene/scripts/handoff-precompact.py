# handoff-precompact.py - PreCompact hook: before any compaction (auto or manual) write a handoff
# document from the transcript so structured facts survive the summary. Silent on success; never
# blocks. Input (stdin JSON): session_id, transcript_path, cwd, trigger. Requires handoff_extract.py
# in this same folder, imported in-process.
# A subagent's own autocompaction fires this hook too; the subagents check below skips it, so only
# the main session's compaction writes a handoff.
# The root follows CLAUDE_CONFIG_DIR when that is set, else ~/.claude.
# HANDOFF_ROOT overrides the output root (default <config dir>/handoffs) for tests.
import json
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


def _home():
    # USERPROFILE can be set but empty, and an unguarded read of it then yields a relative path.
    return os.environ.get('USERPROFILE') or os.path.expanduser('~')


def _config_dir():
    return os.environ.get('CLAUDE_CONFIG_DIR') or os.path.join(_home(), '.claude')


def _rebuild_transcript_path(cwd, sid):
    slug = str(cwd).replace(':', '-').replace('\\', '-').replace('/', '-')
    return os.path.join(_config_dir(), 'projects', slug, f'{sid}.jsonl')


def run(raw, hook_input):
    """raw is the hook JSON as text, hook_input is the parsed dict (may be {}).
    Returns (exit_code:int, stdout_text:str, stderr_text:str)."""
    if not isinstance(hook_input, dict):
        hook_input = {}
    sid = str(hook_input.get('session_id') or '')
    if not sid:
        return 0, '', ''
    tp = str(hook_input.get('transcript_path') or '')
    if not tp or not os.path.exists(tp):
        tp = _rebuild_transcript_path(hook_input.get('cwd') or '', sid)
    if not os.path.exists(tp):
        return 0, '', ''
    # A subagent's transcript lives under <sid>/subagents/. Its compaction must not re-extract the
    # parent transcript.
    norm = tp.lower()
    if '\\subagents\\' in norm or '/subagents/' in norm:
        return 0, '', ''

    root = os.environ.get('HANDOFF_ROOT') or os.path.join(_config_dir(), 'handoffs')

    title = ''
    tf = os.path.join(os.path.dirname(tp), sid, 'custom-title.json')
    if os.path.exists(tf):
        try:
            with open(tf, encoding='utf-8') as fh:
                title = json.load(fh).get('customTitle') or ''
        except Exception:
            title = ''

    os.environ['PYTHONIOENCODING'] = 'utf-8'
    os.environ['HANDOFF_TRIGGER'] = str(hook_input.get('trigger') or '')

    if SCRIPTS_DIR not in sys.path:
        sys.path.insert(0, SCRIPTS_DIR)
    try:
        import handoff_extract
        path = handoff_extract.extract(tp, sid, root, title, False)
    except Exception:
        return 0, '', ''

    if path:
        msg = f"[handoff] written before compaction: {path}"
        out = json.dumps({'systemMessage': msg}, separators=(',', ':'))
        return 0, out, ''
    return 0, '', ''


def main():
    raw = os.environ.get("HOOK_INPUT") or sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        hook_input = json.loads(raw)
    except Exception:
        hook_input = {}
    try:
        code, out, err = run(raw, hook_input)
    except Exception as e:
        sys.stderr.write(f"handoff-precompact: {e}\n")
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
