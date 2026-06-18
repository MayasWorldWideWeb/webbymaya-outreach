#!/usr/bin/env python3
"""
weekly_summary.py — WebByMaya Monday Morning Report
Emails Maya a weekly digest: what was sent, replies, zones left.
Runs automatically every Monday at 8 AM via launchd.
"""
import csv
import json
import os
import urllib.request
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
TO_EMAIL     = "mayas.worldwide.web@gmail.com"
FROM_EMAIL   = "maya@webbymaya.com"
FROM_NAME    = "WebByMaya"
SENDGRID_KEY = os.environ.get("SENDGRID_API_KEY", "")


def load_all(pattern):
    rows = []
    for p in sorted(SCRIPT_DIR.glob(pattern)):
        with open(p, newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def send_email(subject: str, plain: str, html: str):
    if not SENDGRID_KEY:
        print("SENDGRID_API_KEY not set — skipping weekly email")
        return
    payload = json.dumps({
        "personalizations": [{"to": [{"email": TO_EMAIL}]}],
        "from": {"email": FROM_EMAIL, "name": FROM_NAME},
        "subject": subject,
        "content": [
            {"type": "text/plain", "value": plain},
            {"type": "text/html",  "value": html},
        ],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={"Authorization": f"Bearer {SENDGRID_KEY}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        urllib.request.urlopen(req)
        print("Weekly summary emailed.")
    except urllib.error.HTTPError as e:
        print(f"SendGrid error {e.code}: {e.read().decode()}")


def main():
    today    = date.today()
    week_ago = (today - timedelta(days=7)).isoformat()

    send_logs     = load_all("send_log_*.csv")
    sms_logs      = load_all("sms_log_*.csv")
    followup_logs = load_all("email_followup_log_*.csv")
    bounces       = load_all("bounce_log.csv") if (SCRIPT_DIR / "bounce_log.csv").exists() else []

    # This week
    emails_wk  = sum(1 for r in send_logs if r.get("status") == "sent" and r.get("timestamp", "")[:10] >= week_ago)
    sms_wk     = sum(1 for r in sms_logs  if r.get("status") == "sent" and r.get("timestamp", "")[:10] >= week_ago)
    fu_wk      = sum(1 for r in followup_logs if r.get("status") == "sent" and r.get("timestamp", "")[:10] >= week_ago)

    # All time
    emails_all = sum(1 for r in send_logs if r.get("status") == "sent")
    sms_all    = sum(1 for r in sms_logs  if r.get("status") == "sent")
    fu_all     = sum(1 for r in followup_logs if r.get("status") == "sent")

    # Zone progress
    zone_state = SCRIPT_DIR / "zone_state.json"
    zones_done = zones_total = zones_left = 0
    next_zone  = "—"
    if zone_state.exists():
        z = json.loads(zone_state.read_text())
        idx         = z.get("current_index", 0)
        all_zones   = z.get("zones", [])
        zones_total = len(all_zones)
        zones_done  = idx
        zones_left  = zones_total - idx
        next_zone   = all_zones[idx] if idx < zones_total else "all done"

    bounce_rate = len(bounces) / emails_all * 100 if emails_all else 0

    subject = f"WebByMaya Weekly — {today.strftime('%b %d')}"

    plain = f"""WebByMaya Weekly Report
Week ending {today.strftime('%B %d, %Y')}

THIS WEEK
  Emails sent:      {emails_wk}
  SMS sent:         {sms_wk}
  Follow-ups sent:  {fu_wk}

ALL TIME
  Total emails:     {emails_all}
  Total SMS:        {sms_all}
  Total follow-ups: {fu_all}
  Bounce rate:      {bounce_rate:.1f}%

PIPELINE
  Zones done:  {zones_done} / {zones_total}
  Zones left:  {zones_left}
  Next zone:   {next_zone}

Run wm-replies to check for responses.
"""

    html = f"""<html><body style="font-family:Arial,sans-serif;color:#333;max-width:560px;margin:auto;padding:20px">
<h2 style="margin-bottom:4px">WebByMaya Weekly Report</h2>
<p style="color:#888;margin-top:0">Week ending {today.strftime('%B %d, %Y')}</p>

<table style="width:100%;border-collapse:collapse;margin:16px 0">
  <tr style="background:#f5f5f5"><td colspan="2" style="padding:8px 12px;font-weight:bold">THIS WEEK</td></tr>
  <tr><td style="padding:6px 12px;color:#666">Emails sent</td><td style="padding:6px 12px"><b>{emails_wk}</b></td></tr>
  <tr style="background:#f9f9f9"><td style="padding:6px 12px;color:#666">SMS sent</td><td style="padding:6px 12px"><b>{sms_wk}</b></td></tr>
  <tr><td style="padding:6px 12px;color:#666">Follow-ups sent</td><td style="padding:6px 12px"><b>{fu_wk}</b></td></tr>

  <tr style="background:#f5f5f5"><td colspan="2" style="padding:8px 12px;font-weight:bold;padding-top:16px">ALL TIME</td></tr>
  <tr><td style="padding:6px 12px;color:#666">Total emails</td><td style="padding:6px 12px"><b>{emails_all}</b></td></tr>
  <tr style="background:#f9f9f9"><td style="padding:6px 12px;color:#666">Total SMS</td><td style="padding:6px 12px"><b>{sms_all}</b></td></tr>
  <tr><td style="padding:6px 12px;color:#666">Total follow-ups</td><td style="padding:6px 12px"><b>{fu_all}</b></td></tr>
  <tr style="background:#f9f9f9"><td style="padding:6px 12px;color:#666">Bounce rate</td><td style="padding:6px 12px"><b>{bounce_rate:.1f}%</b></td></tr>

  <tr style="background:#f5f5f5"><td colspan="2" style="padding:8px 12px;font-weight:bold;padding-top:16px">PIPELINE</td></tr>
  <tr><td style="padding:6px 12px;color:#666">Zones completed</td><td style="padding:6px 12px"><b>{zones_done} / {zones_total}</b></td></tr>
  <tr style="background:#f9f9f9"><td style="padding:6px 12px;color:#666">Zones remaining</td><td style="padding:6px 12px"><b>{zones_left}</b></td></tr>
  <tr><td style="padding:6px 12px;color:#666">Next zone</td><td style="padding:6px 12px"><b>{next_zone}</b></td></tr>
</table>

<p style="margin-top:20px">
  <a href="https://webbymaya.com" style="color:#000;font-weight:bold">WebByMaya.com</a>
</p>
</body></html>"""

    send_email(subject, plain, html)


if __name__ == "__main__":
    main()
