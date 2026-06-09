#!/usr/bin/env python3
"""
send_followups.py — WebByMaya 3-Touch Follow-up Sequence
Sends follow-up texts to prospects contacted 4 or 10 days ago who haven't replied.
Run daily as part of the pipeline — add to run_daily.sh.
"""
import base64, csv, json, os, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
SID          = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN        = os.environ.get("TWILIO_AUTH_TOKEN","")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE_NUMBER","")

STOP_WORDS = {"stop","stopall","unsubscribe","cancel","end","quit"}

FOLLOWUP_DAY4 = (
    "Hi again! Maya from WebByMaya. Just wanted to follow up — "
    "I help Philly businesses get online for $799, live in 7 days. "
    "Happy to answer any questions on a quick free call: webbymaya.com/book "
    "Reply STOP to opt out."
)

FOLLOWUP_DAY10 = (
    "Last note — Maya @ WebByMaya. "
    "If getting {name} online is on your radar this year, I'm here. "
    "webbymaya.com/get-online Reply STOP to opt out."
)

def twilio_get(path):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url = f"https://api.twilio.com/2010-04-01/Accounts/{SID}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    try: return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except: return {}

def twilio_send(to, body):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    data  = urllib.parse.urlencode({"To":to,"From":TWILIO_PHONE,"Body":body}).encode()
    req   = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
        data=data,
        headers={"Authorization":f"Basic {creds}","Content-Type":"application/x-www-form-urlencoded"},
        method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return resp.get("sid"), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def load_all_sms():
    """Returns dict: phone -> {name, category, first_sent_date, sent_count}"""
    contacts = {}
    for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
        with open(p, newline="") as f:
            for row in csv.DictReader(f):
                if row.get("status") != "sent": continue
                phone = row.get("phone","").strip()
                if not phone: continue
                ts = row.get("timestamp","")[:10]
                if phone not in contacts:
                    contacts[phone] = {
                        "phone": phone, "name": row.get("name",""),
                        "category": row.get("category",""),
                        "first_sent": ts, "last_sent": ts, "count": 0
                    }
                if ts < contacts[phone]["first_sent"]:
                    contacts[phone]["first_sent"] = ts
                if ts > contacts[phone]["last_sent"]:
                    contacts[phone]["last_sent"] = ts
                contacts[phone]["count"] += 1
    return contacts

def load_replied_phones():
    """Returns set of phones that sent any real reply (including STOP)."""
    replied = set()
    data = twilio_get(f"/Messages.json?To={urllib.parse.quote(TWILIO_PHONE)}&PageSize=200")
    for m in data.get("messages", []):
        replied.add(m.get("from",""))
    return replied

def load_already_followed_up():
    """Return set of phones already sent a follow-up today."""
    path = SCRIPT_DIR / f"followup_log_{datetime.now().strftime('%Y-%m-%d')}.csv"
    if not path.exists(): return set()
    with open(path, newline="") as f:
        return {r["phone"] for r in csv.DictReader(f)}

def log_followup(phone, name, touch):
    today = datetime.now().strftime("%Y-%m-%d")
    path  = SCRIPT_DIR / f"followup_log_{today}.csv"
    exists = path.exists()
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["timestamp","phone","name","touch","status"])
        if not exists: w.writeheader()
        w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"),
                    "phone": phone, "name": name, "touch": touch, "status": "sent"})

def main():
    if not SID or not TOKEN or not TWILIO_PHONE:
        print("Twilio env vars not set — skipping follow-ups")
        return

    today         = datetime.now().date()
    contacts      = load_all_sms()
    replied       = load_replied_phones()
    already_sent  = load_already_followed_up()

    sent_day4 = sent_day10 = skipped = 0

    for phone, c in contacts.items():
        if phone in replied:      continue  # replied or opted out
        if phone in already_sent: continue  # already followed up today
        if not c["first_sent"]:   continue

        try:
            first = datetime.strptime(c["first_sent"], "%Y-%m-%d").date()
        except: continue

        days_ago  = (today - first).days
        send_count = c["count"]
        name  = c.get("name","your business")

        if days_ago == 4 and send_count == 1:
            sid, err = twilio_send(phone, FOLLOWUP_DAY4)
            if sid:
                log_followup(phone, name, "day4")
                sent_day4 += 1
                print(f"  Day-4 follow-up → {name} ({phone})")
            else:
                print(f"  [error] {phone}: {err}")

        elif days_ago == 10 and send_count <= 2:
            body = FOLLOWUP_DAY10.format(name=name)
            sid, err = twilio_send(phone, body)
            if sid:
                log_followup(phone, name, "day10")
                sent_day10 += 1
                print(f"  Day-10 follow-up → {name} ({phone})")
            else:
                print(f"  [error] {phone}: {err}")
        else:
            skipped += 1

    print(f"\nFollow-ups: {sent_day4} day-4, {sent_day10} day-10, {skipped} not due")

if __name__ == "__main__":
    main()
