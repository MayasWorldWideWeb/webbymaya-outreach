#!/usr/bin/env python3
"""
notify.py — WebByMaya Reply Notifier
Runs every 5 minutes via LaunchAgent.
Notifies Maya (Mac popup + personal SMS) when a real reply comes in.
Watches: SMS replies (Twilio) + email replies (Gmail inbox).
"""
import base64, json, os, subprocess, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
SEEN_SMS     = SCRIPT_DIR / ".seen_replies.json"
SEEN_EMAIL   = SCRIPT_DIR / ".seen_gmail_replies.json"
MY_NUMBER    = "+12154602084"
SID          = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN        = os.environ.get("TWILIO_AUTH_TOKEN","")
TWILIO_PHONE = os.environ.get("TWILIO_PHONE_NUMBER","")
SG           = os.environ.get("SENDGRID_API_KEY","")

GMAIL_TOKEN  = Path.home() / ".webbymaaya/gmail_token.json"
SEND_LOG_DIR = SCRIPT_DIR

STOP_WORDS   = {"stop","stopall","unsubscribe","cancel","end","quit"}

POSITIVE_KEYWORDS = [
    "interested","yes","sure","sounds good","tell me more","how much",
    "price","cost","how long","when","examples","portfolio","show me",
    "go ahead","let's do it","lets do it","sign me up","book",
    "available","call me","reach me","contact me","definitely","absolutely",
    "i want","i'd like","i would like","set it up","what's included",
]

AUTO_REPLY = (
    "Hi! Thanks for reaching back out — I'd love to help get {name} online! "
    "Fill out my quick intake form and I'll take it from there: "
    "webbymaya.com/book — takes 2 minutes. — Maya"
)
AUTO_REPLY_GENERIC = (
    "Hi! Thanks for reaching out — fill out my intake form and I'll "
    "walk you through everything: webbymaya.com/book — Maya"
)

SEEN_AUTOREPLIED = SCRIPT_DIR / ".seen_autoreplied.json"
AUTO_SIGNALS = ["out of the office","configure your number","twilio",
                "if this is a medic","do not reply","away from the office"]

SKIP_DOMAINS = {
    "adr.org","aura.com","zendesk.com","hubspot.com","salesforce.com",
    "meta.com","facebook.com","google.com","microsoft.com","apple.com",
    "sba.gov","ftc.gov","irs.gov","pa.gov","nj.gov","phila.gov",
    "upenn.edu","temple.edu","drexel.edu","prweb.com","businesswire.com",
    "fresha.com","birdeye.com","yelp.com","yext.com","thryv.com",
    "grubhub.com","doordash.com","toasttab.com","squareup.com",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def mac_notify(title: str, body: str):
    """macOS notification center popup."""
    try:
        script = f'display notification "{body}" with title "{title}" sound name "Glass"'
        subprocess.run(["osascript", "-e", script], timeout=5)
    except Exception:
        pass


def twilio(path, data=None):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url   = f"https://api.twilio.com/2010-04-01/Accounts/{SID}{path}"
    body  = urllib.parse.urlencode(data).encode() if data else None
    req   = urllib.request.Request(url, data=body,
                headers={"Authorization": f"Basic {creds}",
                         **({"Content-Type":"application/x-www-form-urlencoded"} if data else {})},
                method="POST" if data else "GET")
    return json.loads(urllib.request.urlopen(req, timeout=8).read())


def sms_self(msg: str):
    """Text Maya's personal phone."""
    try:
        twilio("/Messages.json", {"To": MY_NUMBER, "From": TWILIO_PHONE, "Body": msg})
    except Exception:
        pass


def is_real_sms(msg):
    body = msg.get("body","")
    if body.strip().lower() in STOP_WORDS: return False
    if any(s in body.lower() for s in AUTO_SIGNALS): return False
    return True


def is_positive_sms(body: str) -> bool:
    b = body.lower()
    return any(kw in b for kw in POSITIVE_KEYWORDS)


def load_sms_names() -> dict[str, str]:
    """phone → business name from sms logs."""
    import csv as _csv
    out = {}
    for p in sorted(SCRIPT_DIR.glob("sms_log_*.csv")):
        try:
            with open(p, newline="", encoding="utf-8") as f:
                for row in _csv.DictReader(f):
                    ph = row.get("phone","").strip()
                    nm = row.get("name","").strip()
                    if ph and nm and ph not in out:
                        out[ph] = nm
        except Exception:
            pass
    return out


def send_sms(to: str, body: str):
    try:
        import base64
        creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
        data  = urllib.parse.urlencode({"To": to, "From": TWILIO_PHONE, "Body": body}).encode()
        req   = urllib.request.Request(
            f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
            data=data,
            headers={"Authorization": f"Basic {creds}",
                     "Content-Type": "application/x-www-form-urlencoded"},
            method="POST")
        urllib.request.urlopen(req, timeout=8)
        return True
    except Exception as e:
        print(f"[auto-reply] send failed: {e}")
        return False


def load_seen(path: Path) -> set:
    if path.exists():
        return set(json.loads(path.read_text()))
    return set()


def save_seen(path: Path, seen: set):
    path.write_text(json.dumps(list(seen)))


# ── Gmail helpers ─────────────────────────────────────────────────────────────

def gmail_access_token() -> str:
    if not GMAIL_TOKEN.exists():
        return ""
    tok = json.loads(GMAIL_TOKEN.read_text())
    access = tok.get("token","")
    try:
        exp = datetime.fromisoformat(tok["expiry"].replace("Z","+00:00"))
        if datetime.now(timezone.utc) >= exp - timedelta(seconds=60):
            data = urllib.parse.urlencode({
                "client_id":     tok["client_id"],
                "client_secret": tok["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type":    "refresh_token",
            }).encode()
            resp = json.loads(urllib.request.urlopen(
                urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
                timeout=10).read())
            access = resp["access_token"]
            tok["token"]  = access
            tok["expiry"] = (datetime.now(timezone.utc) +
                             timedelta(seconds=resp.get("expires_in",3600))
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            GMAIL_TOKEN.write_text(json.dumps(tok))
    except Exception:
        pass
    return access


def load_emailed_addresses() -> set:
    """Emails we've actually sent to — so we only notify on replies from real prospects."""
    addrs = set()
    for p in sorted(SEND_LOG_DIR.glob("send_log_*.csv")):
        try:
            import csv
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent":
                        e = row.get("email_sent_to","").strip().lower()
                        if e:
                            addrs.add(e)
        except Exception:
            pass
    # Also include clicker followup addresses
    for p in sorted(SEND_LOG_DIR.glob("clicker_followup_log_*.csv")):
        try:
            import csv
            with open(p, newline="", encoding="utf-8") as f:
                for row in csv.DictReader(f):
                    if row.get("status") == "sent":
                        e = row.get("email","").strip().lower()
                        if e:
                            addrs.add(e)
        except Exception:
            pass
    return addrs


def check_gmail_replies(seen: set) -> list[dict]:
    """Returns new Gmail replies from known prospects."""
    access = gmail_access_token()
    if not access:
        return []

    known = load_emailed_addresses()
    if not known:
        return []

    new_replies = []
    try:
        # Fetch recent inbox messages not from self
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages"
            "?q=in:inbox+-from:me&maxResults=30",
            headers={"Authorization": f"Bearer {access}"})
        result = json.loads(urllib.request.urlopen(req, timeout=10).read())

        for m in result.get("messages", []):
            mid = m["id"]
            if mid in seen:
                continue

            # Fetch headers only
            req2 = urllib.request.Request(
                f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{mid}"
                "?format=metadata&metadataHeaders=From&metadataHeaders=Subject",
                headers={"Authorization": f"Bearer {access}"})
            detail = json.loads(urllib.request.urlopen(req2, timeout=10).read())

            hdrs = {h["name"]: h["value"]
                    for h in detail.get("payload",{}).get("headers",[])}
            frm  = hdrs.get("From","")
            import re
            match = re.search(r'<([^>]+)>', frm)
            addr  = match.group(1).lower() if match else frm.lower().strip()

            seen.add(mid)

            if addr not in known:
                continue
            domain = addr.split("@")[-1] if "@" in addr else ""
            if domain in SKIP_DOMAINS or domain.endswith(".gov") or domain.endswith(".edu"):
                continue

            subj    = hdrs.get("Subject","(no subject)")
            snippet = detail.get("snippet","")[:100]
            new_replies.append({"addr": addr, "subject": subj, "snippet": snippet})

    except Exception as e:
        print(f"[gmail] error: {e}")

    return new_replies


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    seen_sms       = load_seen(SEEN_SMS)
    seen_email     = load_seen(SEEN_EMAIL)
    seen_replied   = load_seen(SEEN_AUTOREPLIED)
    sms_names      = load_sms_names()

    # ── SMS replies ───────────────────────────────────────────────────────────
    if SID and TOKEN and TWILIO_PHONE:
        try:
            data = twilio(f"/Messages.json?To={urllib.parse.quote(TWILIO_PHONE)}&PageSize=50")
            msgs = data.get("messages",[])
            new_real = [m for m in msgs if m["sid"] not in seen_sms and is_real_sms(m)]

            for m in new_real:
                frm  = m.get("from","")
                body = m.get("body","")[:100]
                print(f"SMS reply: {frm} — {body[:60]}")
                mac_notify("WebByMaya — SMS Reply", f"{frm}: {body[:80]}")
                sms_self(f"WebByMaya reply from {frm}:\n\"{body}\"\n→ check dashboard")
                seen_sms.add(m["sid"])

                # Auto-reply to positive messages (once per number)
                if frm not in seen_replied and is_positive_sms(body):
                    name    = sms_names.get(frm, "")
                    reply   = (AUTO_REPLY.format(name=name) if name
                               else AUTO_REPLY_GENERIC)
                    if send_sms(frm, reply):
                        print(f"  Auto-replied to {frm}")
                        mac_notify("WebByMaya — Auto-Replied", f"Sent booking link to {frm}")
                        seen_replied.add(frm)

            for m in msgs:
                seen_sms.add(m["sid"])
        except Exception as e:
            print(f"[sms] error: {e}")

    save_seen(SEEN_SMS, seen_sms)

    # ── Gmail replies ─────────────────────────────────────────────────────────
    gmail_replies = check_gmail_replies(seen_email)
    for r in gmail_replies:
        addr = r["addr"]; subj = r["subject"]; snip = r["snippet"]
        print(f"Email reply: {addr} — {subj}")
        mac_notify("WebByMaya — Email Reply", f"{addr}: {snip[:80]}")
        sms_self(f"WebByMaya email reply from {addr}\nSubject: {subj}\n→ check dashboard")

    save_seen(SEEN_EMAIL, seen_email)
    save_seen(SEEN_AUTOREPLIED, seen_replied)


if __name__ == "__main__":
    main()
