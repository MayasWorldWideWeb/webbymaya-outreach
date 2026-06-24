#!/usr/bin/env python3
"""
wm_status.py — WebByMaya All-Time Campaign Status
==================================================
One command to see everything: total outreach, pipeline health,
zones remaining, follow-up counts, and bounce rate.

USAGE:
    python3 wm_status.py
"""

import csv
import json
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

BOLD = "\033[1m"
G    = "\033[32m"
Y    = "\033[33m"
C    = "\033[36m"
M    = "\033[35m"
B    = "\033[34m"
DIM  = "\033[2m"
R    = "\033[0m"
W    = 54


def section(title, colour=C):
    bar = "─" * W
    print(f"\n  {colour}{BOLD}┌{bar}┐")
    print(f"  │  {title:<{W-2}}│")
    print(f"  └{bar}┘{R}")


def row(label, value, colour=""):
    print(f"  {DIM}{label:<26}{R}  {colour}{value}{R}")


def load_send_logs() -> list:
    rows = []
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        date_str = p.stem.replace("send_log_", "")
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_date"] = date_str
                rows.append(r)
    return rows


def load_sms_logs() -> list:
    rows = []
    for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
        date_str = p.stem.replace("sms_log_", "")
        with open(p, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_date"] = date_str
                rows.append(r)
    return rows


def load_followup_logs() -> list:
    rows = []
    for p in sorted(SCRIPT_DIR.glob("email_followup_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def load_bounces() -> list:
    path = SCRIPT_DIR / "bounce_log.csv"
    if not path.exists():
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_zone_state() -> dict:
    path = SCRIPT_DIR / "zone_state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def main():
    today = date.today().isoformat()

    email_rows   = load_send_logs()
    sms_rows     = load_sms_logs()
    followup_rows= load_followup_logs()
    bounces      = load_bounces()
    zone_state   = load_zone_state()

    # ── Email stats ───────────────────────────────────────────────────────
    email_sent     = [r for r in email_rows if r.get("status") == "sent"]
    email_skipped  = [r for r in email_rows if r.get("status") == "skipped"]
    email_failed   = [r for r in email_rows if r.get("status") == "failed"]
    unique_emails  = {r.get("email_sent_to","").lower() for r in email_sent}

    by_date_email: Counter = Counter(r["_date"] for r in email_sent)
    first_email = min(by_date_email) if by_date_email else "—"
    last_email  = max(by_date_email) if by_date_email else "—"

    # ── SMS stats ─────────────────────────────────────────────────────────
    sms_sent      = [r for r in sms_rows if r.get("status") == "sent"]
    sms_landline  = [r for r in sms_rows if r.get("status") == "landline"]

    # ── Follow-up stats ───────────────────────────────────────────────────
    fu_sent = [r for r in followup_rows if r.get("status") == "sent"]

    # ── Bounce rate ───────────────────────────────────────────────────────
    bounce_rate = len(bounces) / len(email_sent) * 100 if email_sent else 0

    # ── Category breakdown ────────────────────────────────────────────────
    cat_email: Counter = Counter(r.get("category","unknown") for r in email_sent)
    cat_sms:   Counter = Counter(r.get("category","unknown") for r in sms_sent)

    # ── Zone state ────────────────────────────────────────────────────────
    zones     = zone_state.get("zones", [])
    completed_raw = zone_state.get("completed", [])
    cur_idx   = zone_state.get("current_index", 0)
    remaining = zones[cur_idx:]
    # deduplicate by zone name — keep latest date
    seen: dict = {}
    for entry in completed_raw:
        z = entry["zone"]
        if z not in seen or entry["date"] > seen[z]["date"]:
            seen[z] = entry
    completed = list(seen.values())

    # ─────────────────────────────────────────────────────────────────────
    print(f"\n  {BOLD}{C}WebByMaya — Campaign Status  [{today}]{R}")

    # Outreach totals
    section("ALL-TIME OUTREACH", C)
    row("Emails sent",          f"{BOLD}{G}{len(email_sent)}{R}", G)
    row("Unique inboxes hit",   f"{BOLD}{G}{len(unique_emails)}{R}", G)
    row("SMS sent",             f"{BOLD}{G}{len(sms_sent)}{R}", G)
    row("Email follow-ups sent",f"{G}{len(fu_sent)}{R}")
    row("",                     "")
    row("Emails skipped",       f"{DIM}{len(email_skipped)}{R} (no email found)")
    row("SMS landline/VoIP",    f"{DIM}{len(sms_landline)}{R} (skipped)")
    row("Bounces / blocks",     f"{Y}{len(bounces)}{R}  ({bounce_rate:.1f}% bounce rate)")

    # Daily breakdown
    section("SENDS BY DATE", B)
    for d in sorted(by_date_email.keys()):
        sms_count = sum(1 for r in sms_rows if r["_date"] == d and r.get("status") == "sent")
        marker = f" {G}← today{R}" if d == today else ""
        print(f"  {DIM}{d}{R}   {B}email {by_date_email[d]:>3}{R}  {M}sms {sms_count:>3}{R}{marker}")

    # Top categories
    section("TOP CATEGORIES  (emails sent)", B)
    total_cat = len(email_sent)
    for cat, count in cat_email.most_common(8):
        pct    = count / total_cat * 100 if total_cat else 0
        filled = int(28 * count / total_cat) if total_cat else 0
        bar    = f"{B}{'█'*filled}{DIM}{'░'*(28-filled)}{R}"
        print(f"  {cat:<22} {bar}  {count:>3}  ({pct:.0f}%)")

    # Zone progress
    section("ZONE PIPELINE", M)
    row("Zones completed",   f"{G}{len(completed)}{R} / {len(zones)}")
    if completed:
        row("Last zone run",  completed[-1].get("zone","?") + "  " + completed[-1].get("date",""))
    if remaining:
        row("Next zone",      remaining[0])
        row("Zones left",     f"{Y}{len(remaining)}{R}")
    else:
        print(f"  {Y}All zones exhausted — time to add new markets.{R}")

    # Funnel
    section("CONVERSION FUNNEL", G)
    total_reached = len(unique_emails) + len(sms_sent)
    row("Total businesses reached", f"{BOLD}{total_reached}{R}")
    row("Received follow-up email", f"{len(fu_sent)}")
    row("Replied (run wm-replies)", f"{Y}check Gmail →  python3 check_replies.py{R}")
    print()


if __name__ == "__main__":
    main()
