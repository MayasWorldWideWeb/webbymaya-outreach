#!/usr/bin/env python3
"""
clicker_second_touch.py — WebByMaya second-touch to warm clickers.

Someone who clicked their mockup preview but didn't buy is your warmest lead.
They already got ONE follow-up (clicker_followups.py). Once it's been 15+ days
and they still haven't bought, send ONE more — this time leading with the NEW
one-click checkout button (a genuine reason to reach back out, not a nag).

Guardrails (so this never spams the enrichment-mismatch bots that "click"):
  • 15-day gate since their FIRST clicker follow-up (--days to change)
  • runs every email through _email_belongs_to_biz (kills alexanderwang/github/etc.)
  • skips anyone suppressed / opted-out (bounce_log.csv)
  • one-and-done: logged in clicker_second_touch_log_*.csv, never re-sent

Runs daily from run_daily.sh. Safe to re-run.

    python3 clicker_second_touch.py --dry-run
    python3 clicker_second_touch.py --limit 20
"""
import argparse, csv, datetime, glob
from pathlib import Path

import offer
from enrich_emails import _email_belongs_to_biz
from clicker_followups import send_email, load_suppressed
from mockup_uploader import _token_slug, GITHUB_PAGES_BASE

SCRIPT_DIR = Path(__file__).parent
DEFAULT_DAYS = 15


def _first_touch_by_email() -> dict:
    """email -> (earliest_first_touch_date, business_name) from clicker follow-up logs."""
    first = {}
    for f in sorted(SCRIPT_DIR.glob("clicker_followup_log_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
            e = (r.get("email") or "").strip().lower()
            if not e:
                continue
            ds = (r.get("timestamp") or "")[:10]
            try:
                d = datetime.date.fromisoformat(ds)
            except ValueError:
                continue
            if e not in first or d < first[e][0]:
                first[e] = (d, r.get("name", ""))
    return first


def _already_second_touched() -> set:
    done = set()
    for f in sorted(SCRIPT_DIR.glob("clicker_second_touch_log_*.csv")):
        for r in csv.DictReader(open(f, encoding="utf-8", errors="replace")):
            e = (r.get("email") or "").strip().lower()
            if e:
                done.add(e)
    return done


def _preview_url(name: str) -> str:
    """Deterministic published-preview URL for this business."""
    return f"{GITHUB_PAGES_BASE}/{_token_slug(name)}.html"


def _build_email(name: str, email: str):
    preview = _preview_url(name)
    subj = f"You can now get {name}'s site live in one click"
    plain = (
        f"Hi {name} team,\n\n"
        f"A little while back you checked out the website preview I built for {name} — "
        f"just wanted to reach back out because something's changed that makes this easier.\n\n"
        f"You can now get your site live in ONE click — no back-and-forth, no calls. "
        f"Here's your preview, with a \"Get This Site Live\" button right on it:\n\n"
        f"{preview}\n\n"
        f"It's {offer.PRICE} to build, and that includes a free domain + your first year of "
        f"hosting, SSL & full setup — live in 7 days. After year one, hosting & maintenance is "
        f"just {offer.MONTHLY}. Or go straight to checkout: {offer.CHECKOUT_URL}\n\n"
        f"If it's not the right time, no worries at all — just reply \"stop\" and I won't reach out again.\n\n"
        f"— Maya\nWebByMaya.com\n{offer.BUSINESS_ADDRESS}"
    )
    html = (
        f'<div style="font-family:Arial,sans-serif;color:#333;max-width:600px;line-height:1.6">'
        f'<p>Hi <strong>{name}</strong> team,</p>'
        f'<p>A little while back you checked out the website preview I built for '
        f'<strong>{name}</strong> — wanted to reach back out because something changed that '
        f'makes this easier.</p>'
        f'<p>You can now get your site live in <strong>one click</strong> — no back-and-forth, '
        f'no calls. Here\'s your preview with a "Get This Site Live" button right on it:</p>'
        f'<p><a href="{preview}" style="background:#0d0d0d;color:#fff;padding:12px 24px;'
        f'text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">'
        f'See your site &rarr;</a> &nbsp; '
        f'<a href="{offer.CHECKOUT_URL}" style="background:#C9A96E;color:#0d0d0d;padding:12px 24px;'
        f'text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">'
        f'Get it live — {offer.PRICE} &rarr;</a></p>'
        f'<p>{offer.PRICE} to build, including a <strong>free domain + your first year of '
        f'hosting</strong>, SSL &amp; full setup — live in 7 days. After year one, hosting &amp; '
        f'maintenance is just {offer.MONTHLY}.</p>'
        f'<p style="color:#888;font-size:13px">Not the right time? Just reply "stop" and I won\'t '
        f'reach out again.</p>'
        f'<p>— Maya<br><a href="https://webbymaya.com">WebByMaya.com</a></p>'
        f'<p style="color:#999;font-size:12px">{offer.BUSINESS_ADDRESS}</p></div>'
    )
    return subj, plain, html


def _log_send(email: str, name: str):
    today = datetime.date.today().isoformat()
    path = SCRIPT_DIR / f"clicker_second_touch_log_{today}.csv"
    new = not path.exists()
    with open(path, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["timestamp", "email", "name", "status"])
        w.writerow([datetime.datetime.now().isoformat(timespec="seconds"), email, name, "sent_second_touch"])


def main():
    ap = argparse.ArgumentParser(description="WebByMaya — second touch to warm clickers (15-day gate)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    args = ap.parse_args()

    today = datetime.date.today()
    first = _first_touch_by_email()
    done = _already_second_touched()
    suppressed = load_suppressed()

    eligible = []
    for e, (d, n) in first.items():
        if (today - d).days < args.days:      # not old enough yet
            continue
        if e in done:                          # already second-touched
            continue
        if e in suppressed:                    # opted out / bounced
            continue
        if not _email_belongs_to_biz(e, n):    # bot / enrichment mismatch
            continue
        eligible.append((e, n, d))

    eligible.sort(key=lambda x: x[2])          # oldest first
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}Clicker second-touch — {today}")
    print(f"Eligible (>= {args.days}d, real, not yet second-touched): {len(eligible)}")
    print(f"Will send: {min(len(eligible), args.limit)}\n")

    sent = 0
    for e, n, d in eligible[:args.limit]:
        subj, plain, html = _build_email(n, e)
        age = (today - d).days
        if args.dry_run:
            print(f"  [DRY RUN] would send → {n} <{e}>  ({age}d since first touch)")
            continue
        ok = send_email(e, subj, plain, html)
        if ok:
            _log_send(e, n)
            sent += 1
            print(f"  Sent → {n} <{e}>  ({age}d)")
        else:
            print(f"  FAILED → {n} <{e}>")

    print(f"\nDone — {sent} second-touch email(s) sent.")


if __name__ == "__main__":
    main()
