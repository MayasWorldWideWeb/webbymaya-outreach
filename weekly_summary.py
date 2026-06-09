#!/usr/bin/env python3
"""
weekly_summary.py — WebByMaya Monday Morning Report
Texts Maya a weekly summary of outreach performance.
"""
import base64, csv, json, os, urllib.request, urllib.parse
from datetime import datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
MY_NUMBER  = "+12154602084"
SID        = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN      = os.environ.get("TWILIO_AUTH_TOKEN","")
PHONE      = os.environ.get("TWILIO_PHONE_NUMBER","")

def load_all(pattern):
    rows = []
    for p in sorted(SCRIPT_DIR.glob(pattern)):
        with open(p, newline="") as f:
            rows.extend(csv.DictReader(f))
    return rows

def send_sms(to, body):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    data  = urllib.parse.urlencode({"To":to,"From":PHONE,"Body":body}).encode()
    req   = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
        data=data, headers={"Authorization":f"Basic {creds}",
                            "Content-Type":"application/x-www-form-urlencoded"}, method="POST")
    urllib.request.urlopen(req, timeout=8)

def main():
    week_ago = (datetime.now() - timedelta(days=7)).isoformat()[:10]

    sms_logs   = load_all("sms_log_*.csv")
    send_logs  = load_all("send_log_*.csv")
    bounces    = load_all("bounce_log.csv") if (SCRIPT_DIR/"bounce_log.csv").exists() else []
    statuses   = load_all("lead_status.csv") if (SCRIPT_DIR/"lead_status.csv").exists() else []

    # This week only
    sms_sent   = sum(1 for r in sms_logs if r.get("status")=="sent" and r.get("timestamp","")[:10] >= week_ago)
    email_sent = sum(1 for r in send_logs if r.get("status")=="sent" and r.get("timestamp","")[:10] >= week_ago)
    booked     = sum(1 for r in statuses if r.get("status")=="booked")
    warm       = sum(1 for r in statuses if r.get("status")=="warm")

    # All time
    total_sms   = sum(1 for r in sms_logs if r.get("status")=="sent")
    total_email = sum(1 for r in send_logs if r.get("status")=="sent")

    # Zone progress
    zone_file = SCRIPT_DIR / "zone_state.json"
    zones_done = 0; zones_total = 0
    if zone_file.exists():
        z = json.loads(zone_file.read_text())
        zones_done  = z.get("current_index",0)
        zones_total = len(z.get("zones",[]))

    msg = (
        f"WebByMaya Weekly Report 📊\n"
        f"Week of {week_ago}\n\n"
        f"THIS WEEK:\n"
        f"  SMS sent: {sms_sent}\n"
        f"  Emails sent: {email_sent}\n\n"
        f"ALL TIME:\n"
        f"  Total SMS: {total_sms}\n"
        f"  Total email: {total_email}\n"
        f"  Warm leads: {warm}\n"
        f"  Booked: {booked}\n\n"
        f"Philly progress: {zones_done}/{zones_total} zones done\n"
        f"Bounces on file: {len(bounces)}"
    )

    send_sms(MY_NUMBER, msg)
    print("Weekly summary sent.")

if __name__ == "__main__":
    main()
