#!/usr/bin/env python3
"""
wm_status.py — WebByMaya All-Time Campaign Status
"""

import csv
import json
import os
from collections import Counter
from datetime import date, datetime
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


def _read_csv(path):
    try:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def load_send_logs():
    rows = []
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        date_str = p.stem.replace("send_log_", "")
        for r in _read_csv(p):
            r["_date"] = date_str
            r["_type"] = "outreach"
            rows.append(r)
    return rows


def load_sms_logs():
    rows = []
    for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
        date_str = p.stem.replace("sms_log_", "")
        for r in _read_csv(p):
            r["_date"] = date_str
            rows.append(r)
    return rows


def load_all_followup_logs():
    """Load email follow-ups, drip sequences, clicker follow-ups, and seasonal sends."""
    rows = []

    # Legacy follow-up logs (email_followup_log_*.csv)
    for p in sorted(SCRIPT_DIR.glob("email_followup_log_*.csv")):
        for r in _read_csv(p):
            r["_type"] = "followup"
            r["_date"] = (r.get("timestamp","") or "")[:10]
            rows.append(r)

    # Drip sequence follow-ups (followup_log_*.csv)
    for p in sorted(SCRIPT_DIR.glob("followup_log_*.csv")):
        for r in _read_csv(p):
            r["_type"] = "drip"
            r["_date"] = (r.get("timestamp","") or "")[:10]
            rows.append(r)

    # Clicker follow-ups
    for p in sorted(SCRIPT_DIR.glob("clicker_followup_log_*.csv")):
        for r in _read_csv(p):
            r["_type"] = "clicker"
            r["_date"] = (r.get("timestamp","") or "")[:10]
            rows.append(r)

    # Seasonal campaigns (exclude dry runs)
    for p in sorted(SCRIPT_DIR.glob("seasonal_log_*.csv")):
        for r in _read_csv(p):
            if r.get("dry_run","0") == "1":
                continue
            r["_type"] = "seasonal"
            r["_date"] = r.get("date","")
            r.setdefault("status", "sent")
            r["email_sent_to"] = r.get("email","")
            rows.append(r)

    return rows


def load_bounces():
    return _read_csv(SCRIPT_DIR / "bounce_log.csv")


def load_zone_state():
    path = SCRIPT_DIR / "zone_state.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def automation_status():
    """Check if the daily cron ran today and whether it completed."""
    log = SCRIPT_DIR / "cron_run.log"
    if not log.exists():
        return "unknown", None
    today = date.today().isoformat()
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
        ran_today = f"WebByMaya Daily Run — {today}" in text
        completed = f"  Done: {datetime.now().strftime('%a')}" in text or \
                    text.count(f"Daily Run — {today}") > 0
        mtime_min = round((datetime.now() - datetime.fromtimestamp(log.stat().st_mtime)).total_seconds() / 60)
        return ("running" if ran_today else "not_run"), mtime_min
    except Exception:
        return "unknown", None


def main():
    today = date.today().isoformat()

    email_rows   = load_send_logs()
    sms_rows     = load_sms_logs()
    fu_rows      = load_all_followup_logs()
    bounces      = load_bounces()
    zone_state   = load_zone_state()

    # ── Outreach emails ───────────────────────────────────────────────────
    email_sent    = [r for r in email_rows if r.get("status") == "sent"]
    email_skipped = [r for r in email_rows if r.get("status") == "skipped"]
    email_failed  = [r for r in email_rows if r.get("status") == "failed"]
    unique_emails = {r.get("email_sent_to","").lower() for r in email_sent}

    by_date_email: Counter = Counter(r["_date"] for r in email_sent)

    # ── Follow-up / drip / clicker / seasonal ────────────────────────────
    fu_sent       = [r for r in fu_rows if r.get("status") == "sent" and r["_type"] == "followup"]
    drip_sent     = [r for r in fu_rows if r.get("status") == "sent" and r["_type"] == "drip"]
    clicker_sent  = [r for r in fu_rows if r.get("status") == "sent" and r["_type"] == "clicker"]
    seasonal_sent = [r for r in fu_rows if r["_type"] == "seasonal"]

    total_followon = len(fu_sent) + len(drip_sent) + len(clicker_sent) + len(seasonal_sent)

    # ── SMS ───────────────────────────────────────────────────────────────
    sms_sent = [r for r in sms_rows if r.get("status") == "sent"]

    # ── Bounce rate ───────────────────────────────────────────────────────
    bounce_rate = len(bounces) / len(email_sent) * 100 if email_sent else 0

    # ── Categories ────────────────────────────────────────────────────────
    cat_email: Counter = Counter(r.get("category","unknown") for r in email_sent)

    # ── Zone state ────────────────────────────────────────────────────────
    zones         = zone_state.get("zones", [])
    completed_raw = zone_state.get("completed", [])
    cur_idx       = zone_state.get("current_index", 0)
    remaining     = zones[cur_idx:]
    seen: dict    = {}
    for entry in completed_raw:
        z = entry["zone"]
        if z not in seen or entry["date"] > seen[z]["date"]:
            seen[z] = entry
    completed = list(seen.values())

    # ── Automation health ─────────────────────────────────────────────────
    auto_status, log_age_min = automation_status()

    # ── Print ─────────────────────────────────────────────────────────────
    print(f"\n  {BOLD}{C}WebByMaya — Campaign Status  [{today}]{R}")

    section("ALL-TIME OUTREACH", C)
    row("Cold emails sent",      f"{BOLD}{G}{len(email_sent)}{R}  ({len(unique_emails)} unique inboxes)", G)
    row("  ↳ drip follow-ups",   f"{G}{len(drip_sent)}{R}")
    row("  ↳ clicker follow-ups",f"{G}{len(clicker_sent)}{R}")
    row("  ↳ seasonal campaigns",f"{G}{len(seasonal_sent)}{R}")
    row("  ↳ legacy follow-ups", f"{G}{len(fu_sent)}{R}")
    row("SMS sent",              f"{DIM}{len(sms_sent)}{R}  (disabled — toll-free rejected)")
    row("",                      "")
    row("No email found",        f"{DIM}{len(email_skipped)}{R}")
    row("Failed sends",          f"{DIM}{len(email_failed)}{R}")
    row("Bounces / blocks",      f"{Y}{len(bounces)}{R}  ({bounce_rate:.1f}%)")

    section("SENDS BY DATE  (cold outreach)", B)
    for d in sorted(by_date_email.keys()):
        marker = f" {G}← today{R}" if d == today else ""
        print(f"  {DIM}{d}{R}   {B}email {by_date_email[d]:>3}{R}{marker}")

    section("TOP CATEGORIES  (cold emails)", B)
    total_cat = len(email_sent)
    for cat, count in cat_email.most_common(8):
        pct    = count / total_cat * 100 if total_cat else 0
        filled = int(28 * count / total_cat) if total_cat else 0
        bar    = f"{B}{'█'*filled}{DIM}{'░'*(28-filled)}{R}"
        print(f"  {cat:<22} {bar}  {count:>3}  ({pct:.0f}%)")

    section("ZONE PIPELINE", M)
    row("Zones completed",  f"{G}{len(completed)}{R} / {len(zones)}")
    if completed:
        row("Last zone run", completed[-1].get("zone","?") + "  " + completed[-1].get("date",""))
    if remaining:
        row("Next zone",     remaining[0])
        row("Zones left",    f"{Y}{len(remaining)}{R}")
        next_5 = ", ".join(remaining[1:6])
        if next_5:
            row("  coming up",  f"{DIM}{next_5}{R}")
    else:
        print(f"  {Y}All zones exhausted — time to add new markets.{R}")

    section("CONVERSION FUNNEL", G)
    total_reached = len(unique_emails) + len(sms_sent)
    row("Total businesses reached",  f"{BOLD}{total_reached}{R}")
    row("Follow-on emails sent",     f"{total_followon}")
    row("Replied",                   f"{Y}run wm-replies to check Gmail{R}")

    section("AUTOMATION", C)
    if auto_status == "running":
        row("Today's run",   f"{G}ran today{R}  (log updated {log_age_min}m ago)")
    elif auto_status == "not_run":
        row("Today's run",   f"{Y}not started yet{R}")
    else:
        row("Today's run",   f"{DIM}unknown{R}")
    print()


if __name__ == "__main__":
    main()
