#!/usr/bin/env python3
"""
sync_bounces.py — Pull per-address hard bounces + blocked contacts from Brevo
and add them to the suppression list (bounce_log.csv).

Why this exists:
  reconcile_delivery.py only reads AGGREGATE bounce COUNTS, never which
  addresses bounced. Follow-ups now run on an unbounded monthly cadence
  (followup_send.py), so we MUST drop dead addresses or we'd email them
  forever. This closes the "until it's not a working email" half of the
  stop condition. The "until they say no" half is handled by auto_reply.py.

Sources per Brevo account (both keys):
  GET /v3/smtp/statistics/events?event=hard_bounce   → per-email hard bounces
  GET /v3/smtp/blockedContacts                        → blocked/unsub/complaint

Run standalone or from run_daily.sh (before followup_send.py). Safe: it only
ever APPENDS to the suppression list via add_suppression().

Usage:
  python3 sync_bounces.py            # sync last 30 days
  python3 sync_bounces.py --days 90
  python3 sync_bounces.py --dry-run  # show what would be suppressed
"""
import argparse, datetime, json, os, sys, urllib.parse, urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))
from auto_reply import add_suppression   # writes to bounce_log.csv


def _key(var: str) -> str:
    v = os.environ.get(var, "")
    if v:
        return v
    # cron may not export shell vars — fall back to ~/.zshrc
    try:
        for line in (Path.home() / ".zshrc").read_text().splitlines():
            if line.strip().startswith(f"export {var}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _get(url: str, key: str) -> dict:
    try:
        req = urllib.request.Request(
            url, headers={"api-key": key, "accept": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=30).read())
    except Exception as e:
        return {"_err": str(e)}


def _hard_bounces(key: str, start: str, end: str) -> set:
    """Per-email hard bounces from the transactional events log."""
    emails, offset = set(), 0
    while True:
        q = urllib.parse.urlencode({
            "event": "hardBounces", "startDate": start, "endDate": end,
            "limit": 100, "offset": offset, "sort": "desc"})
        data = _get(f"https://api.brevo.com/v3/smtp/statistics/events?{q}", key)
        if data.get("_err"):
            print(f"    events error: {data['_err']}")
            break
        events = data.get("events", []) or []
        for ev in events:
            em = (ev.get("email") or "").strip().lower()
            if em:
                emails.add(em)
        if len(events) < 100:
            break
        offset += 100
        if offset > 50000:      # safety
            break
    return emails


def _blocked(key: str) -> set:
    """Blocked / unsubscribed / complaint contacts."""
    emails, offset = set(), 0
    while True:
        q = urllib.parse.urlencode({"limit": 100, "offset": offset})
        data = _get(f"https://api.brevo.com/v3/smtp/blockedContacts?{q}", key)
        if data.get("_err"):
            print(f"    blocked error: {data['_err']}")
            break
        contacts = data.get("contacts", []) or []
        for c in contacts:
            em = (c.get("email") or "").strip().lower()
            if em:
                emails.add(em)
        if len(contacts) < 100:
            break
        offset += 100
        if offset > 50000:
            break
    return emails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    today = datetime.date.today()
    start = (today - datetime.timedelta(days=args.days)).isoformat()
    end = today.isoformat()

    # already-suppressed, so we only report NEW additions
    existing = set()
    bl = SCRIPT_DIR / "bounce_log.csv"
    if bl.exists():
        import csv
        for r in csv.DictReader(open(bl, newline="", encoding="utf-8")):
            e = (r.get("email") or "").strip().lower()
            if e:
                existing.add(e)

    all_bounced, all_blocked = set(), set()
    for var in ("BREVO_API_KEY", "BREVO_API_KEY_2"):
        key = _key(var)
        if not key:
            print(f"  {var}: not set — skipping")
            continue
        print(f"  {var}: fetching hard bounces ({args.days}d) + blocked …")
        all_bounced |= _hard_bounces(key, start, end)
        all_blocked |= _blocked(key)

    hard = {("hard_bounce", e) for e in all_bounced}
    blk = {("blocked", e) for e in all_blocked}
    new = [(reason, e) for reason, e in (hard | blk) if e not in existing]

    print(f"\n  Hard bounces found : {len(all_bounced)}")
    print(f"  Blocked contacts   : {len(all_blocked)}")
    print(f"  New to suppress    : {len(new)}")

    if args.dry_run:
        for reason, e in sorted(new, key=lambda x: x[1])[:50]:
            print(f"    [{reason}] {e}")
        if len(new) > 50:
            print(f"    … +{len(new) - 50} more")
        print("\n  (Dry run — nothing written)")
        return

    for reason, e in new:
        add_suppression(email=e, reason=reason)
    print(f"  → {len(new)} addresses added to bounce_log.csv suppression list")


if __name__ == "__main__":
    main()
