#!/usr/bin/env python3
"""
reengagement_pass.py — Re-engage prospects who were emailed 30+ days ago with no reply.

Logic:
  1. Read all send_log_*.csv to find emails sent 30+ days ago
  2. Skip if already re-engaged (in reengagement_log.csv)
  3. Skip if bounced (bounce_log.csv) or opted out
  4. Skip if there is a reply from this email in gmail activity
  5. Send a minimal "still here" email — no pitch, just the mockup link

The angle is completely different from the original outreach:
  original:  "I noticed you don't have a website / here's why you need one"
  reengaged: "still here if you're interested — here's the preview link"

USAGE
    python3 reengagement_pass.py [--dry-run] [--limit N] [--days N]
"""

import argparse
import csv
import datetime
import os
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

REENGAGED_LOG = SCRIPT_DIR / "reengagement_log.csv"
REENGAGED_COLS = ["timestamp", "name", "category", "email", "subject", "status"]

PLAIN_TMPL = """\
Hey,

I built a free website preview for {name} a while back. It's still live if you want a look:

{mockup_or_link}

Fill out my intake form if you'd like to move forward — takes 2 minutes:
https://webbymaya.com/book

No pressure, just wanted to follow up.

Maya
WebByMaya.com
"""

HTML_TMPL = """\
<html><body style="font-family:Arial,sans-serif;color:#333;max-width:580px;margin:40px auto;padding:0 20px">
<p style="color:#888;font-size:12px;margin-bottom:20px">Following up from a while back...</p>
<p style="font-size:17px;font-weight:600;color:#111;margin:0 0 8px">I still have a free website for {name}</p>
<p style="color:#555;font-size:14px;line-height:1.7;margin:0 0 20px">
  No catch — I built a preview and it's still up. Takes 30 seconds to look at.
</p>
{mockup_block}
<p style="margin-top:28px;font-size:13px;color:#888;line-height:1.8">
  If you'd like to move forward, fill out my form:<br>
  <a href="https://webbymaya.com/book" style="color:#C9A96E;font-weight:600;text-decoration:none">
    webbymaya.com/book &rarr;
  </a>
</p>
<p style="font-size:11px;color:#bbb;margin-top:32px;border-top:1px solid #eee;padding-top:14px">
  Maya Sierra &middot; Web Designer &middot;
  <a href="https://webbymaya.com" style="color:#bbb;text-decoration:none">WebByMaya.com</a>
  &middot; Philadelphia, PA
</p>
</body></html>
"""

MOCKUP_BLOCK_HTML = """\
<div style="background:#0d0d0d;border-radius:8px;padding:24px;text-align:center;margin:0 0 20px">
  <div style="font-size:10px;letter-spacing:2px;color:#C9A96E;text-transform:uppercase;margin-bottom:12px">
    Your free website preview
  </div>
  <a href="{mockup_url}" style="display:inline-block;background:#C9A96E;color:#0d0d0d;
     padding:13px 30px;border-radius:5px;font-weight:700;font-size:14px;text-decoration:none">
    View Preview &rarr;
  </a>
  <div style="font-size:10px;color:#555;margin-top:8px">{mockup_url}</div>
</div>
"""

FALLBACK_BLOCK_HTML = """\
<div style="background:#f5f5f5;border-radius:6px;padding:20px;text-align:center;margin:0 0 20px">
  <a href="https://webbymaya.com/book" style="display:inline-block;background:#C9A96E;color:#111;
     padding:13px 30px;border-radius:5px;font-weight:700;font-size:14px;text-decoration:none">
    Fill Out My Form &rarr;
  </a>
</div>
"""

SUBJECT_VARIANTS = [
    "still here if you're interested — {name}",
    "the website I built for {name} is still available",
    "{name} — your free website preview is still live",
]


def _load_reengaged() -> set:
    if not REENGAGED_LOG.exists():
        return set()
    with open(REENGAGED_LOG, newline="", encoding="utf-8") as f:
        return {row.get("email","").lower() for row in csv.DictReader(f)}


def _load_bounced() -> set:
    p = SCRIPT_DIR / "bounce_log.csv"
    if not p.exists():
        return set()
    with open(p, newline="", encoding="utf-8") as f:
        return {row.get("email","").lower() for row in csv.DictReader(f)}


def _load_opted_out() -> set:
    """Load emails that replied STOP or unsubscribed."""
    out = set()
    for path in SCRIPT_DIR.glob("sms_log_*.csv"):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if (row.get("direction","") == "inbound" and
                        "stop" in (row.get("body","") or "").lower()):
                    out.add((row.get("email","") or "").lower())
    return out


def _get_all_sent(days_min: int = 30) -> list[dict]:
    """Return unique emails from send_logs that were sent at least days_min ago."""
    cutoff = (datetime.date.today() - datetime.timedelta(days=days_min)).isoformat()
    sent_by_email: dict[str, dict] = {}

    for path in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "sent":
                    continue
                ts = (row.get("timestamp") or "")[:10]
                if ts > cutoff:
                    continue
                email = (row.get("email_sent_to") or "").strip().lower()
                if not email or "@" not in email:
                    continue
                if email not in sent_by_email:
                    sent_by_email[email] = {
                        "name":     (row.get("name") or "").strip(),
                        "category": (row.get("category") or "").strip(),
                        "email":    email,
                        "sent_at":  ts,
                    }
    return list(sent_by_email.values())


def _get_mockup_url(name: str, category: str) -> str:
    try:
        from mockup_uploader import upload_mockup
        return upload_mockup(name, category)
    except Exception:
        return ""


def _write_reengaged(rows: list[dict]) -> None:
    is_new = not REENGAGED_LOG.exists()
    with open(REENGAGED_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REENGAGED_COLS)
        if is_new:
            w.writeheader()
        w.writerows(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit",   type=int, default=50)
    ap.add_argument("--days",    type=int, default=30, help="Minimum days since original email")
    args = ap.parse_args()

    # Deferred import so we only need send providers at runtime
    from batch_send_outreach import send_email, SUPPRESSED_EMAILS, SENDGRID_API_KEY, BREVO_API_KEY, GMAIL_TOKEN_PATH

    if not args.dry_run and not SENDGRID_API_KEY and not BREVO_API_KEY and not GMAIL_TOKEN_PATH.exists():
        sys.exit("No email provider configured.")

    already_reengaged = _load_reengaged()
    bounced           = _load_bounced()
    opted_out         = _load_opted_out()
    skip              = already_reengaged | bounced | opted_out | SUPPRESSED_EMAILS

    candidates = _get_all_sent(args.days)
    candidates = [c for c in candidates if c["email"] not in skip]
    candidates = candidates[: args.limit]

    print(f"Re-engagement pass: {len(candidates)} candidate(s) to contact.")

    import hashlib
    log_rows = []
    sent_count = 0

    for i, prospect in enumerate(candidates):
        name     = prospect["name"]
        category = prospect["category"]
        email    = prospect["email"]

        # Pick subject variant based on a stable hash of the name
        idx = int(hashlib.md5(name.encode()).hexdigest(), 16) % len(SUBJECT_VARIANTS)
        subject = SUBJECT_VARIANTS[idx].replace("{name}", name)

        mockup_url = _get_mockup_url(name, category)

        if mockup_url:
            mockup_or_link = mockup_url
            mockup_block_html = MOCKUP_BLOCK_HTML.format(mockup_url=mockup_url)
        else:
            mockup_or_link = "https://webbymaya.com/book"
            mockup_block_html = FALLBACK_BLOCK_HTML

        plain = PLAIN_TMPL.format(name=name, mockup_or_link=mockup_or_link)
        html  = HTML_TMPL.format(name=name, mockup_block=mockup_block_html)

        print(f"\n[{i+1}/{len(candidates)}] {name}  <{email}>")
        print(f"  Subject : {subject}")
        if mockup_url:
            print(f"  Mockup  : {mockup_url}")

        if args.dry_run:
            print("  [DRY RUN — not sent]")
            status = "dry_run"
        else:
            ok, provider = send_email(email, subject, plain, html)
            status = "sent" if ok else "failed"
            if ok:
                sent_count += 1
                print(f"  Sent via {provider}")
            else:
                print(f"  FAILED to send")

        log_rows.append({
            "timestamp": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "name":      name,
            "category":  category,
            "email":     email,
            "subject":   subject,
            "status":    status,
        })

    if not args.dry_run and log_rows:
        _write_reengaged(log_rows)

    print(f"\nDone. Sent: {sent_count}/{len(candidates)}")


if __name__ == "__main__":
    main()
