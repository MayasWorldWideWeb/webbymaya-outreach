#!/usr/bin/env python3
"""
subject_perf.py — Analyze email open/click rates by category and subject line.

Cross-references send_log_*.csv with SendGrid's messages API to show which
categories get the best response and which subject line variants are winning.

USAGE
    python3 subject_perf.py            # full report
    python3 subject_perf.py --days 30  # last 30 days only
    python3 subject_perf.py --top 10   # show top 10 categories only
"""

import argparse
import csv
import datetime
import json
import os
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent

SG_KEY = os.environ.get("SENDGRID_API_KEY", "")


def _load_zshrc_key() -> str:
    zshrc = Path.home() / ".zshrc"
    if not zshrc.exists():
        return ""
    for line in zshrc.read_text().splitlines():
        if "SENDGRID_API_KEY" in line and "=" in line:
            val = line.split("=", 1)[-1].strip().strip('"').strip("'")
            if val:
                return val
    return ""


def get_sg_key() -> str:
    return SG_KEY or _load_zshrc_key()


def fetch_sg_messages(sg_key: str) -> dict[str, dict]:
    """Returns {email: {opens, clicks}} for all messages in SendGrid activity."""
    if not sg_key:
        return {}
    try:
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/messages?limit=1000",
            headers={"Authorization": f"Bearer {sg_key}"},
        )
        msgs = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("messages", [])
        result: dict[str, dict] = {}
        for m in msgs:
            email = (m.get("to_email") or "").lower().strip()
            if not email:
                continue
            if email not in result:
                result[email] = {"opens": 0, "clicks": 0}
            result[email]["opens"]  += m.get("opens_count", 0)
            result[email]["clicks"] += m.get("clicks_count", 0)
        return result
    except Exception as e:
        print(f"[SendGrid API error] {e}", file=sys.stderr)
        return {}


def load_send_logs(days: int = 0) -> list[dict]:
    rows = []
    cutoff = ""
    if days > 0:
        cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "sent":
                    continue
                if cutoff and (row.get("timestamp", "") or "")[:10] < cutoff:
                    continue
                rows.append(row)
    return rows


def normalize_category(cat: str) -> str:
    c = (cat or "").strip().lower()
    if not c:
        return "(unknown)"
    # Collapse variants into canonical buckets
    for canon, variants in [
        ("hair salon",    ["hair", "salon", "barber", "barbershop"]),
        ("nail salon",    ["nail"]),
        ("spa / massage", ["spa", "massage", "wax", "threading", "lash", "estheti", "skin"]),
        ("restaurant",    ["restaurant", "food", "pizza", "diner", "bistro", "grill", "eatery"]),
        ("cafe / bakery", ["cafe", "coffee", "bakery", "pastry"]),
        ("bar / nightlife", ["bar", "nightlife", "lounge", "pub"]),
        ("auto / mechanic", ["auto", "mechanic", "car repair", "tire"]),
        ("cleaning",      ["cleaning", "janitorial", "maid"]),
        ("landscaping",   ["landscaping", "lawn", "tree"]),
        ("fitness / yoga", ["gym", "fitness", "yoga", "trainer", "crossfit"]),
        ("tattoo",        ["tattoo", "piercing", "ink"]),
        ("photographer",  ["photo", "videograph"]),
        ("florist",       ["florist", "flower"]),
        ("pet",           ["pet", "grooming", "veterinar"]),
        ("plumbing / HVAC", ["plumb", "hvac", "heat", "cool", "electric"]),
    ]:
        if any(v in c for v in variants):
            return canon
    return c


def analyze(send_logs: list[dict], sg_data: dict) -> dict:
    """
    Returns dict of {category: {sent, opens, clicks, open_rate, click_rate}}
    and {subject_prefix: same structure}
    """
    by_cat:  dict[str, dict] = defaultdict(lambda: {"sent": 0, "opens": 0, "clicks": 0})
    by_subj: dict[str, dict] = defaultdict(lambda: {"sent": 0, "opens": 0, "clicks": 0})

    for row in send_logs:
        email = (row.get("email_sent_to") or "").lower().strip()
        cat   = normalize_category(row.get("category", ""))
        subj  = (row.get("subject") or "I built {name} a free website").strip()

        # Collapse subject to first ~40 chars to group variants
        subj_key = subj[:50] if len(subj) > 50 else subj

        sg = sg_data.get(email, {})
        opens  = 1 if sg.get("opens", 0)  > 0 else 0
        clicks = 1 if sg.get("clicks", 0) > 0 else 0

        by_cat[cat]["sent"]   += 1
        by_cat[cat]["opens"]  += opens
        by_cat[cat]["clicks"] += clicks

        by_subj[subj_key]["sent"]   += 1
        by_subj[subj_key]["opens"]  += opens
        by_subj[subj_key]["clicks"] += clicks

    def enrich(d):
        for k, v in d.items():
            s = v["sent"]
            v["open_rate"]  = round(v["opens"]  / s * 100, 1) if s else 0
            v["click_rate"] = round(v["clicks"] / s * 100, 1) if s else 0
        return d

    return {"by_category": enrich(by_cat), "by_subject": enrich(by_subj)}


def _bar(pct: float, width: int = 20) -> str:
    filled = round(pct / 100 * width)
    return "█" * filled + "░" * (width - filled)


def print_report(analysis: dict, top: int = 0) -> None:
    by_cat  = analysis["by_category"]
    by_subj = analysis["by_subject"]

    print("\n" + "=" * 70)
    print("  WebByMaya — Email Performance by Category")
    print("=" * 70)

    cats = sorted(by_cat.items(), key=lambda x: -x[1]["open_rate"])
    if top:
        cats = cats[:top]

    print(f"\n{'Category':<26} {'Sent':>6} {'Opens':>6} {'OpenR%':>7} {'Clicks':>7} {'ClickR%':>8}  Bar (open %)")
    print("─" * 90)
    for cat, v in cats:
        if v["sent"] < 3:
            continue
        bar = _bar(v["open_rate"])
        print(
            f"  {cat:<24} {v['sent']:>6} {v['opens']:>6} {v['open_rate']:>6.1f}%"
            f" {v['clicks']:>7} {v['click_rate']:>7.1f}%  {bar}"
        )

    print("\n\n" + "=" * 70)
    print("  Top Subject Lines by Open Rate  (min 5 sends)")
    print("=" * 70)
    subjs = sorted(by_subj.items(), key=lambda x: -x[1]["open_rate"])
    print(f"\n{'Subject':<52} {'Sent':>6} {'OpenR%':>7} {'ClickR%':>8}")
    print("─" * 80)
    for subj, v in subjs:
        if v["sent"] < 5:
            continue
        print(f"  {subj[:50]:<50} {v['sent']:>6} {v['open_rate']:>6.1f}% {v['click_rate']:>7.1f}%")

    # Recommendations
    print("\n\n" + "═" * 70)
    print("  Recommendations")
    print("═" * 70)

    best_cats = [c for c, v in by_cat.items() if v["sent"] >= 10]
    if best_cats:
        best  = max(best_cats, key=lambda c: by_cat[c]["open_rate"])
        worst = min(best_cats, key=lambda c: by_cat[c]["open_rate"])
        print(f"\n  FOCUS:  {best}  →  {by_cat[best]['open_rate']:.1f}% open rate (highest)")
        print(f"  REVIEW: {worst}  →  {by_cat[worst]['open_rate']:.1f}% open rate (lowest)")

    print()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0,    help="Only include sends from last N days")
    ap.add_argument("--top",  type=int, default=0,    help="Show only top N categories")
    ap.add_argument("--no-api", action="store_true",  help="Skip SendGrid API (open/click data will be 0)")
    args = ap.parse_args()

    print(f"Loading send logs{'  (last ' + str(args.days) + ' days)' if args.days else ''}...")
    logs = load_send_logs(args.days)
    print(f"  {len(logs)} sent emails found.")

    sg_data = {}
    if not args.no_api:
        sg_key = get_sg_key()
        if sg_key:
            print("Fetching SendGrid activity data...")
            sg_data = fetch_sg_messages(sg_key)
            print(f"  {len(sg_data)} email records from SendGrid.")
        else:
            print("  [WARN] No SENDGRID_API_KEY — open/click rates will be 0. Set key or use --no-api.")

    analysis = analyze(logs, sg_data)
    print_report(analysis, top=args.top)


if __name__ == "__main__":
    main()
