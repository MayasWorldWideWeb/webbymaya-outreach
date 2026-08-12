#!/usr/bin/env python3
"""click_rate.py — report a real open/click rate.

Sources, deliberately chosen so this works no matter WHERE the send ran:

  Sent       Supabase email_log — every send writes here via sb.log_email,
             from Maya's Mac and from the GitHub Actions runner alike.
  Engagement Brevo's aggregated report, across both accounts. Brevo is the
             system of record for delivered/opens/clicks/bounces; it counts
             what actually happened rather than what we logged as attempted.

It used to read ~/.webbymaaya/tracking_sends.json for the denominator, a local
file incremented by batch_send_outreach._record_tracking_send. Cold acquisition
moved to GitHub Actions on 2026-08-09; the runner increments its own copy and
discards it at the end of the job, so that file froze on 08-09 and every rate
computed from it has been wrong since. Nothing local can measure a cloud send.

Usage:  python3 click_rate.py             # last 14 days
        python3 click_rate.py --days 30
        python3 click_rate.py --by-day
"""
import argparse
import collections
import datetime
import json
import os
import subprocess
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
CACHE_FILE = SCRIPT_DIR / "clicker_cache.json"

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
SUPABASE_ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1"
    "emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5"
    "NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
)


def _brevo_keys() -> list:
    keys = [os.environ.get("BREVO_API_KEY", ""), os.environ.get("BREVO_API_KEY_2", "")]
    if not any(keys):  # not run from run_daily.sh — read the shell profile
        try:
            txt = Path.home().joinpath(".zshrc").read_text()
            for name in ("BREVO_API_KEY=", "BREVO_API_KEY_2="):
                for line in txt.splitlines():
                    if line.startswith(f"export {name}"):
                        keys.append(line.split('"')[1])
        except Exception:
            pass
    return [k for k in keys if k]


def sent_by_day(start: str, end: str) -> dict:
    """{date: count} of sends Supabase recorded, wherever they ran."""
    out = collections.Counter()
    url = (f"{SUPABASE_URL}/rest/v1/email_log?select=sent_at,status"
           f"&status=eq.sent&sent_at=gte.{start}T00:00:00Z&sent_at=lte.{end}T23:59:59Z&limit=10000")
    req = urllib.request.Request(
        url, headers={"apikey": SUPABASE_ANON, "Authorization": f"Bearer {SUPABASE_ANON}"})
    try:
        for r in json.loads(urllib.request.urlopen(req, timeout=25).read()):
            out[(r.get("sent_at") or "")[:10]] += 1
    except Exception as e:
        print(f"  [warn] could not read email_log: {str(e)[:90]}")
    return dict(out)


def engagement(start: str, end: str) -> dict:
    """Brevo's own numbers, summed across accounts."""
    total = collections.Counter()
    for key in _brevo_keys():
        url = (f"https://api.brevo.com/v3/smtp/statistics/aggregatedReport"
               f"?startDate={start}&endDate={end}")
        try:
            out = subprocess.run(
                ["curl", "-s", "-H", f"api-key: {key}", "-H", "accept: application/json", url],
                capture_output=True, text=True, timeout=40).stdout
            d = json.loads(out)
            for f in ("requests", "delivered", "hardBounces", "softBounces",
                      "uniqueOpens", "uniqueClicks", "spamReports", "unsubscribed"):
                total[f] += int(d.get(f, 0) or 0)
        except Exception as e:
            print(f"  [warn] Brevo report: {str(e)[:80]}")
    return dict(total)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--by-day", action="store_true", help="also print a per-day send table")
    a = ap.parse_args()

    end = datetime.date.today()
    start = end - datetime.timedelta(days=a.days - 1)
    s, e = start.isoformat(), end.isoformat()

    sends = sent_by_day(s, e)
    eng = engagement(s, e)

    total_sent = sum(sends.values())
    delivered = eng.get("delivered", 0)
    requests_ = eng.get("requests", 0)
    opens = eng.get("uniqueOpens", 0)
    clicks = eng.get("uniqueClicks", 0)
    hard = eng.get("hardBounces", 0)
    spam = eng.get("spamReports", 0)

    print("=" * 56)
    print(f"  WebByMaya — Email Engagement   ({s} → {e})")
    print("=" * 56)
    print(f"  Logged sent (Supabase):  {total_sent}")
    print(f"  Provider requests:       {requests_}")
    print(f"  Delivered:               {delivered}"
          + (f"   ({100*delivered/requests_:.1f}%)" if requests_ else ""))
    print(f"  Hard bounces:            {hard}"
          + (f"   ({100*hard/requests_:.1f}%)" if requests_ else ""))
    print(f"  Spam complaints:         {spam}")
    print("-" * 56)
    if delivered:
        print(f"  OPEN RATE:   {100*opens/delivered:5.1f}%   ({opens}/{delivered} delivered)")
        print(f"  CLICK RATE:  {100*clicks/delivered:5.1f}%   ({clicks}/{delivered} delivered)")
    else:
        print("  No delivered mail in this window — nothing to rate.")

    # A human who clicks has almost always opened first, and most opens never
    # become clicks. Clicks tracking opens 1:1 is the signature of a security
    # gateway fetching every URL in the message, not of interest.
    if opens and clicks >= opens * 0.8:
        print()
        print(f"  ⚠️  {clicks} clicks against {opens} opens — near 1:1.")
        print("      That pattern is scanners pre-fetching links, not readers.")
        print("      Treat this engagement as close to zero.")

    if a.by_day and sends:
        print("-" * 56)
        for day in sorted(sends):
            print(f"  {day}   {sends[day]:>4} sent")

    # Secondary view: the bot-filtered per-person cache the follow-up scripts use.
    try:
        cache = json.loads(CACHE_FILE.read_text())
        humans = {k: v for k, v in cache.items() if not v.get("likely_bot")}
        clickers = sum(1 for v in humans.values() if v.get("clicks", 0) > 0)
        print("-" * 56)
        print(f"  Cumulative bot-filtered clickers on file: {clickers}"
              f"  ({len(cache) - len(humans)} flagged as bots)")
    except Exception:
        pass
    print("=" * 56)


if __name__ == "__main__":
    main()
