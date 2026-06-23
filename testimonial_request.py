#!/usr/bin/env python3
"""
testimonial_request.py — Auto-send testimonial request emails to recently-gone-Live clients.

Runs weekly (Fridays via run_daily.sh). Targets projects that went Live 7-14 days ago
and haven't received a testimonial request yet. Logs to testimonial_log.csv.
"""
import csv, json, os, smtplib, ssl, sys
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
PROJECTS_FILE = SCRIPT_DIR / "projects.json"
LOG_PATH      = SCRIPT_DIR / "testimonial_log.csv"
LOG_FIELDS    = ["date","name","phone","email","status","notes"]

GMAIL_USER    = os.environ.get("GMAIL_USER", "maya@webbymaya.com")
GMAIL_PASS    = os.environ.get("GMAIL_APP_PASSWORD", "")

SUBJECT = "How's your new website going, {name}?"
BODY = """\
Hi there,

I just wanted to check in — it's been about a week since your new website went live!

How's it feeling? Any questions or tweaks you'd like?

If you're happy with everything, I'd love it if you could leave a quick Google review or share a few words I can feature on my site. It really helps local businesses find me.

Here's my Google link (only takes 30 seconds):
https://g.page/r/webbymaya/review

Or just reply here with a quick sentence about your experience — I'll handle the rest!

Thank you so much for trusting me with your business. It means a lot.

Maya Sierra
Web Designer · WebByMaya.com
maya@webbymaya.com
"""


def load_csv(path):
    p = Path(path)
    if not p.exists():
        return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_projects():
    if not PROJECTS_FILE.exists():
        return []
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except Exception:
        return []


def already_sent(phone):
    rows = load_csv(LOG_PATH)
    return any(r.get("phone") == phone and r.get("status") == "sent" for r in rows)


def log_send(name, phone, email, status, notes=""):
    exists = LOG_PATH.exists()
    with open(LOG_PATH, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        if not exists:
            w.writeheader()
        w.writerow({
            "date":   datetime.now().strftime("%Y-%m-%d"),
            "name":   name,
            "phone":  phone,
            "email":  email,
            "status": status,
            "notes":  notes,
        })


def send_email(to_email, name):
    if not GMAIL_PASS:
        print(f"  [skip] No GMAIL_APP_PASSWORD set — can't send to {name}")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = SUBJECT.format(name=name)
        msg["From"]    = f"Maya Sierra <{GMAIL_USER}>"
        msg["To"]      = to_email
        msg.attach(MIMEText(BODY, "plain"))
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=ctx) as s:
            s.login(GMAIL_USER, GMAIL_PASS)
            s.sendmail(GMAIL_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"  [error] {name}: {e}")
        return False


def main():
    projects = load_projects()
    today    = datetime.now()
    window_start = (today - timedelta(days=14)).strftime("%Y-%m-%d")
    window_end   = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    candidates = [
        p for p in projects
        if p.get("stage") == "Live"
        and p.get("live_date","") >= window_start
        and p.get("live_date","") <= window_end
        and not already_sent(p.get("phone",""))
        and p.get("email","")
    ]

    if not candidates:
        print("No testimonial requests to send today.")
        return

    sent = 0
    for p in candidates:
        name  = p.get("name","")
        phone = p.get("phone","")
        email = p.get("email","").strip()
        print(f"  Sending testimonial request → {name} <{email}>")
        ok = send_email(email, name)
        log_send(name, phone, email, "sent" if ok else "failed")
        if ok:
            sent += 1

    print(f"\nTestimonial requests sent: {sent}/{len(candidates)}")


if __name__ == "__main__":
    main()
