#!/usr/bin/env python3
"""
watch.py — WebByMaya Live Search Progress
==========================================
Run this in a second terminal while outreach.py is running:

    python3 watch.py

Refreshes every second. Press Ctrl+C to exit.
"""

import json
import os
import re
import sys
import time
import datetime
from pathlib import Path

SCRIPT_DIR    = Path(__file__).parent
PROGRESS_FILE = SCRIPT_DIR / "search_progress.json"
LOG_FILE      = SCRIPT_DIR / "search_output.log"
REFRESH_HZ    = 1
BAR_WIDTH     = 44

PROGRESS_RE = re.compile(r'\[(\d+)/(\d+)\].*?(\d+) prospects so far')
LABEL_RE    = re.compile(r"Zone '(.+?)':|Custom zips:|Geocoding \d+ city")


def clear():
    os.system("clear")


def progress_bar(done, total, width=BAR_WIDTH):
    pct = done / total if total else 0
    filled = int(width * pct)
    return f"[{'█' * filled}{'░' * (width - filled)}] {pct*100:5.1f}%"


def fmt_duration(seconds):
    if seconds < 0:
        return "--:--"
    td = datetime.timedelta(seconds=int(seconds))
    h, rem = divmod(td.seconds, 3600)
    m, s   = divmod(rem, 60)
    total_h = td.days * 24 + h
    if total_h:
        return f"{total_h}h {m:02d}m {s:02d}s"
    return f"{m:02d}m {s:02d}s"


def parse_log():
    """Parse search_output.log, return (done, total, found, label, finished, mtime)."""
    if not LOG_FILE.exists():
        return None
    try:
        text  = LOG_FILE.read_text(errors="replace")
        mtime = LOG_FILE.stat().st_mtime
        done = total = found = 0
        label = ""
        for line in text.splitlines():
            m = PROGRESS_RE.search(line)
            if m:
                done, total, found = int(m.group(1)), int(m.group(2)), int(m.group(3))
            lm = LABEL_RE.search(line)
            if lm and not label:
                label = lm.group(0).rstrip(":")
        finished = "✓ Done" in text or "contact emails found" in text
        return {"done": done, "total": total, "found": found,
                "label": label, "finished": finished,
                "started_at": mtime - (done / max(done, 1)),  # rough estimate
                "_from_log": True, "_mtime": mtime}
    except Exception:
        return None


def load_data():
    """Return progress dict from progress.json (preferred) or log fallback."""
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text())
        except Exception:
            pass
    return parse_log()


def render(data):
    done       = data.get("done", 0)
    total      = data.get("total", 1)
    found      = data.get("found", 0)
    label      = data.get("label", "")
    started_at = data.get("started_at", time.time())
    finished   = data.get("finished", False)
    from_log   = data.get("_from_log", False)

    # For log-based fallback, estimate elapsed from file mtime of first line
    elapsed  = time.time() - started_at if started_at else 0
    rate     = done / elapsed if elapsed > 0 and done > 0 else 0
    eta_secs = (total - done) / rate if rate > 0 and not finished else 0
    pct      = done / total * 100 if total else 0

    source = "  (live log)" if from_log else ""

    lines = []
    lines.append("")
    lines.append("  ╔══════════════════════════════════════════════════════╗")
    lines.append("  ║        WebByMaya — Live Search Progress              ║")
    lines.append("  ╚══════════════════════════════════════════════════════╝")
    lines.append("")
    lines.append(f"  Target  : {label}{source}")
    lines.append(f"  Searches: {done} / {total}  ({pct:.1f}%)")
    lines.append("")
    lines.append(f"  {progress_bar(done, total)}")
    lines.append("")
    lines.append(f"  Prospects found : {found}")

    if elapsed > 1:
        lines.append(f"  Elapsed         : {fmt_duration(elapsed)}")

    if finished:
        lines.append(f"  Status          : ✓  Complete!")
    elif done == 0:
        lines.append(f"  Status          : Starting up ...")
    elif rate > 0:
        lines.append(f"  ETA             : ~{fmt_duration(eta_secs)}")
        lines.append(f"  Speed           : {rate * 60:.1f} searches / min")

    lines.append("")
    lines.append("  ─────────────────────────────────────────────────────")
    lines.append(f"  Refreshing every {REFRESH_HZ}s  ·  Ctrl+C to exit")
    lines.append("")
    return "\n".join(lines)


def main():
    while True:
        clear()
        data = load_data()

        if data is None:
            print("\n  WebByMaya — Live Search Progress")
            print("  ─────────────────────────────────────────────────────")
            print("\n  Waiting for a search to start ...")
            print("  Run in another terminal:")
            print("    python3 outreach.py --zone philly-center --no-web-check")
            print("\n  Ctrl+C to exit")
        else:
            print(render(data))

        try:
            time.sleep(REFRESH_HZ)
        except KeyboardInterrupt:
            print("\n  Exited watch.\n")
            sys.exit(0)


if __name__ == "__main__":
    main()
