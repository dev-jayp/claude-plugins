"""Build a handoff document from a Claude Code transcript (JSONL) so a compaction never loses
structured facts: questions the assistant asked and the user's answers, identifiers, files edited, peer
messages, last instructions, subagents dispatched and whether each one has returned. Covers the
segment since the last compaction summary; earlier handoffs stay on disk. A judgment.md next to it
(model-authored) is placed first, right after a one-line header, so the 2 KB SessionStart preview
and the injector's character cut never remove it; the provenance paragraph follows it.
A near-empty segment (a second PreCompact pass over an already compacted transcript) never replaces
a larger latest.md: the timestamped file is still written and latest.md gets a one-line note.

Optional: an assistant message containing the heading "Needs you" is treated as a list of questions
for the user, ending at a U+25A0 character when one is present. Each is kept to its question lines (option
and recommendation lines dropped), capped at MAX_ITEM characters, next to the user's answer.

usage: handoff_extract.py <transcript.jsonl> <session_id> <handoffs_root> [title] [--all]
--all covers the whole transcript, ignoring earlier compaction summaries, and writes full-history.md
instead of latest.md: the recovery path for a session that compacted before this plugin was installed.
prints the written path."""
import json, os, re, sys, datetime

MAX_ITEM = 400
NEAR_EMPTY_ENTRIES = 20
NEAR_EMPTY_TOOL_CALLS = 2
STAMP = '■'
SKIP_LINE = re.compile(r"^[\s\-*>_`]*(\([a-z]\)|I'd suggest)", re.I)


def text_of(msg):
    c = msg.get('content')
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return '\n'.join(b.get('text', '') for b in c if isinstance(b, dict) and b.get('type') == 'text')
    return ''


def tool_uses(msg):
    c = msg.get('content')
    return [b for b in c if isinstance(b, dict) and b.get('type') == 'tool_use'] if isinstance(c, list) else []


def is_tool_result(msg):
    c = msg.get('content')
    return isinstance(c, list) and any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in c)


def packet_core(block):
    """Keep the header and question lines of a Needs-you packet; drop option and recommendation lines."""
    lines = [ln for ln in block.splitlines() if ln.strip()]
    keep = [ln for ln in lines if not SKIP_LINE.match(ln)]
    return '\n'.join(keep or lines)[:MAX_ITEM].strip()


def _now():
    # test-only override
    raw = os.environ.get('HANDOFF_NOW', '').strip()
    if raw:
        try:
            return datetime.datetime.strptime(raw, '%Y%m%d-%H%M%S')
        except ValueError:
            pass
    return datetime.datetime.now()


def extract(tp, sid, root, title='', full=False):
    """Callable entry point, imported in-process by handoff-precompact.py. Returns the path written."""
    entries = []
    last_compact = -1
    with open(tp, encoding='utf-8', errors='ignore') as fh:
        for line in fh:
            try:
                o = json.loads(line)
            except Exception:
                continue
            if o.get('isCompactSummary') or (o.get('message') or {}).get('isCompactSummary'):
                last_compact = len(entries)
            entries.append(o)
    seg = entries if full else (entries[last_compact + 1:] if last_compact >= 0 else entries)
    prior = len(entries) - len(seg)

    prompts, peers, needs, files, commits, sends, agents, ids = [], [], [], [], [], [], [], {}
    pr_refs, first_ts, last_ts = {}, None, None
    pending_needs = None
    tool_calls = 0
    for o in seg:
        m = o.get('message') or {}
        role = m.get('role')
        ts = (o.get('timestamp') or '')[:16].replace('T', ' ')
        if ts:
            first_ts = first_ts or ts
            last_ts = ts
        txt = text_of(m)
        for k in re.findall(r'\b[A-Z]{2,10}-\d{2,6}\b', txt):
            ids[k] = ids.get(k, 0) + 1
        for k in re.findall(r'(?:pull/|\bPR\s?#?|#)(\d{2,5})\b', txt):
            pr_refs[k] = pr_refs.get(k, 0) + 1
        if role == 'user' and '<task-notification>' in txt:
            for tid, status in re.findall(r'<task-id>([^<]+)</task-id>.*?<status>([^<]+)</status>', txt, flags=re.S):
                for a in agents:
                    if a['agent_id'] == tid.strip():
                        a['status'], a['done_ts'] = status.strip(), ts
        if role == 'user' and not is_tool_result(m) and txt.strip():
            head = txt.lstrip()[:120]
            if head.startswith('<cross-session-message') or 'Another Claude session sent a message' in head:
                who = re.search(r'from-name="([^"]+)"', txt)
                body = re.sub(r'<[^>]+>', ' ', txt)
                peers.append((ts, who.group(1) if who else '?', ' '.join(body.split())[:300]))
                continue
            if head.startswith('[') and 'hook' in head.lower():
                continue
            if 'This session is being continued from a previous conversation' in head:
                continue
            if '<task-notification>' in head:
                continue
            prompts.append((ts, ' '.join(txt.split())[:400]))
            if pending_needs is not None:
                needs.append((pending_needs[0], pending_needs[1], ts, ' '.join(txt.split())[:400]))
                pending_needs = None
        if role == 'assistant':
            i = txt.find('Needs you')
            if i >= 0:
                block = txt[i:]
                j = block.find(STAMP)
                block = block[:j] if j > 0 else block
                pending_needs = (ts, packet_core(block))
            for tu in tool_uses(m):
                tool_calls += 1
                name, inp = tu.get('name'), tu.get('input') or {}
                if name in ('Edit', 'Write', 'MultiEdit', 'NotebookEdit') and inp.get('file_path'):
                    files.append(inp['file_path'])
                elif name in ('Bash', 'PowerShell'):
                    cmd = inp.get('command', '')
                    if re.search(r'\bgit (commit|push|merge|rebase|cherry-pick)\b|\bgh (pr|issue|api)\b', cmd):
                        commits.append((ts, ' '.join(cmd.split())[:200]))
                elif name == 'SendMessage':
                    sends.append((ts, inp.get('to', '?'), inp.get('summary') or (inp.get('message') or '')[:120]))
                elif name == 'Agent':
                    agents.append({'ts': ts, 'model': inp.get('model') or 'default', 'desc': (inp.get('description') or '')[:80],
                                   'tool_use_id': tu.get('id'), 'agent_id': None, 'status': 'running', 'done_ts': ''})
        if role == 'user' and is_tool_result(m):
            # A background Agent launch answers at once with an agentId; the real result comes later as a
            # task notification. A foreground Agent answers with its result, so it is done here.
            for b in m.get('content'):
                if not (isinstance(b, dict) and b.get('type') == 'tool_result'):
                    continue
                a = next((x for x in agents if x['tool_use_id'] == b.get('tool_use_id')), None)
                if a is None:
                    continue
                cc = b.get('content')
                body = cc if isinstance(cc, str) else ' '.join(x.get('text', '') for x in cc if isinstance(x, dict)) if isinstance(cc, list) else ''
                mm = re.search(r'agentId:\s*([0-9a-f]{8,})', body)
                if mm:
                    a['agent_id'] = mm.group(1)
                else:
                    a['status'], a['done_ts'] = 'done', ts
    if pending_needs is not None:
        needs.append((pending_needs[0], pending_needs[1], '', '(no answer yet)'))

    def uniq(seq):
        seen, out = set(), []
        for x in seq:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    files = uniq(files)
    now = _now()
    outdir = os.path.join(root, sid)
    os.makedirs(outdir, exist_ok=True)
    judgment = ''
    jp = os.path.join(outdir, 'judgment.md')
    if os.path.exists(jp):
        judgment = open(jp, encoding='utf-8', errors='ignore').read().strip()

    L = []
    L.append(f"# Handoff: {title or sid}")
    L.append('')
    scope = "the whole transcript, every compaction included" if full else "the transcript segment since the last compaction"
    trig = os.environ.get('HANDOFF_TRIGGER', '').strip()
    # Claude Code previews only the first 2,000 characters of a large hook output, so the header stays
    # one short line and the Judgment section starts inside that preview.
    L.append(f"Written {now:%Y-%m-%d %H:%M}" + (f" before a {trig} compaction" if trig else "") +
             "; Judgment first, then the mechanical record; disk and git are the truth for code, docs and PR state.")
    L.append('')
    if judgment:
        L.append('## Judgment (written by the session before compaction)')
        L.append(judgment)
        L.append('')
    L.append('## Provenance')
    L.append(f"Written {now:%Y-%m-%d %H:%M}" + (f" before a {trig} compaction" if trig else "") + f" from {scope} "
             f"({len(seg)} entries after {prior} earlier ones; segment spans {first_ts or '?'} to {last_ts or '?'}). "
             "Facts in the sections that follow are extracted mechanically from the transcript; the Judgment section, "
             "when present, was written by the session before compaction. Truth for code, docs and PR state lives on "
             "disk and in git: re-read it rather than trusting memory.")
    L.append('')
    if ids or pr_refs:
        L.append('## Identifiers')
        if ids:
            L.append('- Tickets: ' + ', '.join(f"{k} ({v})" for k, v in sorted(ids.items(), key=lambda x: -x[1])[:12]))
        if pr_refs:
            L.append('- PR or issue numbers mentioned: ' + ', '.join(f"#{k} ({v})" for k, v in sorted(pr_refs.items(), key=lambda x: -x[1])[:12]))
        L.append('')
    L.append(f'## Decisions asked of the user and the answers ({len(needs)})')
    for ts, block, ats, ans in (needs if full else needs[-25:]):
        L.append(f"### {ts}")
        L.append(block)
        L.append(f"**User ({ats or 'pending'}):** {ans}")
        L.append('')
    L.append(f'## Last instructions from the user ({min(len(prompts), 15)} of {len(prompts)})')
    for ts, p in prompts[-15:]:
        L.append(f"- {ts}: {p}")
    L.append('')
    if peers:
        L.append('## Peer-session messages received')
        L.append(f"{len(peers)} received in this segment; the last {min(len(peers), 5)} are shown.")
        for ts, who, body in peers[-5:]:
            L.append(f"- {ts} from '{who}': {body}")
        L.append('')
    if sends:
        L.append(f'## Messages sent to peer sessions ({len(sends)})')
        for ts, to, s in sends[-10:]:
            L.append(f"- {ts} to '{to}': {s}")
        L.append('')
    if commits:
        L.append(f'## Git and PR commands run ({len(commits)})')
        for ts, c in commits[-20:]:
            L.append(f"- {ts}: `{c}`")
        L.append('')
    if files:
        L.append(f'## Files edited ({len(files)})')
        for f in files[-40:]:
            L.append(f"- `{f}`")
        L.append('')
    if agents:
        running = [a for a in agents if a['status'] == 'running']
        L.append(f'## Subagents dispatched ({len(agents)}, {len(running)} still running at compaction)')
        for a in agents[-12:]:
            if a['status'] == 'running':
                tail = 'STILL RUNNING: its result arrives later as a task notification; this line is why it was dispatched'
            else:
                tail = f"{a['status']} {a['done_ts']}".strip()
            L.append(f"- {a['ts']} [{a['model']}] {a['desc']} ({tail})")
        L.append('')
    stamped = [(m.group(1), int(m.group(2) or 0), x) for x in os.listdir(outdir)
               if (m := re.match(r'^(\d{8}-\d{6})(?:-(\d+))?\.md$', x))]
    earlier = [x for _, _, x in sorted(stamped)]
    if earlier:
        L.append('## Earlier handoffs for this session')
        for e in earlier[-5:]:
            L.append(f"- {os.path.join(outdir, e)}")
        L.append('')
    body = '\n'.join(L)
    if full:
        path = os.path.join(outdir, 'full-history.md')
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(body)
        return path
    stamp = f"{now:%Y%m%d-%H%M%S}"
    base = os.path.join(outdir, f"{stamp}.md")
    path = base
    for n in range(1, 52):
        if n > 1:
            path = os.path.join(outdir, f"{stamp}-{n}.md")
        try:
            with open(path, 'x', encoding='utf-8', newline='\n') as fh:
                fh.write(body)
            break
        except FileExistsError:
            continue
    else:
        path = base
        with open(path, 'w', encoding='utf-8', newline='\n') as fh:
            fh.write(body)
    latest = os.path.join(outdir, 'latest.md')
    near_empty = len(seg) < NEAR_EMPTY_ENTRIES or tool_calls < NEAR_EMPTY_TOOL_CALLS
    if near_empty and os.path.exists(latest):
        with open(latest, encoding='utf-8', errors='ignore') as fh:
            existing_len = len(fh.read())
        if existing_len > len(body):
            sys.stderr.write(f"handoff_extract: near-empty segment ({len(seg)} entries, {tool_calls} tool calls); "
                             f"kept {latest} ({existing_len} chars > {len(body)}), new handoff only at {path}\n")
            with open(latest, 'a', encoding='utf-8', newline='\n') as fh:
                fh.write(f"\n## Second compaction {now:%Y-%m-%d %H:%M}\n"
                         f"The segment had too few entries ({len(seg)} entries, {tool_calls} tool calls), so this file was kept; "
                         f"the new handoff is {path}.\n")
            return path
    with open(latest, 'w', encoding='utf-8', newline='\n') as fh:
        fh.write(body)
    return path


def main():
    args = [a for a in sys.argv[1:] if a != '--all']
    full = '--all' in sys.argv
    tp, sid, root = args[0], args[1], args[2]
    title = args[3] if len(args) > 3 else ''
    print(extract(tp, sid, root, title, full))


if __name__ == '__main__':
    main()
