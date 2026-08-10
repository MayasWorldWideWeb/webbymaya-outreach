#!/usr/bin/env python3
"""click_rate.py — report a real open/click rate.

Denominator: tracking_sends.json (count of first-touch emails sent WITH a
tracked preview link, recorded per day by batch_send_outreach._record_tracking_send).
Numerator:    clicker_cache.json (per-recipient opens/clicks, bot-flagged).

Usage:  python3 click_rate.py            # all-time
        python3 click_rate.py --days 7   # last 7 days of *sends* in the rate
"""
import argparse, datetime, json
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SENDS_FILE = Path.home() / ".webbymaaya/tracking_sends.json"
CACHE_FILE = SCRIPT_DIR / "clicker_cache.json"


def _load(p, default):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=0, help="limit sends to last N days (0 = all)")
    args = ap.parse_args()

    sends = _load(SENDS_FILE, {})
    cache = _load(CACHE_FILE, {})

    if args.days > 0:
        cutoff = datetime.date.today() - datetime.timedelta(days=args.days - 1)
        sends = {d: n for d, n in sends.items()
                 if d >= cutoff.isoformat()}

    total_sends = sum(int(n) for n in sends.values())
    span = f"{min(sends)} → {max(sends)}" if sends else "no tracked sends recorded yet"

    humans = {e: v for e, v in cache.items() if not v.get("likely_bot")}
    clickers = sum(1 for v in humans.values() if v.get("clicks", 0) > 0)
    openers  = sum(1 for v in humans.values() if v.get("opens", 0) > 0)
    total_clicks = sum(v.get("clicks", 0) for v in humans.values())
    bots = sum(1 for v in cache.values() if v.get("likely_bot"))

    print("=" * 48)
    print("  WebByMaya — Email Engagement")
    print("=" * 48)
    print(f"  Tracked sends:        {total_sends}   ({span})")
    print(f"  Distinct human opens: {openers}")
    print(f"  Distinct human clicks:{clickers}")
    print(f"  Total clicks:         {total_clicks}")
    print(f"  Bots filtered out:    {bots}")
    if total_sends:
        print("-" * 48)
        print(f"  OPEN RATE:  {100*openers/total_sends:5.1f}%   ({openers}/{total_sends})")
        print(f"  CLICK RATE: {100*clickers/total_sends:5.1f}%   ({clickers}/{total_sends})")
    else:
        print("-" * 48)
        print("  Rate unavailable — denominator starts accumulating on the")
        print("  next batch send (tracking_sends.json is empty).")
    print("=" * 48)
    print("  Note: clicker_cache is cumulative; the rate is accurate once")
    print("  tracked sends cover the same period as the recorded clicks.")


if __name__ == "__main__":
    main()
