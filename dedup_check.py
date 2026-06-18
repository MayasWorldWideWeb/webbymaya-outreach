#!/usr/bin/env python3
"""
dedup_check.py — Scan send logs + prospects CSVs for businesses contacted
more than once across zone passes. Prints a report and optionally writes
a dedup_flags.csv for dashboard review.

Usage:
    python dedup_check.py                # report only
    python dedup_check.py --write        # also write dedup_flags.csv
    python dedup_check.py --write --days 60   # only look back N days
"""
import csv
import argparse
from pathlib import Path
from collections import defaultdict
from datetime import datetime, timedelta

SCRIPT_DIR = Path(__file__).parent


def _iter_send_logs(days=None):
    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for path in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                date = row.get("date","")
                if cutoff and date and date < cutoff:
                    continue
                yield row


def _iter_prospects(days=None):
    cutoff = None
    if days:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    for path in sorted(SCRIPT_DIR.glob("prospects_*.csv")):
        date_tag = path.stem.replace("prospects_","")[:10]
        if cutoff and date_tag and date_tag < cutoff:
            continue
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                row.setdefault("source_date", date_tag)
                yield row


def _norm_phone(ph: str) -> str:
    return "".join(c for c in (ph or "") if c.isdigit())[-10:]


def _norm_email(em: str) -> str:
    return (em or "").strip().lower()


def run(days=None, write=False):
    by_phone: dict = defaultdict(list)   # phone → list of {date, name, source}
    by_email: dict = defaultdict(list)   # email → list of {date, name, source}

    # --- send logs ---
    for row in _iter_send_logs(days):
        ph  = _norm_phone(row.get("phone",""))
        em  = _norm_email(row.get("email",""))
        rec = {
            "date":     row.get("date",""),
            "name":     row.get("name",""),
            "category": row.get("category",""),
            "source":   "send_log",
        }
        if ph:
            by_phone[ph].append(rec)
        if em:
            by_email[em].append(rec)

    # --- enriched prospect files ---
    for row in _iter_prospects(days):
        ph  = _norm_phone(row.get("phone",""))
        em  = _norm_email(row.get("email",""))
        rec = {
            "date":     row.get("source_date",""),
            "name":     row.get("name","") or row.get("business_name",""),
            "category": row.get("category",""),
            "source":   "prospects",
        }
        if ph:
            by_phone[ph].append(rec)
        if em:
            by_email[em].append(rec)

    dup_phone = {ph: recs for ph, recs in by_phone.items() if len(recs) > 1 and ph}
    dup_email = {em: recs for em, recs in by_email.items() if len(recs) > 1 and em}

    # Merge by phone and email into unified list
    seen_keys = set()
    dupes = []
    for ph, recs in dup_phone.items():
        key = f"ph:{ph}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        first = recs[0]
        dates = sorted({r["date"] for r in recs if r["date"]})
        dupes.append({
            "match_type": "phone",
            "match_value": ph,
            "name": first.get("name",""),
            "category": first.get("category",""),
            "contact_count": len(recs),
            "first_date": dates[0] if dates else "",
            "last_date": dates[-1] if dates else "",
            "dates": ", ".join(dates),
        })

    for em, recs in dup_email.items():
        key = f"em:{em}"
        if key in seen_keys:
            continue
        seen_keys.add(key)
        first = recs[0]
        dates = sorted({r["date"] for r in recs if r["date"]})
        dupes.append({
            "match_type": "email",
            "match_value": em,
            "name": first.get("name",""),
            "category": first.get("category",""),
            "contact_count": len(recs),
            "first_date": dates[0] if dates else "",
            "last_date": dates[-1] if dates else "",
            "dates": ", ".join(dates),
        })

    dupes.sort(key=lambda d: -d["contact_count"])

    # Print report
    total_dups = len(dupes)
    print(f"\n{'='*60}")
    print(f"  WebByMaya Duplicate Contact Report")
    if days:
        print(f"  (last {days} days)")
    print(f"{'='*60}")
    if not dupes:
        print("  No duplicates found — clean!")
    else:
        print(f"  {total_dups} duplicate{'s' if total_dups != 1 else ''} found\n")
        for d in dupes[:50]:
            print(f"  [{d['contact_count']}x] {d['name'] or d['match_value']:<30}  ({d['match_type']}: {d['match_value']})")
            print(f"       Category: {d['category']}   First: {d['first_date']}   Last: {d['last_date']}")
        if total_dups > 50:
            print(f"  ... and {total_dups - 50} more")
    print(f"{'='*60}\n")

    if write and dupes:
        out = SCRIPT_DIR / "dedup_flags.csv"
        cols = ["match_type","match_value","name","category","contact_count","first_date","last_date","dates"]
        with open(out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(dupes)
        print(f"  Wrote {len(dupes)} rows to {out.name}")

    return dupes


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--days",  type=int, default=None, help="Only look back N days")
    ap.add_argument("--write", action="store_true",    help="Write dedup_flags.csv")
    args = ap.parse_args()
    run(days=args.days, write=args.write)
