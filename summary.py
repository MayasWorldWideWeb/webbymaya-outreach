#!/usr/bin/env python3
"""
summary.py — WebByMaya Daily Outreach Summary
==============================================
Prints a full breakdown of the day's activity:
  • Search results (prospects found by zone)
  • Email outreach (sent / skipped / failed, by category)
  • SMS outreach  (sent / landline / failed, by category)
  • Combined totals and reach

USAGE
-----
    python3 summary.py                  # today's data
    python3 summary.py --date 2026-05-27
    python3 summary.py --date 2026-05-27 --top 10
"""

import argparse
import csv
import datetime
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional

SCRIPT_DIR = Path(__file__).parent

# ── ANSI colours ──────────────────────────────────────────────────────────────
G  = "\033[32m"   # green
Y  = "\033[33m"   # yellow
C  = "\033[36m"   # cyan
B  = "\033[34m"   # blue
M  = "\033[35m"   # magenta
DIM = "\033[2m"
R  = "\033[0m"    # reset
BOLD = "\033[1m"

W = 58  # box width


def box(title, colour=C):
    bar = "─" * W
    return f"\n  {colour}{BOLD}┌{bar}┐\n  │  {title:<{W-2}}│\n  └{bar}┘{R}"


def row(label, value, colour=""):
    return f"  {DIM}{label:<24}{R}  {colour}{value}{R}"


def bar_chart(data: dict, total: int, width=30, colour=G):
    lines = []
    for label, count in sorted(data.items(), key=lambda x: -x[1]):
        pct   = count / total if total else 0
        filled = int(width * pct)
        bar   = f"{colour}{'█' * filled}{DIM}{'░' * (width - filled)}{R}"
        lines.append(f"  {label:<22} {bar}  {count:>4}  ({pct*100:.0f}%)")
    return "\n".join(lines)


# ── Loaders ───────────────────────────────────────────────────────────────────

def load_search(date_str: str) -> Optional[Dict]:
    pf = SCRIPT_DIR / "search_progress.json"
    if pf.exists():
        try:
            d = json.loads(pf.read_text())
            return d
        except Exception:
            pass

    lf = SCRIPT_DIR / "search_output.log"
    if not lf.exists():
        return None
    text = lf.read_text(errors="replace")
    import re
    prog  = re.compile(r'\[(\d+)/(\d+)\].*?(\d+) prospects so far')
    label_re = re.compile(r"Zone '(.+?)':|Custom zips:|Geocoding \d+ city")
    done = total = found = 0
    label = ""
    for line in text.splitlines():
        m = prog.search(line)
        if m:
            done, total, found = int(m.group(1)), int(m.group(2)), int(m.group(3))
        lm = label_re.search(line)
        if lm and not label:
            label = lm.group(0).rstrip(":")
    finished = "✓ Done" in text or "contact emails found" in text
    return {
        "label": label, "total": total, "done": done,
        "found": found, "finished": finished, "_from_log": True,
    }


def load_csv_log(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_prospects(date_str: str) -> List[Dict]:
    for stem in (f"prospects_{date_str}_enriched", f"prospects_{date_str}"):
        p = SCRIPT_DIR / f"{stem}.csv"
        if p.exists():
            with open(p, newline="", encoding="utf-8") as f:
                return list(csv.DictReader(f))
    return []


# ── Section renderers ─────────────────────────────────────────────────────────

def render_search(data: Optional[Dict]) -> str:
    lines = [box("SEARCH  —  Prospects Found", C)]
    if not data:
        lines.append(f"\n  {DIM}No search data found for this date.{R}\n")
        return "\n".join(lines)

    label    = data.get("label") or "—"
    done     = data.get("done", 0)
    total    = data.get("total", 0)
    found    = data.get("found", 0)
    finished = data.get("finished", False)
    pct      = done / total * 100 if total else 0

    status_str = f"{G}✓ Complete{R}" if finished else f"{Y}In progress …{R}"

    lines += [
        "",
        row("Zone / Area",  label, C),
        row("Searches run", f"{done} / {total}  ({pct:.0f}%)"),
        row("Prospects found", f"{BOLD}{found}{R}"),
        row("Status",       status_str),
        "",
    ]
    return "\n".join(lines)


def render_email(rows: List[Dict], top: int) -> str:
    lines = [box("EMAIL OUTREACH", B)]
    if not rows:
        lines.append(f"\n  {DIM}No email log found for this date.{R}\n")
        return "\n".join(lines)

    status_counts: Counter = Counter(r.get("status", "unknown") for r in rows)
    sent    = status_counts.get("sent",    0)
    skipped = status_counts.get("skipped", 0)
    failed  = status_counts.get("failed",  0)
    total   = len(rows)

    cat_sent: Counter = Counter(
        r.get("category", "unknown")
        for r in rows if r.get("status") == "sent"
    )

    lines += [
        "",
        row("Total attempted", str(total)),
        row("Sent",    f"{G}{sent}{R}"),
        row("Skipped", f"{Y}{skipped}{R}  (no email found)"),
        row("Failed",  f"{M}{failed}{R}" if failed else f"{DIM}0{R}"),
    ]

    if sent and cat_sent:
        top_cats = dict(cat_sent.most_common(top))
        lines += [
            "",
            f"  {DIM}Top categories (sent):{R}",
            bar_chart(top_cats, sent, colour=B),
        ]

    failed_rows = [r for r in rows if r.get("status") == "failed"]
    if failed_rows:
        lines += ["", f"  {M}Failures:{R}"]
        for r in failed_rows[:5]:
            lines.append(f"    {r.get('name','?')} — {r.get('notes','')[:60]}")

    lines.append("")
    return "\n".join(lines)


def render_sms(rows: List[Dict], top: int) -> str:
    lines = [box("SMS OUTREACH", M)]
    if not rows:
        lines.append(f"\n  {DIM}No SMS log found for this date.{R}\n")
        return "\n".join(lines)

    status_counts: Counter = Counter(r.get("status", "unknown") for r in rows)
    sent     = status_counts.get("sent",     0)
    landline = status_counts.get("landline", 0)
    skipped  = status_counts.get("skipped",  0)
    failed   = status_counts.get("failed",   0)
    total    = len(rows)

    carrier_counts: Counter = Counter(r.get("carrier_type", "unknown") for r in rows)

    cat_sent: Counter = Counter(
        r.get("category", "unknown")
        for r in rows if r.get("status") == "sent"
    )

    lines += [
        "",
        row("Total attempted", str(total)),
        row("Sent",     f"{G}{sent}{R}"),
        row("Landline / VoIP", f"{Y}{landline}{R}  (skipped — not mobile)"),
        row("Skipped",  f"{DIM}{skipped}{R}"),
        row("Failed",   f"{M}{failed}{R}" if failed else f"{DIM}0{R}"),
    ]

    if len(carrier_counts) > 1:
        lines += ["", f"  {DIM}Carrier types:{R}"]
        for ctype, count in carrier_counts.most_common():
            pct = count / total * 100 if total else 0
            lines.append(f"    {ctype:<20}  {count:>4}  ({pct:.0f}%)")

    if sent and cat_sent:
        top_cats = dict(cat_sent.most_common(top))
        lines += [
            "",
            f"  {DIM}Top categories (sent):{R}",
            bar_chart(top_cats, sent, colour=M),
        ]

    failed_rows = [r for r in rows if r.get("status") == "failed"]
    if failed_rows:
        lines += ["", f"  {M}Failures:{R}"]
        for r in failed_rows[:5]:
            lines.append(f"    {r.get('name','?')} — {r.get('notes','')[:60]}")

    lines.append("")
    return "\n".join(lines)


def render_totals(search: Optional[Dict],
                  email_rows: List[Dict],
                  sms_rows: List[Dict],
                  prospects: List[Dict]) -> str:
    lines = [box("COMBINED TOTALS", G)]

    emails_sent = sum(1 for r in email_rows if r.get("status") == "sent")
    sms_sent    = sum(1 for r in sms_rows   if r.get("status") == "sent")

    # Unique businesses contacted by name (email OR sms sent)
    emailed_names = {r.get("name","") for r in email_rows if r.get("status") == "sent"}
    texted_names  = {r.get("name","") for r in sms_rows   if r.get("status") == "sent"}
    unique_reached = len(emailed_names | texted_names)

    found = search.get("found", 0) if search else 0

    # Prospects with no contact channel at all
    no_email = sum(1 for p in prospects if not p.get("email","").strip())
    no_phone = sum(1 for p in prospects if not p.get("phone","").strip())
    no_contact = sum(
        1 for p in prospects
        if not p.get("email","").strip() and not p.get("phone","").strip()
    )

    lines += [
        "",
        row("Prospects found",      f"{BOLD}{found}{R}", C),
        row("Emails sent",          f"{G}{emails_sent}{R}"),
        row("SMS sent",             f"{G}{sms_sent}{R}"),
        row("Unique biz reached",   f"{BOLD}{G}{unique_reached}{R}"),
        "",
        row("No email found",       f"{DIM}{no_email}{R}"),
        row("No phone found",       f"{DIM}{no_phone}{R}"),
        row("No contact at all",    f"{Y}{no_contact}{R}"),
        "",
    ]

    if found:
        reach_pct = unique_reached / found * 100
        lines.append(f"  {DIM}Reach rate: {G}{BOLD}{reach_pct:.1f}%{R}{DIM} of prospects got a message{R}")
        lines.append("")

    return "\n".join(lines)


# ── Main ──────────────────────────────────────────────────────────────────────

def parse_args():
    p = argparse.ArgumentParser(description="WebByMaya — daily outreach summary")
    p.add_argument("--date", default=datetime.date.today().strftime("%Y-%m-%d"),
                   help="Date to report on (YYYY-MM-DD, default: today)")
    p.add_argument("--top", type=int, default=8, metavar="N",
                   help="Top N categories to show in charts (default: 8)")
    return p.parse_args()


def main():
    args = parse_args()
    date = args.date

    email_log = SCRIPT_DIR / f"send_log_{date}.csv"
    sms_log   = SCRIPT_DIR / f"sms_log_{date}.csv"

    search    = load_search(date)
    email_rows = load_csv_log(email_log)
    sms_rows   = load_csv_log(sms_log)
    prospects  = load_prospects(date)

    header = f"\n  {BOLD}{C}WebByMaya — Daily Summary  [{date}]{R}"
    print(header)

    print(render_search(search))
    print(render_email(email_rows, args.top))
    print(render_sms(sms_rows, args.top))
    print(render_totals(search, email_rows, sms_rows, prospects))


if __name__ == "__main__":
    main()
