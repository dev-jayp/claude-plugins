#!/usr/bin/env python3
"""Claude Code session inventory + safe archive / restore / deletion.

Subcommands:
  list    [--project SUBSTR] [--show-archived] [--json]   Active sessions only by default;
                                                           --show-archived adds a second table of archived ones.
  info    <id>
  archive <id> [--force]    Move a session into the project's .archive/ (hidden from /resume).
  restore <id>              Move an archived session back so /resume shows it again.
  delete  <id> [--yes] [--force] [--active-min N]   Permanently delete (dry-run unless --yes).

Session layout:
  active   : <project>/<id>.jsonl        + <project>/<id>/ sidecar
  archived : <project>/.archive/<id>.jsonl + <project>/.archive/<id>/ sidecar
  scratchpad (ephemeral) : <temp>/claude/<project>/<id>/
  optional, only if the compaction-handoff hooks or the toast hook are installed:
    handoffs : <config>/handoffs/<id>/        turn stamp : <config>/tmp/turnstart-<id>.txt
  delete removes all of the above that exist; archive and restore move only the transcript
  and sidecar, so a restored session still finds its handoffs.

Open-window detection is reliable, not heuristic: ~/.claude/sessions/<pid>.json maps each
LIVE Claude process -> the sessionId it currently has open. We read that registry and verify
the pid is still alive.

Safety / flag semantics (two independent gates: don't conflate them):
  * CURRENT session (env CLAUDE_CODE_SESSION_ID) is never deletable/archivable, no flag overrides this.
  * --force overrides the "OPEN in another live window" block. (archive also honours --yes as a synonym
    for back-compat, since archive is reversible and has no separate confirm step.)
  * --yes CONFIRMS a delete (it is a DRY RUN otherwise). --yes does NOT override the open-window block.
  * To delete a session that is open in another live window you must pass BOTH --yes and --force.
  * archive/restore are reversible moves (no dry-run).
<id> may be a full UUID or any unambiguous prefix.
"""
import sys, os, json, time, shutil, argparse
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ACTIVE_MIN_DEFAULT = 10
ARCHIVE_DIRNAME = ".archive"


def config_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or (Path.home() / ".claude"))


def projects_dir() -> Path:
    return config_dir() / "projects"


def temp_base() -> Path:
    fallback = str(Path.home() / "AppData/Local/Temp") if os.name == "nt" else "/tmp"
    t = os.environ.get("TEMP") or os.environ.get("TMP") or os.environ.get("TMPDIR") or fallback
    return Path(t) / "claude"


def current_id() -> str:
    return os.environ.get("CLAUDE_CODE_SESSION_ID", "")


def pid_alive(pid) -> bool:
    try:
        pid = int(pid)
        if os.name == "nt":
            import ctypes
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
            if not h:
                return False
            ctypes.windll.kernel32.CloseHandle(h)
            return True
        os.kill(pid, 0)
        return True
    except Exception:
        return False


def open_map() -> dict:
    """sessionId -> {pid,status,name,cwd} for sessions currently open in a LIVE window."""
    m = {}
    sdir = config_dir() / "sessions"
    if not sdir.is_dir():
        return m
    for f in sdir.glob("*.json"):
        try:
            e = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        sid, pid = e.get("sessionId"), e.get("pid")
        if sid and (pid is None or pid_alive(pid)):
            m[sid] = e
    return m


def folder_label(cwd: str) -> str:
    """Clean leaf folder name a session was started from, derived from its logged cwd."""
    if not cwd:
        return ""
    parts = Path(cwd.replace("\\", "/")).parts
    if ".claude" in parts and "worktrees" in parts:
        i = parts.index(".claude")
        repo = parts[i - 1] if i > 0 else ""
        return f"{repo}/worktrees/{parts[-1]}"
    return parts[-1] if parts else ""


def title_and_counts(jsonl: Path):
    custom_title, ai_title, msgs, first, cwd = "", "", 0, "", ""
    try:
        with jsonl.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if '"custom-title"' not in line and '"type"' not in line and '"cwd"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if not cwd and isinstance(r.get("cwd"), str):
                    cwd = r["cwd"]
                t = r.get("type")
                if t == "custom-title" and r.get("customTitle"):
                    custom_title = r["customTitle"]
                elif t == "ai-title" and r.get("aiTitle"):
                    ai_title = r["aiTitle"]
                elif t == "user":
                    msgs += 1
                    if not first:
                        m = r.get("message", {})
                        c = m.get("content") if isinstance(m, dict) else None
                        if isinstance(c, str):
                            first = c
                        elif isinstance(c, list):
                            for p in c:
                                if isinstance(p, dict) and p.get("type") == "text":
                                    first = p.get("text", "")
                                    break
                elif t == "assistant":
                    msgs += 1
    except FileNotFoundError:
        pass
    # A manual /rename (custom-title) is sticky in the real UI and always wins over the
    # auto-generated ai-title, even if an ai-title event happens to log after it.
    return (custom_title or ai_title, msgs, " ".join(first.split()), cwd)


def collect(project_filter=None, include_archived=True):
    rows, cur, now, om = [], current_id(), time.time(), open_map()
    for proj in sorted(projects_dir().glob("*")):
        if not proj.is_dir():
            continue
        if project_filter and project_filter.lower() not in proj.name.lower():
            continue
        locations = [(proj, False)]
        arch = proj / ARCHIVE_DIRNAME
        if include_archived and arch.is_dir():
            locations.append((arch, True))
        for loc, archived in locations:
            for jsonl in loc.glob("*.jsonl"):
                sid = jsonl.stem
                try:
                    st = jsonl.stat()
                except OSError:
                    continue
                title, msgs, first, cwd = title_and_counts(jsonl)
                oe = om.get(sid)
                rows.append({
                    "id": sid, "title": title or "(untitled)", "project": proj.name,
                    "folder": folder_label(cwd) or proj.name,
                    "archived": archived, "mtime": st.st_mtime,
                    "age_min": (now - st.st_mtime) / 60.0, "size_kb": st.st_size // 1024,
                    "msgs": msgs, "first": first[:70], "current": sid == cur,
                    "open": bool(oe), "open_pid": (oe or {}).get("pid"),
                    "open_status": (oe or {}).get("status"), "jsonl": str(jsonl),
                })
    rows.sort(key=lambda r: r["mtime"], reverse=True)
    return rows


def fmt_age(m: float) -> str:
    return f"{m:.0f}m ago" if m < 60 else (f"{m/60:.1f}h ago" if m < 1440 else f"{m/1440:.1f}d ago")


def mark(r) -> str:
    if r["current"]:
        return "★"
    if r["open"]:
        return "▶"
    if r["archived"]:
        return "A"
    return " "


TITLE_W = 50


def _print_table(rows):
    hdr = f"{'':2} {'ID (short)':10} {'TITLE':{TITLE_W}} {'LAST ACCESS':12} {'SIZE':>7} {'MSGS':>5}  FOLDER"
    print(hdr + "\n" + "-" * len(hdr))
    for r in rows:
        title = r["title"]
        shown = title if len(title) <= TITLE_W else title[:TITLE_W - 1] + "…"
        print(f"{mark(r):2} {r['id'][:8]:10} {shown:{TITLE_W}} {fmt_age(r['age_min']):12} "
              f"{str(r['size_kb'])+'KB':>7} {r['msgs']:>5}  {r['folder']}")
        if len(title) > TITLE_W:
            print(f"{'':2} {'':10} ↳ {title}")


def cmd_list(args):
    rows = collect(args.project, include_archived=args.show_archived)
    if args.json:
        print(json.dumps(rows, indent=2))
        return 0
    if not current_id():
        print("WARNING: CLAUDE_CODE_SESSION_ID not set, cannot mark the current session.\n")
    active = [r for r in rows if not r["archived"]]
    archived = [r for r in rows if r["archived"]]
    print(f"{len(active)} active session(s).  ★ current  ▶ open in another live window\n")
    _print_table(active)
    if args.show_archived:
        print(f"\n{len(archived)} archived session(s).  (hidden from /resume; restore with: restore <id>)\n")
        if archived:
            _print_table(archived)
        else:
            print("  (none)")
    return 0


def resolve(sid, archived=None):
    rows = collect()
    if archived is not None:
        rows = [r for r in rows if r["archived"] == archived]
    exact = [r for r in rows if r["id"] == sid]
    if exact:
        return exact[0], None
    pref = [r for r in rows if r["id"].startswith(sid)]
    if len(pref) == 1:
        return pref[0], None
    if not pref:
        return None, f"No{' archived' if archived else ''} session matches id '{sid}'."
    return None, f"Ambiguous prefix '{sid}' matches: " + ", ".join(r["id"][:8] for r in pref)


def real_project_dir(row) -> Path:
    p = Path(row["jsonl"]).parent
    return p.parent if row["archived"] else p


def targets_for(row):
    """Everything keyed by the session id. The last two exist only on machines running the
    optional compaction-handoff hooks and the task-finished toast; callers skip missing paths,
    so users without those hooks see no difference."""
    jsonl = Path(row["jsonl"])
    sid = row["id"]
    return [
        jsonl,
        jsonl.parent / sid,
        temp_base() / real_project_dir(row).name / sid,
        config_dir() / "handoffs" / sid,
        config_dir() / "tmp" / f"turnstart-{sid}.txt",
    ]


def _check_movable(row, action, allow_open):
    if row["current"]:
        print(f"BLOCKED: '{row['id']}' is the CURRENT session: cannot {action} the window you're in.")
        print("        Do it from another session/window.")
        return 3
    if row["open"] and not allow_open:
        print(f"Session {row['id']}  ({row['title']})")
        print(f"\nBLOCKED: OPEN in another live window (pid {row['open_pid']}, {row['open_status']}).")
        print(f"        Close that window first, then {action} it. To override, re-run with --force.")
        return 4
    return 0


def cmd_archive(args):
    row, err = resolve(args.id, archived=False)
    if err:
        print("ERROR:", err)
        return 1
    rc = _check_movable(row, "archive", args.force or args.yes)
    if rc:
        return rc
    proj = real_project_dir(row)
    dest = proj / ARCHIVE_DIRNAME
    dest.mkdir(exist_ok=True)
    moved = []
    for src in [Path(row["jsonl"]), proj / row["id"]]:
        if src.exists():
            shutil.move(str(src), str(dest / src.name))
            moved.append(str(dest / src.name))
    print(f"ARCHIVED {row['id']}  ({row['title']}), now hidden from /resume:")
    for m in moved:
        print(f"    -> {m}")
    print("Restore with: restore " + row["id"][:8])
    return 0


def cmd_restore(args):
    row, err = resolve(args.id, archived=True)
    if err:
        print("ERROR:", err)
        return 1
    proj = real_project_dir(row)
    moved = []
    for src in [Path(row["jsonl"]), proj / ARCHIVE_DIRNAME / row["id"]]:
        if src.exists():
            tgt = proj / src.name
            if tgt.exists():
                print(f"ERROR: {tgt} already exists in active set, not overwriting.")
                return 1
            shutil.move(str(src), str(tgt))
            moved.append(str(tgt))
    print(f"RESTORED {row['id']}  ({row['title']}), /resume will show it again:")
    for m in moved:
        print(f"    -> {m}")
    return 0


def cmd_info(args):
    row, err = resolve(args.id)
    if err:
        print("ERROR:", err)
        return 1
    print(json.dumps(row, indent=2))
    return 0


def cmd_delete(args):
    row, err = resolve(args.id)
    if err:
        print("ERROR:", err)
        return 1
    head = (f"Session {row['id']}\n  title : {row['title']}\n  project: {row['project']}"
            f"{'  [ARCHIVED]' if row['archived'] else ''}\n"
            f"  last accessed: {fmt_age(row['age_min'])}  ({row['size_kb']}KB, {row['msgs']} msgs)")
    if row["current"]:
        print(f"BLOCKED: '{row['id']}' is the CURRENT session and cannot be deleted from within itself.")
        return 3
    plan = "\n".join(f"    - {p}" for p in targets_for(row) if p.exists()) or "    (nothing on disk?)"
    if row["open"] and not args.force:
        print(head)
        print(f"\nBLOCKED: OPEN in another live window (pid {row['open_pid']}, {row['open_status']}).")
        print("        Close that window first, then retry. To delete anyway, re-run with --yes --force.")
        print("\nWould remove:\n" + plan)
        return 4
    if not row["open"] and row["age_min"] < args.active_min and not args.yes:
        print(head)
        print(f"\nNOTE: modified {fmt_age(row['age_min'])} (< {args.active_min}m) but no live window holds it.")
        print("\nWould remove:\n" + plan + "\n\nRe-run with --yes to delete.")
        return 5
    if not args.yes:
        print(head + "\n\nDRY RUN: nothing deleted. Would remove:\n" + plan + "\n\nRe-run with --yes to delete.")
        return 5
    removed = []
    for p in targets_for(row):
        if not p.exists():
            continue
        try:
            shutil.rmtree(p) if p.is_dir() else p.unlink()
            removed.append(str(p))
        except Exception as e:
            print(f"  ! failed to remove {p}: {e}")
    print(head + "\n\nDELETED:")
    for r in removed:
        print(f"    - {r}")
    return 0


def main():
    ap = argparse.ArgumentParser(prog="sessions")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("list"); p.add_argument("--project"); p.add_argument("--show-archived", action="store_true"); p.add_argument("--json", action="store_true")
    p = sub.add_parser("info"); p.add_argument("id")
    p = sub.add_parser("archive"); p.add_argument("id"); p.add_argument("--force", action="store_true"); p.add_argument("--yes", action="store_true")
    p = sub.add_parser("restore"); p.add_argument("id")
    p = sub.add_parser("delete"); p.add_argument("id"); p.add_argument("--yes", action="store_true"); p.add_argument("--force", action="store_true"); p.add_argument("--active-min", type=int, default=ACTIVE_MIN_DEFAULT)
    args = ap.parse_args()
    return {"list": cmd_list, "info": cmd_info, "archive": cmd_archive,
            "restore": cmd_restore, "delete": cmd_delete}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
