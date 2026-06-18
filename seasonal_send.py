#!/usr/bin/env python3
"""
seasonal_send.py — Time-sensitive campaign emails tied to upcoming holidays/events.
Targets specific business categories with a relevant hook 2–4 weeks before the date.

Usage:
    python seasonal_send.py                # check + send today's applicable campaigns
    python seasonal_send.py --dry-run      # preview what would be sent
    python seasonal_send.py --campaign valentine  # force a specific campaign
    python seasonal_send.py --limit 100    # cap at N sends

Logs to: seasonal_log_YYYY_MM_DD.csv
"""
import argparse
import csv
import hashlib
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

from batch_send_outreach import send_email
SITE_PRICE = 799

# ── Campaign definitions ────────────────────────────────────────────────────────
# Each campaign: name, month, day (of the holiday), lead_days window (start, end),
# target categories, subject, plain body, HTML body

_CAMPAIGNS = [
    {
        "name": "valentine",
        "label": "Valentine's Day",
        "month": 2, "day": 14,
        "lead_days": (7, 21),       # send 7–21 days before
        "categories": [
            "florist", "nail salon", "hair salon", "spa", "massage",
            "beauty salon", "gift shop", "chocolatier", "bakery", "restaurant",
        ],
        "subject": "Valentine's Day is coming — does {name} have a website?",
        "plain": """\
Valentine's Day is one of the biggest spending days of the year — and customers \
are searching online right now for a place to book.

I built a free mockup website for {name}. No obligation, no catch — I just want \
you to see what's possible before the holiday rush hits.

Reply "show me" and I'll send it over in minutes.

— Maya, WebByMaya
webbymaya.com
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  <strong>Valentine's Day is one of the biggest spending days of the year</strong> — \
  and customers are searching online <em>right now</em> for places to book.
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  I built a free mockup website for <strong style="color:#C9A96E">{name}</strong>. \
  No obligation, no catch — I just want you to see what's possible before the holiday rush hits.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "show me" to get your free mockup
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
    {
        "name": "mothers_day",
        "label": "Mother's Day",
        "month": 5, "day": 11,     # 2nd Sunday; approximate with May 11
        "lead_days": (7, 21),
        "categories": [
            "florist", "nail salon", "hair salon", "spa", "massage",
            "beauty salon", "gift shop", "bakery", "restaurant", "jewelry",
        ],
        "subject": "Mother's Day bookings start NOW — is {name} ready?",
        "plain": """\
Mother's Day is coming up fast — and moms across Philly are already looking for \
the perfect gift, spa day, or dinner reservation.

Businesses with a website get booked first. I put together a free site for \
{name} that you can have live before the weekend rush.

Just reply "yes" and I'll send the mockup right now.

— Maya, WebByMaya
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  Mother's Day is coming up fast — and moms across Philly are already looking \
  for the perfect gift, spa day, or dinner reservation.
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  Businesses with a website get booked first. I put together a <strong style="color:#C9A96E">free site for {name}</strong> \
  that you can have live before the weekend rush.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "yes" — I'll send the mockup now
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
    {
        "name": "summer",
        "label": "Summer Season",
        "month": 6, "day": 1,
        "lead_days": (0, 91),   # covers all of June, July, August
        "categories": [
            "restaurant", "bar", "cafe", "food truck", "catering",
            "hair salon", "nail salon", "barbershop", "outdoor fitness",
        ],
        "subject": "Summer is here — does {name} come up when people search?",
        "plain": """\
Summer foot traffic is the biggest opportunity of the year for local businesses — \
but only if people can find you online.

I built a free website mockup for {name}. Takes 2 minutes to look at, \
could bring in bookings all summer long.

Reply "show me" and I'll send it over.

— Maya, WebByMaya
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  Summer foot traffic is the biggest opportunity of the year for local businesses — \
  but only if people can <strong>find you online</strong>.
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  I built a free website mockup for <strong style="color:#C9A96E">{name}</strong>. \
  Takes 2 minutes to look at, could bring in bookings all summer long.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "show me" to get your free mockup
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
    {
        "name": "back_to_school",
        "label": "Back to School",
        "month": 8, "day": 25,
        "lead_days": (7, 28),
        "categories": [
            "tutoring", "education", "barber", "barbershop", "hair salon",
            "nail salon", "uniform shop", "shoe store",
        ],
        "subject": "Back-to-school rush is weeks away — is {name} online?",
        "plain": """\
Back-to-school season is one of the busiest times of year — parents are searching \
online for everything from haircuts to tutors to supplies.

I built a free website mockup for {name} so you can be ready when the rush hits. \
No cost, no commitment.

Just reply "show me" and I'll send it over.

— Maya, WebByMaya
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  Back-to-school season is one of the busiest times of year — parents are searching \
  online for everything from haircuts to tutors to supplies.
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  I built a free website mockup for <strong style="color:#C9A96E">{name}</strong> \
  so you can be ready when the rush hits. No cost, no commitment.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "show me" to get your free mockup
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
    {
        "name": "holiday",
        "label": "Holiday Season",
        "month": 12, "day": 25,
        "lead_days": (21, 60),
        "categories": [
            "gift shop", "florist", "bakery", "restaurant", "hair salon",
            "nail salon", "spa", "massage", "jeweler", "boutique",
            "clothing store", "toy store",
        ],
        "subject": "Holiday shoppers are searching — does {name} show up?",
        "plain": """\
The holiday season is the biggest revenue window of the year — and people are \
already searching Google for local gifts, bookings, and experiences.

I built a free website mockup for {name}. Takes seconds to view, \
could make all the difference this December.

Reply "show me" and I'll send it right now.

— Maya, WebByMaya
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  The holiday season is the <strong>biggest revenue window of the year</strong> — \
  and people are already searching Google for local gifts, bookings, and experiences.
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  I built a free website mockup for <strong style="color:#C9A96E">{name}</strong>. \
  Takes seconds to view, could make all the difference this December.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "show me" to get your free mockup
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
    {
        "name": "new_year",
        "label": "New Year",
        "month": 1, "day": 1,
        "lead_days": (3, 21),
        "categories": [
            "gym", "fitness", "personal trainer", "health food", "yoga",
            "wellness", "nutrition", "spa", "massage", "dentist",
        ],
        "subject": "New Year resolution traffic is coming — is {name} ready?",
        "plain": """\
Every January, people flood search results looking for gyms, trainers, wellness \
spots, and health services. The businesses with websites get the calls.

I built a free mockup for {name}. No cost, no pressure — just a look.

Reply "show me" and I'll send it over.

— Maya, WebByMaya
""",
        "html": """\
<!DOCTYPE html><html><body style="background:#0a0a0a;color:#d8d8d8;font-family:Arial,sans-serif;padding:32px 24px;max-width:600px;margin:0 auto">
<p style="font-size:15px;line-height:1.7">
  Every January, people flood search results looking for gyms, trainers, wellness spots, \
  and health services. <strong>The businesses with websites get the calls.</strong>
</p>
<p style="font-size:15px;line-height:1.7;margin-top:16px">
  I built a free mockup for <strong style="color:#C9A96E">{name}</strong>. \
  No cost, no pressure — just a look.
</p>
<div style="margin:28px 0;text-align:center">
  <a href="https://webbymaya.com/book" style="background:#C9A96E;color:#000;padding:14px 32px;border-radius:6px;font-weight:700;text-decoration:none;font-size:15px">
    Reply "show me" to get your free mockup
  </a>
</div>
<p style="color:#666;font-size:12px;margin-top:32px">— Maya &nbsp;·&nbsp; <a href="https://webbymaya.com" style="color:#C9A96E">webbymaya.com</a></p>
<p style="color:#333;font-size:10px;margin-top:24px">To opt out reply STOP.</p>
</body></html>
""",
    },
]


# ── Helpers ─────────────────────────────────────────────────────────────────────

def _active_campaigns(today: date, force: str = None) -> list:
    """Return campaigns that are active today (within their lead window)."""
    active = []
    for c in _CAMPAIGNS:
        if force and c["name"] != force:
            continue
        yr = today.year
        lo, hi = c["lead_days"]

        # Check both this year's and last year's holiday date so campaigns
        # that span the date (lead_days start=0) remain active after the date.
        for check_yr in (yr, yr - 1, yr + 1):
            try:
                holiday = date(check_yr, c["month"], c["day"])
            except ValueError:
                continue
            days_until = (holiday - today).days
            # days_until < 0 means holiday already passed; abs() gives days since
            days_since = -days_until
            # Active if we're in the pre-holiday window OR in the post-holiday window
            if lo <= days_until <= hi:          # pre-holiday window
                active.append((c, days_until))
                break
            if lo == 0 and 0 <= days_since <= hi:  # post-holiday window (season)
                active.append((c, days_since))
                break
    return active


def _load_send_logs() -> set:
    """Return set of emails already in any send_log CSV."""
    sent = set()
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                em = (row.get("email") or "").strip().lower()
                if em:
                    sent.add(em)
    return sent


def _load_seasonal_log() -> set:
    """Emails already reached by any seasonal campaign."""
    sent = set()
    for p in sorted(SCRIPT_DIR.glob("seasonal_log_*.csv")):
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                em = (row.get("email") or "").strip().lower()
                if em:
                    sent.add(em)
    return sent


def _load_opt_outs() -> set:
    out = set()
    p = SCRIPT_DIR / "opt_outs.csv"
    if not p.exists():
        return out
    with open(p, newline="", encoding="utf-8", errors="replace") as f:
        for row in csv.DictReader(f):
            v = (row.get("phone") or row.get("email") or "").strip().lower()
            if v:
                out.add(v)
    return out


def _load_all_leads() -> list:
    """Load enriched prospect CSVs (most recent first)."""
    leads = []
    seen_emails = set()
    for p in sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv"), reverse=True):
        with open(p, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                em = (row.get("email") or "").strip().lower()
                if em and em not in seen_emails:
                    seen_emails.add(em)
                    leads.append(row)
    return leads


def _cat_match(row_cat: str, target_cats: list) -> bool:
    rc = row_cat.strip().lower()
    for tc in target_cats:
        if tc in rc or rc in tc:
            return True
    return False


def _log_seasonal(name, email, category, campaign_name, dry_run):
    today = datetime.now().strftime("%Y-%m-%d")
    path  = SCRIPT_DIR / f"seasonal_log_{today}.csv"
    is_new = not path.exists()
    prefix = "[DRY RUN] " if dry_run else ""
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["date","name","email","category","campaign","dry_run"])
        if is_new:
            w.writeheader()
        w.writerow({"date": today, "name": name, "email": email,
                    "category": category, "campaign": campaign_name,
                    "dry_run": "1" if dry_run else "0"})


# ── Main ─────────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run",   action="store_true")
    ap.add_argument("--campaign",  default=None, help="Force a specific campaign name")
    ap.add_argument("--limit",     type=int, default=200)
    args = ap.parse_args()

    today    = date.today()
    active   = _active_campaigns(today, force=args.campaign)

    if not active:
        print(f"[seasonal] No active campaigns for {today}.")
        return

    already_sent     = _load_send_logs()
    already_seasonal = _load_seasonal_log()
    opt_outs         = _load_opt_outs()
    leads            = _load_all_leads()

    skip = already_sent | already_seasonal | opt_outs
    total_sent = 0

    for campaign, days_until in active:
        print(f"\n[seasonal] Campaign: {campaign['label']} — {days_until} days away")
        targets = [
            l for l in leads
            if _cat_match(l.get("category",""), campaign["categories"])
            and (l.get("email","") or "").strip().lower() not in skip
            and (l.get("email","") or "").strip()
        ]
        print(f"[seasonal] {len(targets)} eligible leads for {campaign['label']}")

        for lead in targets:
            if total_sent >= args.limit:
                print(f"[seasonal] Hit limit ({args.limit}) — stopping.")
                return

            name     = lead.get("name","") or lead.get("business_name","")
            email    = (lead.get("email","") or "").strip()
            category = lead.get("category","")

            subject  = campaign["subject"].format(name=name)
            plain    = campaign["plain"].format(name=name, category=category)
            html     = campaign["html"].format(name=name, category=category)

            if args.dry_run:
                print(f"  [DRY] → {email} | {name} | {subject}")
                _log_seasonal(name, email, category, campaign["name"], dry_run=True)
                skip.add(email.lower())
                total_sent += 1
                continue

            ok = send_email(email, subject, plain, html)
            status = "sent" if ok else "failed"
            print(f"  [{status}] → {email} | {name}")
            if ok:
                _log_seasonal(name, email, category, campaign["name"], dry_run=False)
                skip.add(email.lower())
                total_sent += 1

    print(f"\n[seasonal] Done — {total_sent} emails {'(dry run)' if args.dry_run else 'sent'}.")


if __name__ == "__main__":
    main()
