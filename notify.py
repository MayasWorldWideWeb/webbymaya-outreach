#!/usr/bin/env python3
"""
notify.py — WebByMaya Reply Notifier
Runs every 5 minutes via LaunchAgent.
Texts Maya's personal phone when a real reply comes in from a prospect.
"""
import base64, json, os, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
SEEN_FILE    = SCRIPT_DIR / ".seen_replies.json"
MY_NUMBER    = "+12154602084"   # Maya's personal phone
SID          = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN        = os.environ.get("TWILIO_AUTH_TOKEN","")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE_NUMBER","")

STOP_WORDS   = {"stop","stopall","unsubscribe","cancel","end","quit"}
AUTO_SIGNALS = ["out of the office","configure your number","twilio",
                "if this is a medic","do not reply","away from the office"]

def twilio(path, data=None):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url   = f"https://api.twilio.com/2010-04-01/Accounts/{SID}{path}"
    body  = urllib.parse.urlencode(data).encode() if data else None
    req   = urllib.request.Request(url, data=body,
                headers={"Authorization": f"Basic {creds}",
                         **({"Content-Type":"application/x-www-form-urlencoded"} if data else {})},
                method="POST" if data else "GET")
    return json.loads(urllib.request.urlopen(req, timeout=8).read())

def load_seen():
    if SEEN_FILE.exists():
        return set(json.loads(SEEN_FILE.read_text()))
    return set()

def save_seen(seen):
    SEEN_FILE.write_text(json.dumps(list(seen)))

def is_real(msg):
    body = msg.get("body","")
    if body.strip().lower() in STOP_WORDS: return False
    if any(s in body.lower() for s in AUTO_SIGNALS): return False
    return True

def main():
    seen = load_seen()
    data = twilio(f"/Messages.json?To={urllib.parse.quote(TWILIO_PHONE)}&PageSize=50")
    msgs = data.get("messages",[])

    new_real = [m for m in msgs if m["sid"] not in seen and is_real(m)]

    for m in new_real:
        frm  = m.get("from","")
        body = m.get("body","")[:100]
        text = f"WebByMaya reply from {frm}:\n\"{body}\"\n→ webbymaya.com/dashboard or reply FOLLOWUP {frm}"
        twilio("/Messages.json", {"To": MY_NUMBER, "From": TWILIO_PHONE, "Body": text})
        print(f"Notified: {frm}")
        seen.add(m["sid"])

    # Also mark seen for non-real messages so they don't noise up future checks
    for m in msgs:
        seen.add(m["sid"])

    save_seen(seen)

if __name__ == "__main__":
    main()
