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

    def _row(label, val, shade=False):
        bg = "background:#faf9f7;" if shade else ""
        return (f'<tr style="{bg}"><td style="padding:7px 14px;color:#888888;font-family:Arial,sans-serif;font-size:13px;">{label}</td>'
                f'<td style="padding:7px 14px;font-family:Arial,sans-serif;font-size:13px;font-weight:700;color:#1c1c1c;">{val}</td></tr>')
    def _section(label):
        return (f'<tr><td colspan="2" style="padding:12px 14px 6px;font-size:11px;font-weight:700;letter-spacing:2px;'
                f'text-transform:uppercase;color:#C9A96E;font-family:Arial,sans-serif;border-top:1px solid #eeeeee;">{label}</td></tr>')

    html = (
        '<!DOCTYPE html><html><head><meta charset="UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#f0ede8;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#f0ede8;">'
        '<tr><td align="center" style="padding:28px 12px;">'
        '<table role="presentation" width="560" cellpadding="0" cellspacing="0"'
        ' style="max-width:560px;width:100%;background:#ffffff;border-radius:10px;overflow:hidden;border:1px solid #e4dfd8;">'
        '<tr><td style="background:#C9A96E;height:3px;font-size:0;line-height:3px;">&nbsp;</td></tr>'
        '<tr><td style="padding:22px 28px 16px;">'
        f'<p style="margin:0 0 4px;font-size:10px;font-weight:700;letter-spacing:3px;text-transform:uppercase;color:#C9A96E;font-family:Arial,sans-serif;">WebByMaya</p>'
        f'<p style="margin:0;font-size:18px;font-weight:700;color:#1a1a1a;font-family:Arial,sans-serif;">Weekly Report</p>'
        f'<p style="margin:4px 0 0;font-size:12px;color:#aaa;font-family:Arial,sans-serif;">Week ending {today.strftime("%B %d, %Y")}</p>'
        '</td></tr>'
        '<tr><td style="padding:0 14px 24px;">'
        '<table width="100%" cellpadding="0" cellspacing="0">'
        + _section("This Week")
        + _row("Emails sent", emails_wk)
        + _row("SMS sent", sms_wk, shade=True)
        + _row("Follow-ups sent", fu_wk)
        + _section("All Time")
        + _row("Total emails", emails_all)
        + _row("Total SMS", sms_all, shade=True)
        + _row("Total follow-ups", fu_all)
        + _row("Bounce rate", f"{bounce_rate:.1f}%", shade=True)
        + _section("Pipeline")
        + _row("Zones completed", f"{zones_done} / {zones_total}")
        + _row("Zones remaining", zones_left, shade=True)
        + _row("Next zone", next_zone)
        + '</table>'
        '</td></tr>'
        '</table>'
        '</td></tr></table>'
        '</body></html>'
    )

    send_email(subject, plain, html)


if __name__ == "__main__":
    main()
