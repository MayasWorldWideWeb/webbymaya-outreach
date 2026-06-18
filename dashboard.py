#!/usr/bin/env python3
"""
dashboard.py — WebByMaya Outreach Console v3
Run:  python3 dashboard.py
Open: http://localhost:8787
"""
import base64, csv, email.mime.multipart, email.mime.text, json, os, re, urllib.request, urllib.parse, urllib.error
from collections import Counter
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from sb import set_lead_status, queue_followup, log_sms

SCRIPT_DIR  = Path(__file__).parent
PORT        = 8787
SID         = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN       = os.environ.get("TWILIO_AUTH_TOKEN","")
PHONE       = os.environ.get("TWILIO_PHONE_NUMBER","")
SG          = os.environ.get("SENDGRID_API_KEY","")
SITE_PRICE  = 799
SENDER_EMAIL = "maya@webbymaya.com"
SENDER_NAME  = "Maya Sierra"

SUPABASE_URL_WBM = "https://ycsauzlqsjjbusugshpz.supabase.co"
SUPABASE_KEY_WBM = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc3OTQ2MzMxNCwiZXhwIjoyMDk1MDM5MzE0fQ.0qJY5I3THWHxPVVM49D8Ov1pmH91gMYb5bIXOOKJy1c"

def fetch_intake_responses():
    url = (f"{SUPABASE_URL_WBM}/rest/v1/intake_responses"
           "?select=id,submitted_at,business_name,contact_name,contact_email,"
           "contact_phone,budget,timeline,primary_goal,how_found,current_website,"
           "what_you_do,services_list,anything_else"
           "&order=submitted_at.desc&limit=50")
    req = urllib.request.Request(url, headers={
        "apikey":        SUPABASE_KEY_WBM,
        "Authorization": f"Bearer {SUPABASE_KEY_WBM}",
    })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except Exception:
        return []

FOLLOWUP_MSG = (
    "Hi {name}! This is Maya from WebByMaya following up on my earlier message. "
    "I'd love to get {name} online — fill out my quick form and I'll get started: "
    "https://webbymaya.com/book"
)

FOLLOWUP_EMAIL_SUBJECT = "Still thinking about it, {name}?"
FOLLOWUP_EMAIL_PLAIN = """\
Hi there,

I reached out recently about building a website for {name} and wanted to follow up.

A lot of local businesses lose customers simply because people can't find them online \
— no Google listing, no hours, no way to book. I'd love to change that for you.

I'm Maya, a web designer based in Philly. Sites start at $799 and are ready fast.

Fill out my quick intake form: https://webbymaya.com/book

Or just reply here — I check email daily.

Maya Sierra
Web Designer · WebByMaya.com
maya@webbymaya.com
"""

CLICKER_EMAIL_SUBJECT = "Can I send you a mockup, {name}?"
CLICKER_EMAIL_PLAIN = """\
Hi,

I noticed you checked out my site — thanks for taking a look!

I wanted to reach out personally. I build websites for local businesses \
in the Philly area, and I'd love to show you what one could look like for {name}.

No call needed. Just reply "yes" and I'll put together a free mockup — takes me \
about 20 minutes and you're under no obligation.

Sites start at $799 and usually go live within a week.

Maya Sierra
Web Designer · WebByMaya.com
maya@webbymaya.com
"""

# ── CSV helpers ────────────────────────────────────────────────────────────────

def load_csv(path):
    p = Path(path)
    if not p.exists(): return []
    with open(p, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))

def save_csv(path, rows, fieldnames):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader(); w.writerows(rows)

def all_logs(pattern):
    rows = []
    for p in sorted(SCRIPT_DIR.glob(pattern)):
        rows.extend(load_csv(p))
    return rows

def all_email_logs():
    """Load ALL email send logs, normalized to a common schema.

    Unified schema: date, name, category, email_sent_to, subject, status, log_type
    status is always 'sent' or 'skipped'/'failed'.
    """
    rows = []

    # 1. Main outreach send logs — already have the right columns
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        for r in load_csv(p):
            rows.append({
                "date":         (r.get("timestamp","") or "")[:10],
                "name":         r.get("name",""),
                "category":     r.get("category",""),
                "email_sent_to": r.get("email_sent_to",""),
                "subject":      r.get("subject",""),
                "status":       r.get("status",""),
                "provider":     r.get("provider","sendgrid"),
                "log_type":     "outreach",
            })

    # 2. Email follow-up logs (rounds 1–3)
    for p in sorted(SCRIPT_DIR.glob("email_followup_log_*.csv")):
        for r in load_csv(p):
            rows.append({
                "date":         (r.get("timestamp","") or "")[:10],
                "name":         r.get("name",""),
                "category":     r.get("category",""),
                "email_sent_to": r.get("email",""),
                "subject":      r.get("subject",""),
                "status":       "sent" if r.get("status","").lower() == "sent" else r.get("status",""),
                "log_type":     "followup",
            })

    # 3. Clicker follow-up logs
    for p in sorted(SCRIPT_DIR.glob("clicker_followup_log_*.csv")):
        for r in load_csv(p):
            status = r.get("status","").lower()
            rows.append({
                "date":         (r.get("timestamp","") or "")[:10],
                "name":         r.get("name",""),
                "category":     "",
                "email_sent_to": r.get("email",""),
                "subject":      "",
                "status":       "sent" if status in ("sent","sent_mockup") else status,
                "log_type":     "clicker",
            })

    # 4. Re-engagement logs
    for p in sorted(SCRIPT_DIR.glob("reengagement_log*.csv")):
        for r in load_csv(p):
            rows.append({
                "date":         (r.get("date","") or r.get("timestamp",""))[:10],
                "name":         r.get("name",""),
                "category":     r.get("category",""),
                "email_sent_to": r.get("email",""),
                "subject":      "",
                "status":       "sent" if r.get("status","").lower() in ("sent","") else r.get("status",""),
                "log_type":     "reengagement",
            })

    # 5. Seasonal campaign logs (exclude dry runs)
    for p in sorted(SCRIPT_DIR.glob("seasonal_log_*.csv")):
        for r in load_csv(p):
            if r.get("dry_run","0") == "1":
                continue
            rows.append({
                "date":         r.get("date",""),
                "name":         r.get("name",""),
                "category":     r.get("category",""),
                "email_sent_to": r.get("email",""),
                "subject":      "",
                "status":       "sent",
                "log_type":     "seasonal",
            })

    return rows

def load_statuses():
    rows = load_csv(SCRIPT_DIR / "lead_status.csv")
    return {r["phone"]: r for r in rows}

def save_status(phone, name, category, status, note=""):
    set_lead_status(phone, name, category, status, note)
    path = SCRIPT_DIR / "lead_status.csv"
    rows = load_csv(path)
    existing = next((r for r in rows if r["phone"] == phone), None)
    if existing:
        existing["status"]  = status
        if note: existing["note"] = note
        existing["updated"] = datetime.now().isoformat(timespec="seconds")
    else:
        rows.append({"phone": phone, "name": name, "category": category,
                     "status": status, "note": note,
                     "updated": datetime.now().isoformat(timespec="seconds")})
    save_csv(path, rows, ["phone","name","category","status","note","updated"])

    if status == "won":
        _log_revenue(phone, name, category)
        _create_project(phone, name, category)
    elif status == "booked":
        _create_project(phone, name, category, stage="Form received")


REVENUE_LOG = SCRIPT_DIR / "revenue_log.csv"
REVENUE_COLS = ["date", "name", "phone", "category", "package", "amount"]

def _log_revenue(phone: str, name: str, category: str, package: str = "Standard", amount: int = SITE_PRICE):
    is_new = not REVENUE_LOG.exists()
    rows = load_csv(REVENUE_LOG)
    if any(r.get("phone") == phone and r.get("name") == name for r in rows):
        return  # already logged
    with open(REVENUE_LOG, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=REVENUE_COLS)
        if is_new:
            w.writeheader()
        w.writerow({"date": datetime.now().strftime("%Y-%m-%d"), "name": name,
                    "phone": phone, "category": category,
                    "package": package, "amount": amount})


PROJECTS_FILE = SCRIPT_DIR / "projects.json"
PROJECT_STAGES = ["Form received", "Mockup sent", "Mockup approved", "In build", "Live"]

def _load_projects() -> list:
    if not PROJECTS_FILE.exists():
        return []
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except Exception:
        return []

def _save_projects(projects: list):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))

def _create_project(phone: str, name: str, category: str, stage: str = "Form received"):
    projects = _load_projects()
    if any(p.get("phone") == phone for p in projects):
        return  # already exists
    projects.append({
        "phone":    phone,
        "name":     name,
        "category": category,
        "stage":    stage,
        "started":  datetime.now().strftime("%Y-%m-%d"),
        "deadline": "",
        "notes":    "",
    })
    _save_projects(projects)

def get_revenue_history():
    rows = load_csv(REVENUE_LOG)
    by_month: dict = {}
    total = 0
    for r in rows:
        mo = (r.get("date") or "")[:7]
        amt = int(r.get("amount") or SITE_PRICE)
        if mo:
            by_month[mo] = by_month.get(mo, 0) + amt
        total += amt
    return {
        "by_month": [{"month": m, "revenue": v} for m, v in sorted(by_month.items())],
        "rows":     rows,
        "total":    total,
        "clients":  len(rows),
    }

def save_note_only(phone, name, category, note):
    path = SCRIPT_DIR / "lead_status.csv"
    rows = load_csv(path)
    existing = next((r for r in rows if r["phone"] == phone), None)
    if existing:
        existing["note"]    = note
        existing["updated"] = datetime.now().isoformat(timespec="seconds")
    else:
        rows.append({"phone": phone, "name": name, "category": category,
                     "status": "contacted", "note": note,
                     "updated": datetime.now().isoformat(timespec="seconds")})
    save_csv(path, rows, ["phone","name","category","status","note","updated"])

def load_followup_queue():
    return load_csv(SCRIPT_DIR / "followup_queue.csv")

def add_to_queue(phone, name, category, send_after, reason):
    queue_followup(phone, name, category, send_after, reason)
    path = SCRIPT_DIR / "followup_queue.csv"
    rows = load_csv(path)
    if any(r["phone"] == phone and r["sent"] == "no" for r in rows):
        return False
    rows.append({"phone": phone, "name": name, "category": category,
                 "send_after": send_after, "reason": reason,
                 "sent": "no", "queued_at": datetime.now().isoformat(timespec="seconds")})
    save_csv(path, rows, ["phone","name","category","send_after","reason","sent","queued_at"])
    return True

# ── Twilio / SendGrid ──────────────────────────────────────────────────────────

def sg_send_email(to, subject, plain):
    if not SG: return None, "SENDGRID_API_KEY not set"
    html = (f'<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">'
            f'<p>{plain.replace(chr(10),"<br>")}</p></body></html>')
    payload = json.dumps({
        "personalizations": [{"to": [{"email": to}]}],
        "from": {"email": SENDER_EMAIL, "name": SENDER_NAME},
        "subject": subject,
        "content": [{"type":"text/plain","value":plain},{"type":"text/html","value":html}],
    }).encode()
    req = urllib.request.Request(
        "https://api.sendgrid.com/v3/mail/send", data=payload,
        headers={"Authorization": f"Bearer {SG}", "Content-Type": "application/json"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True, None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()
    except Exception as exc:
        return None, str(exc)

def gmail_send_email(to, subject, plain):
    """Send via Gmail API using stored OAuth token. Falls back to SendGrid on error."""
    token_path = Path.home() / ".webbymaaya/gmail_token.json"
    if not token_path.exists():
        return sg_send_email(to, subject, plain)
    try:
        tok = json.loads(token_path.read_text())
        access = tok.get("token", "")
        # Auto-refresh if expired
        try:
            exp = datetime.fromisoformat(tok["expiry"].replace("Z", "+00:00"))
            if datetime.now(timezone.utc) >= exp - timedelta(seconds=60):
                data = urllib.parse.urlencode({
                    "client_id":     tok["client_id"],
                    "client_secret": tok["client_secret"],
                    "refresh_token": tok["refresh_token"],
                    "grant_type":    "refresh_token",
                }).encode()
                req  = urllib.request.Request("https://oauth2.googleapis.com/token", data=data)
                resp = json.loads(urllib.request.urlopen(req, timeout=10).read())
                access = resp["access_token"]
                tok["token"]  = access
                tok["expiry"] = (datetime.now(timezone.utc) + timedelta(seconds=resp.get("expires_in", 3600))).strftime("%Y-%m-%dT%H:%M:%SZ")
                token_path.write_text(json.dumps(tok))
        except Exception:
            pass
        # Build RFC 2822 message
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["To"]      = to
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["Subject"] = subject
        html = (f'<html><body style="font-family:Arial,sans-serif;color:#333;max-width:600px;margin:auto">'
                f'<p>{plain.replace(chr(10), "<br>")}</p></body></html>')
        msg.attach(email.mime.text.MIMEText(plain, "plain"))
        msg.attach(email.mime.text.MIMEText(html,  "html"))
        raw     = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = json.dumps({"raw": raw}).encode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=payload,
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True, None
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        return None, f"Gmail API: {err[:300]}"
    except Exception as exc:
        return None, str(exc)

def twilio_get(path):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url   = f"https://api.twilio.com/2010-04-01/Accounts/{SID}{path}"
    req   = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    try: return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except: return {}

def twilio_send_sms(to, body):
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url   = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    data  = urllib.parse.urlencode({"To": to, "From": PHONE, "Body": body}).encode()
    req   = urllib.request.Request(url, data=data,
                headers={"Authorization": f"Basic {creds}",
                         "Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return resp.get("sid"), None
    except urllib.error.HTTPError as e:
        return None, e.read().decode()

def fetch_inbound():
    data = twilio_get(f"/Messages.json?To={urllib.parse.quote(PHONE)}&PageSize=100")
    return data.get("messages", [])

def fetch_sg_stats():
    if not SG: return {}
    url = "https://api.sendgrid.com/v3/stats?start_date=2026-05-01&aggregated_by=day"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {SG}"})
    try:
        days = json.loads(urllib.request.urlopen(req, timeout=8).read())
        t = {"requests":0,"delivered":0,"opens":0,"clicks":0,"bounces":0}
        for day in days:
            for s in day.get("stats",[]):
                m = s.get("metrics",{})
                for k in t: t[k] += m.get(k,0)
        return t
    except: return {}

def fetch_suppressed():
    out = set()
    if not SG: return out
    for ep in ["bounces","blocks","spam_reports"]:
        req = urllib.request.Request(
            f"https://api.sendgrid.com/v3/suppression/{ep}?limit=500",
            headers={"Authorization": f"Bearer {SG}"})
        try:
            for r in json.loads(urllib.request.urlopen(req, timeout=8).read()):
                out.add(r.get("email","").lower())
        except: pass
    return out

SCANNER_DOMAINS = {
    # Government / academic / courts
    "sba.gov","dnr.ohio.gov","dnr.gov","usda.gov","hhs.gov","nih.gov","adr.org",
    "ftc.gov","irs.gov","state.pa.us","state.nj.us","epa.gov","cdc.gov",
    "phila.gov","pa.gov","nj.gov","courts.phila.gov",
    "pennmedicine.upenn.edu","upenn.edu","temple.edu","drexel.edu",
    # Major tech / media (emails enriched to wrong address)
    "meta.com","facebook.com","google.com","microsoft.com","apple.com","amazon.com",
    "dailymail.com","billypenn.com","nytimes.com","washingtonpost.com","cnn.com",
    "reuters.com","apnews.com","bloomberg.com","wsj.com","forbes.com","inc.com",
    "aura.com","zendesk.com","hubspot.com","salesforce.com","stripe.com",
    # Known catch-all / press addresses
    "prweb.com","businesswire.com","prnewswire.com",
}

def fetch_twilio_delivery_stats(limit=1000):
    """Returns delivery breakdown for recent outbound SMS from Twilio."""
    if not SID or not TOKEN or not PHONE: return {}
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    url   = (f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
             f"?From={urllib.parse.quote(PHONE)}&PageSize={limit}")
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    try:
        msgs     = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("messages", [])
        statuses = Counter()
        errors   = Counter()
        segments = 0
        for m in msgs:
            statuses[m.get("status","unknown")] += 1
            ec = m.get("error_code")
            if ec: errors[ec] += 1
            segments += int(m.get("num_segments", 1) or 1)
        total     = len(msgs)
        delivered = statuses.get("delivered", 0)
        return {
            "total":          total,
            "delivered":      delivered,
            "undelivered":    statuses.get("undelivered", 0),
            "failed":         statuses.get("failed", 0),
            "delivery_rate":  round(delivered / total * 100, 1) if total else 0,
            "blocked_10dlc":  errors.get(30034, 0),
            "landlines":      errors.get(30006, 0),
            "unreachable":    errors.get(30005, 0),
            "opted_out":      errors.get(21610, 0),
            "segments":       segments,
            "has_10dlc_issue": errors.get(30034, 0) > 0,
        }
    except Exception:
        return {}

def fetch_sg_clickers():
    """Returns {email: {clicks, opens, businesses[], likely_bot}} for emails that clicked."""
    if not SG: return {}
    try:
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/messages?limit=1000",
            headers={"Authorization": f"Bearer {SG}"})
        msgs = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("messages", [])
        clickers = {}
        for m in msgs:
            if m.get("clicks_count", 0) < 1:
                continue
            email  = m.get("to_email", "").lower().strip()
            if not email:
                continue
            opens  = m.get("opens_count", 0)
            clicks = m.get("clicks_count", 0)
            domain = email.split("@")[-1] if "@" in email else ""
            subj   = m.get("subject", "")
            biz    = subj.replace("Quick question, ", "").replace("Still thinking about it, ","").rstrip("?").strip()
            # Bot if: known scanner domain, OR clicked many times with zero opens (link scanner)
            is_bot = domain in SCANNER_DOMAINS or (clicks >= 4 and opens == 0)
            if email not in clickers:
                clickers[email] = {"clicks": 0, "opens": 0, "businesses": [], "likely_bot": is_bot}
            clickers[email]["clicks"] += clicks
            clickers[email]["opens"]  += opens
            if biz and biz not in clickers[email]["businesses"]:
                clickers[email]["businesses"].append(biz)
        return clickers
    except Exception:
        return {}

def fetch_sg_daily():
    """Returns per-day SendGrid stats for last 14 days."""
    if not SG: return []
    start = (datetime.now() - timedelta(days=14)).strftime("%Y-%m-%d")
    url = f"https://api.sendgrid.com/v3/stats?start_date={start}&aggregated_by=day"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {SG}"})
    try:
        days = json.loads(urllib.request.urlopen(req, timeout=8).read())
        result = []
        for day in days:
            date = day.get("date","")
            m = {}
            for s in day.get("stats",[]):
                for k, v in s.get("metrics",{}).items():
                    m[k] = m.get(k,0) + v
            if m.get("requests",0) > 0:
                result.append({
                    "date":    date,
                    "sent":    m.get("requests",0),
                    "opens":   m.get("opens",0),
                    "clicks":  m.get("clicks",0),
                    "bounces": m.get("bounces",0),
                })
        return result
    except: return []

# ── Feature 1: Gmail replies ────────────────────────────────────────────────────

def fetch_gmail_replies(email_to_name):
    """Pull email replies from Gmail for contacts we've emailed."""
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError:
        return []
    token_path = Path.home() / ".webbymaaya/gmail_token.json"
    if not token_path.exists(): return []
    try:
        creds = Credentials.from_authorized_user_file(str(token_path))
        svc   = build("gmail", "v1", credentials=creds, cache_discovery=False)
        result = svc.users().messages().list(
            userId="me", q="in:inbox -from:me", maxResults=50).execute()
        out = []
        for m in result.get("messages", []):
            detail = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From","Subject","Date"]).execute()
            hdrs = {h["name"]: h["value"]
                    for h in detail.get("payload",{}).get("headers",[])}
            frm = hdrs.get("From","")
            match = re.search(r'<([^>]+)>', frm)
            addr  = match.group(1).lower() if match else frm.lower().strip()
            if addr not in email_to_name: continue
            out.append({
                "kind": "email_in",
                "from_email": addr,
                "name": email_to_name[addr],
                "subject": hdrs.get("Subject",""),
                "snippet": detail.get("snippet","")[:120],
                "ts": hdrs.get("Date",""),
            })
        return out
    except Exception:
        return []

# ── Feature 6: Zone performance ────────────────────────────────────────────────

def get_zone_stats(sms_logs, send_logs=None, sg_clickers=None):
    zp = SCRIPT_DIR / "zone_state.json"
    if not zp.exists(): return []
    try:
        zs = json.load(open(zp))
    except Exception:
        return []
    completed = zs.get("completed", [])
    if not completed: return []

    date_to_zone = {e.get("date",""): e.get("zone","") for e in completed if e.get("date") and e.get("zone")}

    zone_counts = {}
    for row in sms_logs:
        if row.get("status") != "sent": continue
        ts    = row.get("timestamp","")
        date  = ts[:10] if len(ts) >= 10 else ""
        zone  = date_to_zone.get(date)
        if not zone: continue
        if zone not in zone_counts:
            zone_counts[zone] = {"sent": 0, "phones": set(), "emails": set()}
        zone_counts[zone]["sent"] += 1
        p = row.get("phone","")
        if p: zone_counts[zone]["phones"].add(p)

    # Email counts per zone — cross-reference send_logs by date
    for row in (send_logs or []):
        if row.get("status") != "sent": continue
        ts   = row.get("timestamp","")
        date = ts[:10] if len(ts) >= 10 else ""
        zone = date_to_zone.get(date)
        if not zone: continue
        if zone not in zone_counts:
            zone_counts[zone] = {"sent": 0, "phones": set(), "emails": set()}
        em = row.get("email_sent_to","").strip().lower()
        if em: zone_counts[zone]["emails"].add(em)

    sg_clickers = sg_clickers or {}

    result = []
    for entry in completed:
        zone  = entry.get("zone","")
        date  = entry.get("date","")
        stats = zone_counts.get(zone, {"sent": 0, "phones": set(), "emails": set()})
        zone_emails    = stats.get("emails", set())
        emails_sent    = len(zone_emails)
        emails_opened  = sum(1 for e in zone_emails if (sg_clickers.get(e) or {}).get("opens", 0) > 0)
        emails_clicked = sum(1 for e in zone_emails if (sg_clickers.get(e) or {}).get("clicks", 0) > 0)
        result.append({
            "zone":         zone,
            "date":         date,
            "sent":         stats["sent"],
            "businesses":   len(stats["phones"]),
            "emails_sent":  emails_sent,
            "open_rate":    round(emails_opened / emails_sent * 100) if emails_sent else 0,
            "click_rate":   round(emails_clicked / emails_sent * 100) if emails_sent else 0,
        })
    return result

# ── Feature 8: Automation health ───────────────────────────────────────────────

def get_automation_health():
    log_path = SCRIPT_DIR / "cron_run.log"
    if not log_path.exists():
        return {"status": "unknown", "hours_ago": None, "last_line": "No log file"}
    try:
        text  = log_path.read_text(encoding="utf-8", errors="replace").strip()
        lines = text.split("\n") if text else []
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
        hours_ago = round((datetime.now() - mtime).total_seconds() / 3600, 1)
        tail  = "\n".join(lines[-15:]).lower()
        status = "error" if ("error" in tail or "traceback" in tail) else "ok"
        return {
            "status":    status,
            "hours_ago": hours_ago,
            "last_line": lines[-1].strip()[:100] if lines else "",
            "last_run":  mtime.strftime("%-I:%M %p, %b %-d"),
        }
    except Exception as e:
        return {"status": "error", "hours_ago": None, "last_line": str(e)}

# ── Prospect index ──────────────────────────────────────────────────────────────

def load_prospect_index():
    index = {}
    for p in sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv")):
        for row in load_csv(p):
            name = row.get("name","").strip().lower()
            if name and name not in index:
                index[name] = row
    return index

def get_category_breakdown(sms_logs, send_logs):
    """Per-category SMS + email counts, top 15 by volume."""
    sms_cats   = Counter()
    email_cats = Counter()
    for r in sms_logs:
        if r.get("status") == "sent":
            sms_cats[(r.get("category","") or "other").strip().lower()] += 1
    for r in send_logs:
        if r.get("status") == "sent":
            email_cats[(r.get("category","") or "other").strip().lower()] += 1
    cats = set(list(sms_cats) + list(email_cats))
    result = sorted(
        [{"category": c, "sms": sms_cats.get(c,0), "email": email_cats.get(c,0),
          "total": sms_cats.get(c,0)+email_cats.get(c,0)} for c in cats],
        key=lambda x: -x["total"]
    )
    return result[:15]

def get_daily_sms_counts(sms_logs):
    """Per-day SMS send counts from local logs."""
    counts = Counter()
    for r in sms_logs:
        if r.get("status") == "sent":
            date = (r.get("timestamp","") or "")[:10]
            if date:
                counts[date] += 1
    return [{"date": d, "sms": c} for d, c in sorted(counts.items())]

def get_revenue_forecast(send_logs, pipeline):
    """Project monthly revenue based on current funnel metrics."""
    sent_by_date: dict = {}
    for r in send_logs:
        if r.get("status") != "sent": continue
        d = (r.get("timestamp") or "")[:10]
        if d: sent_by_date[d] = sent_by_date.get(d, 0) + 1
    if not sent_by_date: return {}

    dates        = sorted(sent_by_date.keys())
    total_sent   = sum(sent_by_date.values())
    first        = datetime.strptime(dates[0],  "%Y-%m-%d")
    last_d       = datetime.strptime(dates[-1], "%Y-%m-%d")
    days_active  = max(1, (last_d - first).days + 1)

    cutoff_30    = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    recent_sent  = sum(v for d, v in sent_by_date.items() if d >= cutoff_30)
    recent_days  = sum(1 for d in dates if d >= cutoff_30) or 1
    daily_rate   = recent_sent / recent_days

    warm  = pipeline.get("warm", 0)
    won   = pipeline.get("won",  0)

    using_defaults = total_sent < 30 or warm < 5
    warm_rate  = (warm / total_sent) if not using_defaults else 0.025
    close_rate = (won  / warm)       if (warm >= 5 and won > 0) else 0.20

    monthly_sends     = round(daily_rate * 30)
    projected_closes  = monthly_sends * warm_rate * close_rate
    projected_revenue = round(projected_closes * SITE_PRICE)

    return {
        "daily_sends":       round(daily_rate, 1),
        "monthly_sends":     monthly_sends,
        "warm_rate_pct":     round(warm_rate  * 100, 1),
        "close_rate_pct":    round(close_rate * 100, 1),
        "projected_closes":  round(projected_closes, 1),
        "projected_revenue": projected_revenue,
        "using_defaults":    using_defaults,
        "days_active":       days_active,
    }


def get_bounce_domains(bounces):
    """Return top 15 email domains with the most bounces."""
    from collections import Counter as _C
    counts = _C()
    for b in bounces:
        email = (b.get("email") or "").lower().strip()
        if "@" in email:
            domain = email.split("@")[-1]
            if domain:
                counts[domain] += 1
    return [{"domain": d, "count": c} for d, c in counts.most_common(15)]


def fix_bounce_timestamps(bounces):
    fixed = []
    for b in bounces:
        ts = b.get("timestamp","")
        try:
            if ts.isdigit():
                b = dict(b)
                b["timestamp"] = datetime.fromtimestamp(int(ts)).isoformat(timespec="seconds")
        except Exception:
            pass
        fixed.append(b)
    return fixed

# ── Build dataset ───────────────────────────────────────────────────────────────

STOP_WORDS   = {"stop","stopall","unsubscribe","cancel","end","quit"}
AUTO_SIGNALS = ["out of the office","configure your number","twilio","if this is a medic",
                "do not reply","away from the office"]

def categorize(msgs):
    stops, auto, real = [], [], []
    for m in msgs:
        body = m.get("body","")
        if body.strip().lower() in STOP_WORDS: stops.append(m)
        elif any(s in body.lower() for s in AUTO_SIGNALS): auto.append(m)
        else: real.append(m)
    return real, stops, auto

def build_dataset():
    sms_logs   = all_logs("sms_log_*.csv")
    send_logs  = all_email_logs()          # unified: outreach + followups + clickers + seasonal
    bounces    = fix_bounce_timestamps(load_csv(SCRIPT_DIR / "bounce_log.csv"))
    backlog    = load_csv(SCRIPT_DIR / "backlog_unsent_emails.csv")
    inbound    = fetch_inbound()
    sg_stats   = fetch_sg_stats()
    sg_daily   = fetch_sg_daily()
    sms_delivery = fetch_twilio_delivery_stats()
    sg_clickers  = fetch_sg_clickers()
    clicker_emails = set(sg_clickers.keys())
    suppressed = fetch_suppressed()
    statuses   = load_statuses()
    queue      = load_followup_queue()
    prospects  = load_prospect_index()
    automation = get_automation_health()
    zone_stats      = get_zone_stats(sms_logs, send_logs, sg_clickers)
    bounce_domains  = get_bounce_domains(bounces)
    cat_breakdown = get_category_breakdown(sms_logs, send_logs)
    daily_sms     = get_daily_sms_counts(sms_logs)
    today         = datetime.now().strftime("%Y-%m-%d")
    sg_today      = next((d["sent"] for d in sg_daily if d["date"]==today), 0)

    real_replies, opt_outs, auto_replies = categorize(inbound)
    replied_phones    = {m["from"] for m in real_replies}
    opted_out_phones  = {m["from"] for m in opt_outs}

    email_by_name = {}
    for row in send_logs:
        if row.get("status") == "sent":
            n = row.get("name","").strip().lower()
            if n and n not in email_by_name:
                email_by_name[n] = row.get("email_sent_to","").strip()

    leads = {}
    for row in sms_logs:
        p = row.get("phone","").strip()
        if not p: continue
        if p not in leads:
            name  = row.get("name","")
            pr    = prospects.get(name.strip().lower(), {})
            email = email_by_name.get(name.strip().lower(),"") or pr.get("email","")
            leads[p] = {
                "phone": p, "name": name,
                "category":    row.get("category","") or pr.get("category",""),
                "address":     pr.get("address",""),
                "maps_url":    pr.get("maps_url",""),
                "email":       email,
                "clicked":     email.lower() in clicker_emails,
                "click_data":  sg_clickers.get(email.lower(), {}),
                "sms_sent": 0, "email_sent": 0,
                "replied": False, "opted_out": False,
                "last_contact": "", "touches": [],
                "status": "contacted", "note": "",
                "rating":  pr.get("rating",""),
                "reviews": pr.get("review_count",""),
            }
        if row.get("status") == "sent":
            leads[p]["sms_sent"] += 1
            leads[p]["last_contact"] = row.get("timestamp","")
        leads[p]["touches"].append({
            "type": "sms_out", "ts": row.get("timestamp",""),
            "note": "SMS sent" if row.get("status")=="sent" else row.get("status","")
        })

    for row in send_logs:
        if row.get("status") != "sent": continue
        name  = row.get("name","").strip()
        email = row.get("email_sent_to","").strip()
        matched = next((v for v in leads.values() if v["name"].lower()==name.lower()), None)
        if matched:
            matched["email_sent"] += 1
            matched["touches"].append({"type":"email_out","ts":row.get("timestamp",""),"note":email})

    for m in inbound:
        frm = m.get("from","")
        ts  = m.get("date_sent","")
        if frm not in leads: continue
        if frm in replied_phones:
            leads[frm]["replied"] = True
            leads[frm]["status"]  = "warm"
        if frm in opted_out_phones:
            leads[frm]["opted_out"] = True
            leads[frm]["status"]    = "opted_out"
        leads[frm]["touches"].append({"type":"sms_in","ts":ts,"note":m.get("body","")[:100]})

    for phone, s in statuses.items():
        if phone in leads:
            leads[phone]["status"] = s["status"]
            leads[phone]["note"]   = s.get("note","")

    for l in leads.values():
        l["touches"].sort(key=lambda x: x.get("ts",""))

    # Feature 9: duplicates
    phone_counts = Counter(r.get("phone","") for r in sms_logs if r.get("status")=="sent")
    dup_phones   = {p for p, c in phone_counts.items() if c > 1}

    # Cross-zone dedup flags (from dedup_check.py output or live scan)
    dedup_flags = load_csv(SCRIPT_DIR / "dedup_flags.csv") if (SCRIPT_DIR / "dedup_flags.csv").exists() else []

    # Overdue leads — clickers flagged at 2 days, everyone else at 7 days
    now     = datetime.now()
    overdue = []
    for l in leads.values():
        if l["status"] in ("opted_out","booked","not_interested","won"): continue
        lc = l.get("last_contact","")
        if not lc: continue
        try:
            last      = datetime.fromisoformat(lc)
            threshold = timedelta(days=2) if l.get("clicked") else timedelta(days=7)
            if last < (now - threshold):
                overdue.append({
                    "phone":    l["phone"], "name": l["name"],
                    "category": l["category"],
                    "days_ago": (now - last).days,
                    "clicked":  l.get("clicked", False),
                })
        except Exception:
            pass

    # Feature 5: pipeline
    all_list = list(leads.values())
    pipeline = {
        "contacted": sum(1 for l in all_list if l["status"]=="contacted"),
        "warm":      sum(1 for l in all_list if l["status"]=="warm"),
        "booked":    sum(1 for l in all_list if l["status"]=="booked"),
        "won":       sum(1 for l in all_list if l["status"]=="won"),
    }

    revenue_forecast = get_revenue_forecast(send_logs, pipeline)
    warm        = [l for l in all_list if l["replied"] and not l["opted_out"]]
    total_sms   = sum(1 for r in sms_logs  if r.get("status")=="sent")
    _sent       = [r for r in send_logs    if r.get("status")=="sent"]
    total_email = len(_sent)
    email_by_type = {
        "outreach":    sum(1 for r in _sent if r.get("log_type")=="outreach"),
        "followup":    sum(1 for r in _sent if r.get("log_type")=="followup"),
        "clicker":     sum(1 for r in _sent if r.get("log_type")=="clicker"),
        "reengagement":sum(1 for r in _sent if r.get("log_type")=="reengagement"),
        "seasonal":    sum(1 for r in _sent if r.get("log_type")=="seasonal"),
    }
    backlog_ct  = sum(1 for b in backlog    if b.get("email","").strip())
    clicker_leads = [l for l in all_list if l.get("clicked") and l["status"] not in ("opted_out","won")]
    real_clickers = [l for l in clicker_leads if not l.get("click_data",{}).get("likely_bot")]

    email_to_name  = {row.get("email_sent_to","").strip().lower(): row.get("name","")
                      for row in send_logs
                      if row.get("status")=="sent" and row.get("email_sent_to")}
    gmail_replies  = fetch_gmail_replies(email_to_name)

    # ── Provider breakdown (today) ──────────────────────────────────────────
    today_str = datetime.now().strftime("%Y-%m-%d")
    today_sent = [r for r in send_logs if r.get("status")=="sent" and r.get("date","").startswith(today_str)]
    seasonal_today = []
    for p in sorted(SCRIPT_DIR.glob("seasonal_log_*.csv")):
        try:
            for row in load_csv(p):
                if row.get("date","").startswith(today_str) and str(row.get("dry_run","1")) == "0":
                    seasonal_today.append(row)
        except Exception:
            pass

    provider_today = {
        "sendgrid": sum(1 for r in today_sent if r.get("provider","sendgrid") in ("sendgrid","")),
        "brevo":    sum(1 for r in today_sent if r.get("provider","") == "brevo"),
        "gmail":    sum(1 for r in today_sent if r.get("provider","") == "gmail"),
        "seasonal": len(seasonal_today),
    }

    # Read persisted exhaustion state
    _limit_file = Path.home() / ".webbymaaya/provider_limits.json"
    try:
        _limit_data = json.loads(_limit_file.read_text())
        provider_exhausted = {p: (d == today_str) for p, d in _limit_data.items()}
    except Exception:
        provider_exhausted = {}

    # ── Instagram stats ──────────────────────────────────────────────────────
    _ig_state_path = SCRIPT_DIR / ".instagram_state.json"
    try:
        _ig = json.loads(_ig_state_path.read_text())
        ig_stats = {
            "post_count":   _ig.get("post_count", 0),
            "last_posted":  _ig.get("last_posted", ""),
            "caption_index": _ig.get("caption_index", 0),
        }
    except Exception:
        ig_stats = {"post_count": 0, "last_posted": "", "caption_index": 0}

    # Next IG post day (Mon=0, Wed=2, Fri=4)
    from datetime import date as _date
    _today_dow = _date.today().weekday()
    _post_days = [0, 2, 4]
    _next_post_day = next((d for d in _post_days if d > _today_dow), _post_days[0])
    _days_until = (_next_post_day - _today_dow) % 7 or 7
    ig_stats["next_post_in_days"] = _days_until

    return {
        "intakes":      fetch_intake_responses(),
        "leads":        all_list,
        "sms_logs":     sms_logs,
        "send_logs":    send_logs,
        "bounces":      bounces,
        "inbound":      inbound,
        "real_replies": real_replies,
        "opt_outs":     opt_outs,
        "auto_replies": auto_replies,
        "gmail_replies": gmail_replies,
        "warm":         warm,
        "sg_stats":     sg_stats,
        "sg_daily":     sg_daily,
        "sg_today":     sg_today,
        "sg_limit":     100,
        "suppressed":   list(suppressed),
        "queue":        queue,
        "dup_phones":   list(dup_phones),
        "dedup_flags":  dedup_flags,
        "overdue":      sorted(overdue, key=lambda x: -x["days_ago"]),
        "pipeline":     pipeline,
        "backlog_count": backlog_ct,
        "zone_stats":        zone_stats,
        "automation":        automation,
        "revenue_forecast":  revenue_forecast,
        "bounce_domains":    bounce_domains,
        "revenue_history":   get_revenue_history(),
        "projects":          _load_projects(),
        "sms_delivery":   sms_delivery,
        "cat_breakdown":  cat_breakdown,
        "daily_sms":      daily_sms,
        "clicker_leads":  real_clickers,
        "clicker_data":   sg_clickers,
        "provider_today":     provider_today,
        "provider_exhausted": provider_exhausted,
        "ig_stats":           ig_stats,
        "stats": {
            "total_sms":      total_sms,
            "total_email":    total_email,
            "email_by_type":  email_by_type,
            "warm":           len(warm),
            "replies":        len(real_replies),
            "opt_outs":       len(opt_outs),
            "bounces":        len(bounces),
            "opens":          sg_stats.get("opens",0),
            "clicks":         sg_stats.get("clicks",0),
            "clicker_count":  len(real_clickers),
        }
    }

# ── HTML ────────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WebByMaya Console</title>
<style>
/* ── Reset & Base ─────────────────────────────────────────────────────────── */
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0a0a0a;color:#d8d8d8;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;font-size:13px;line-height:1.5;display:flex;flex-direction:column;height:100vh;overflow:hidden}
a{color:#C9A96E;text-decoration:none}
a:hover{color:#dbbe8a}

/* ── Header ──────────────────────────────────────────────────────────────── */
header{background:#0f0f0f;border-bottom:1px solid #1e1e1e;padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:16px}
header h1{font-family:Georgia,serif;color:#C9A96E;font-size:16px;letter-spacing:.8px;white-space:nowrap;font-weight:normal}
.hdr-center{display:flex;align-items:center;gap:12px;flex:1;justify-content:center}
.hdr-right{display:flex;align-items:center;gap:10px;flex-shrink:0}
.hdr-right span{color:#444;font-size:11px}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
.btn{background:#C9A96E;color:#111;border:none;padding:7px 14px;border-radius:4px;cursor:pointer;font-weight:600;font-size:12px;letter-spacing:.2px;transition:background .15s;white-space:nowrap;flex-shrink:0}
.btn:hover{background:#d8bb82}
.btn-sm{padding:5px 11px;font-size:11px}
.btn-outline{background:transparent;border:1px solid #333;color:#aaa}
.btn-outline:hover{border-color:#C9A96E;color:#C9A96E;background:transparent}
.btn-danger{background:#a93226;color:#fff}
.btn-danger:hover{background:#c0392b}
.btn-green{background:#1e7e45;color:#fff}
.btn-green:hover{background:#27ae60}
.btn-blue{background:#1a5f8a;color:#fff}
.btn-blue:hover{background:#2980b9}

/* ── Pills / health ──────────────────────────────────────────────────────── */
.health-pill{display:flex;align-items:center;gap:6px;font-size:11px;color:#555;background:#141414;padding:5px 11px;border-radius:20px;border:1px solid #1c1c1c;white-space:nowrap}
.health-dot{width:6px;height:6px;border-radius:50%;flex-shrink:0}
.health-dot.ok{background:#2ecc71}
.health-dot.error{background:#e74c3c}
.health-dot.unknown{background:#555}

/* ── Layout ──────────────────────────────────────────────────────────────── */
.main{display:flex;flex:1;overflow:hidden}
.sidebar{width:200px;background:#0f0f0f;border-right:1px solid #181818;display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto;padding:8px 0}
.nav-item{padding:9px 16px;cursor:pointer;color:#555;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;border-left:2px solid transparent;display:flex;align-items:center;justify-content:space-between;transition:color .15s,background .15s;margin:1px 0}
.nav-item:hover{color:#bbb;background:#151515}
.nav-item.active{color:#C9A96E;border-left-color:#C9A96E;background:#141414}
.nav-divider{height:1px;background:#181818;margin:6px 16px}
.badge-count{background:#333;color:#aaa;border-radius:10px;padding:1px 7px;font-size:10px;font-weight:700}
.badge-count.red{background:#7a1f1f;color:#e87070}
.badge-count.blue{background:#1a3a5a;color:#6aafe6}
.badge-count.gold{background:#3a2a00;color:#C9A96E}
.content{flex:1;overflow-y:auto;padding:22px 28px}

/* ── Pipeline ────────────────────────────────────────────────────────────── */
.pipeline{display:grid;grid-template-columns:repeat(4,1fr);margin-bottom:18px;border:1px solid #1c1c1c;border-radius:8px;overflow:hidden;background:#111}
.pipe-step{padding:16px 12px;text-align:center;border-right:1px solid #1c1c1c;position:relative}
.pipe-step:last-child{border-right:none}
.pipe-num{font-size:28px;font-weight:700;color:#C9A96E;line-height:1}
.pipe-num.green{color:#27ae60}
.pipe-num.warm{color:#d4a017}
.pipe-num.booked{color:#2980b9}
.pipe-label{color:#444;font-size:10px;text-transform:uppercase;letter-spacing:.6px;margin-top:5px}
.pipe-revenue{background:#0f0f00;border-top:1px solid #1c1c1a;padding:9px 16px;font-size:12px;color:#a88840;text-align:center;grid-column:1/-1}

/* ── Banners ─────────────────────────────────────────────────────────────── */
.banner{border-radius:6px;margin-bottom:14px;padding:12px 16px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px;font-size:13px}
.banner-backlog{background:#130e00;border:1px solid #2e2200;border-left:3px solid #C9A96E}
.banner-backlog .banner-text{color:#aaa}
.banner-backlog .banner-text b{color:#C9A96E}
.banner-nudge{background:#080f17;border:1px solid #152133;border-left:3px solid #2980b9}
.banner-nudge .banner-text{color:#7ab8e8}
.banner-nudge .banner-text b{color:#5aaee0}

/* ── Stats cards ─────────────────────────────────────────────────────────── */
.cards{display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px}
.card{background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:14px 18px;min-width:100px;flex:1;transition:border-color .15s}
.card:hover{border-color:#2a2a2a}
.card-num{font-size:26px;font-weight:700;color:#C9A96E;line-height:1}
.card-num.green{color:#27ae60}
.card-num.red{color:#c0392b}
.card-num.orange{color:#d4a017}
.card-label{color:#555;font-size:10px;margin-top:5px;text-transform:uppercase;letter-spacing:.5px}

/* ── Section titles ──────────────────────────────────────────────────────── */
.section-title{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.section-title::after{content:"";flex:1;height:1px;background:#181818}

/* ── Tables ──────────────────────────────────────────────────────────────── */
.tbl-wrap{overflow-x:auto;border:1px solid #181818;border-radius:8px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{background:#0f0f0f;color:#444;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:10px 14px;text-align:left;border-bottom:1px solid #1a1a1a;position:sticky;top:0;z-index:1;font-weight:600}
td{padding:10px 14px;border-bottom:1px solid #141414;vertical-align:middle;color:#ccc}
tbody tr:last-child td{border-bottom:none}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:#131313}
tr.overdue td{background:#0f0c00}
tr.overdue:hover td{background:#181200}
.tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:.3px}
.empty{color:#333;text-align:center;padding:52px;font-size:13px}
.notice{background:#111;border:1px solid #1c1c1c;border-left:3px solid #C9A96E;padding:11px 15px;border-radius:6px;margin-bottom:14px;font-size:12px;color:#666;line-height:1.6}

/* ── Lead Panel ──────────────────────────────────────────────────────────── */
#panel-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;backdrop-filter:blur(2px)}
#panel-overlay.open{display:block}
#lead-panel{position:fixed;right:-520px;top:0;bottom:0;width:520px;background:#0f0f0f;border-left:1px solid #1e1e1e;z-index:101;transition:right .22s ease;display:flex;flex-direction:column;overflow:hidden}
#lead-panel.open{right:0}
#panel-header{background:#0a0a0a;border-bottom:1px solid #1a1a1a;padding:18px 20px;display:flex;align-items:flex-start;justify-content:space-between}
#panel-close{background:none;border:none;color:#444;font-size:20px;cursor:pointer;line-height:1;padding:2px 6px;border-radius:3px}
#panel-close:hover{color:#fff;background:#1a1a1a}
#panel-body{flex:1;overflow-y:auto;padding:18px 20px}
.panel-section{margin-bottom:20px}
.panel-section-title{color:#444;font-size:10px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px;padding-bottom:6px;border-bottom:1px solid #181818}
.info-grid{display:grid;grid-template-columns:96px 1fr;gap:6px 12px}
.info-label{color:#555;font-size:12px}
.info-val{color:#ccc;font-size:12px}
.touch-item{display:flex;gap:12px;padding:8px 0;border-bottom:1px solid #141414}
.touch-dot{width:7px;height:7px;border-radius:50%;margin-top:5px;flex-shrink:0}
.touch-meta{font-size:11px;color:#555;margin-top:2px}
.action-bar{padding:14px 20px;border-top:1px solid #1a1a1a;display:flex;flex-wrap:wrap;gap:7px;background:#0a0a0a}
.sms-compose{width:100%;background:#141414;border:1px solid #222;color:#ccc;padding:9px 11px;border-radius:4px;font-size:12px;resize:vertical;min-height:68px;font-family:inherit;transition:border-color .15s}
.sms-compose:focus{outline:none;border-color:#333}
.note-area{width:100%;background:#141414;border:1px solid #222;color:#ccc;padding:9px 11px;border-radius:4px;font-size:12px;resize:vertical;min-height:56px;font-family:inherit;transition:border-color .15s}
.note-area:focus{outline:none;border-color:#333}

/* ── Queue / warm cards ──────────────────────────────────────────────────── */
.queue-item{background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:13px 16px;margin-bottom:8px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:14px;transition:border-color .15s}
.queue-item:hover{border-color:#2a2a2a}
.queue-info h4{font-size:14px;color:#ddd;margin-bottom:3px;font-weight:600}
.queue-info span{font-size:12px;color:#555}

/* ── Toast ───────────────────────────────────────────────────────────────── */
#toast{position:fixed;bottom:24px;right:24px;background:#C9A96E;color:#111;padding:11px 18px;border-radius:6px;font-weight:700;font-size:12px;display:none;z-index:200;box-shadow:0 4px 20px rgba(0,0,0,.5)}
</style>
</head>
<body>

<header>
  <h1>WebByMaya — Outreach Console</h1>
  <div class="hdr-center" id="hdr-health"></div>
  <div class="hdr-right" style="gap:10px">
    <div id="hdr-credit"></div>
    <span id="last-updated"></span>
    <button class="btn" onclick="location.reload()">↻ Refresh</button>
  </div>
</header>

<div class="main">
  <div class="sidebar">
    <div class="nav-item active" onclick="showPage('warm')" id="nav-warm">
      Warm Leads <span class="badge-count red" id="badge-warm">0</span>
    </div>
    <div class="nav-item" onclick="showPage('responses')" id="nav-responses">
      Responses <span class="badge-count" id="badge-responses">0</span>
    </div>
    <div class="nav-item" onclick="showPage('queue')" id="nav-queue">
      Follow-ups <span class="badge-count gold" id="badge-queue">0</span>
    </div>
    <div class="nav-item" onclick="showPage('all-leads')" id="nav-all-leads">
      All Leads <span class="badge-count blue" id="badge-dups" style="display:none"></span>
    </div>
    <div class="nav-divider"></div>
    <div class="nav-item" onclick="showPage('analytics')" id="nav-analytics">Analytics</div>
    <div class="nav-item" onclick="showPage('zones')" id="nav-zones">Zones</div>
    <div class="nav-item" onclick="showPage('projects')" id="nav-projects">
      Projects <span class="badge-count gold" id="badge-projects">0</span>
    </div>
    <div class="nav-item" onclick="showPage('revenue')" id="nav-revenue">Revenue Log</div>
    <div class="nav-divider"></div>
    <div class="nav-item" onclick="showPage('sms')" id="nav-sms">SMS Log</div>
    <div class="nav-item" onclick="showPage('email')" id="nav-email">Email Log</div>
    <div class="nav-item" onclick="showPage('bounces')" id="nav-bounces">Bounces</div>
    <div class="nav-divider"></div>
    <div class="nav-item" onclick="showPage('intake')" id="nav-intake">
      Intake Forms <span class="badge-count gold" id="badge-intake">0</span>
    </div>
  </div>

  <div class="content" id="main-content">

    <!-- Pipeline (always visible) -->
    <div id="pipeline-row" style="margin-bottom:18px"></div>

    <!-- Backlog banner -->
    <div id="backlog-banner" style="display:none"></div>

    <!-- Overdue nudge (shown on warm/all-leads) -->
    <div id="nudge-bar" style="display:none"></div>

    <!-- Hot clicker alert (always shown when clickers exist) -->
    <div id="clicker-alert" style="display:none"></div>

    <!-- SMS 10DLC critical warning -->
    <div id="sms-alert" style="display:none"></div>

    <!-- Stats cards -->
    <div class="cards" id="stats-cards"></div>

    <!-- Conversion funnel -->
    <div id="funnel-row" style="margin-bottom:14px"></div>

    <!-- Revenue forecast -->
    <div id="forecast-row" style="margin-bottom:20px"></div>

    <!-- Warm Leads -->
    <div id="page-warm">
      <p class="section-title">Warm Leads — replied or took action</p>
      <div id="warm-list"></div>
    </div>

    <!-- Responses -->
    <div id="page-responses" style="display:none">
      <p class="section-title">All Inbound Messages</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Channel</th><th>Type</th><th>Business</th><th>Message / Subject</th><th></th></tr></thead>
        <tbody id="responses-body"></tbody>
      </table></div>
    </div>

    <!-- Follow-up Queue -->
    <div id="page-queue" style="display:none">
      <p class="section-title">Scheduled Follow-ups</p>
      <div id="queue-list"></div>
    </div>

    <!-- All Leads -->
    <div id="page-all-leads" style="display:none">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
        <p class="section-title" style="margin:0">All Contacts</p>
        <input id="lead-search" type="text" placeholder="Search name or category..."
          oninput="filterLeads()"
          style="background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:6px 12px;border-radius:3px;font-size:13px;width:240px">
        <label style="color:#7ed321;font-size:12px;cursor:pointer;font-weight:600">
          <input type="checkbox" id="show-clickers" onchange="filterLeads()" style="margin-right:4px">
          🔥 Clickers only
        </label>
        <label style="color:#888;font-size:12px;cursor:pointer">
          <input type="checkbox" id="show-dups" onchange="filterLeads()" style="margin-right:4px">
          Duplicates only
        </label>
        <label style="color:#888;font-size:12px;cursor:pointer">
          <input type="checkbox" id="show-overdue" onchange="filterLeads()" style="margin-right:4px">
          Overdue (7d+)
        </label>
      </div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Business</th><th>Category</th><th>Status</th><th>SMS</th><th>Email</th><th>Replied</th><th>Last Contact</th><th></th></tr></thead>
        <tbody id="all-leads-body"></tbody>
      </table></div>
    </div>

    <!-- Zones -->
    <div id="page-zones" style="display:none">
      <p class="section-title">Zone Performance</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Zone</th><th>Date Run</th><th>Businesses</th><th>SMS Sent</th><th>Emails Sent</th><th>Open %</th><th>Click %</th></tr></thead>
        <tbody id="zones-body"></tbody>
      </table></div>
    </div>

    <!-- SMS Log -->
    <div id="page-sms" style="display:none">
      <p class="section-title">SMS Send Log (most recent first)</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Phone</th><th>Status</th></tr></thead>
        <tbody id="sms-body"></tbody>
      </table></div>
    </div>

    <!-- Email Log -->
    <div id="page-email" style="display:none">
      <div class="notice">Email replies → <strong>maya@webbymaya.com</strong>
        &nbsp;<a href="https://mail.google.com" target="_blank">Open Gmail →</a></div>
      <p class="section-title">Email Send Log (most recent first)</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Email</th><th>Status</th></tr></thead>
        <tbody id="email-body"></tbody>
      </table></div>
    </div>

    <!-- Bounces -->
    <div id="page-bounces" style="display:none">
      <p class="section-title">Bounce & Suppression List</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Email</th><th>Type</th><th>Reason</th></tr></thead>
        <tbody id="bounces-body"></tbody>
      </table></div>
    </div>

    <!-- Intake Forms -->
    <div id="page-intake" style="display:none">
      <p class="section-title">Website Intake Form Submissions (webbymaya.com/book)</p>
      <div id="intake-list"></div>
    </div>

    <!-- Analytics -->
    <div id="page-analytics" style="display:none">
      <p class="section-title">Outreach Performance Breakdown</p>
      <div id="analytics-rates"></div>

      <p class="section-title" style="margin-top:24px;margin-bottom:12px">Daily Outreach Activity</p>
      <div id="analytics-chart" style="background:#141414;border:1px solid #222;border-radius:6px;padding:16px;margin-bottom:24px"></div>

      <div style="display:flex;gap:20px;flex-wrap:wrap">
        <div style="flex:1;min-width:280px">
          <p class="section-title">Email Performance by Day</p>
          <div class="tbl-wrap"><table>
            <thead><tr><th>Date</th><th>Sent</th><th>Opens</th><th>Clicks</th><th>Bounces</th></tr></thead>
            <tbody id="sg-daily-body"></tbody>
          </table></div>
        </div>
        <div style="flex:1;min-width:280px">
          <p class="section-title">Outreach by Category</p>
          <div class="tbl-wrap"><table>
            <thead><tr><th>Category</th><th>SMS</th><th>Email</th><th>Total</th></tr></thead>
            <tbody id="cat-breakdown-body"></tbody>
          </table></div>
        </div>
      </div>

      <p class="section-title" style="margin-top:28px">SMS Delivery Health (Twilio — last 1,000 sent)</p>
      <div id="sms-health-section"></div>

      <p class="section-title" style="margin-top:28px">Top Bounce Domains</p>
      <div id="bounce-domains-section"></div>

      <p class="section-title" style="margin-top:28px">Cross-Zone Duplicate Contacts</p>
      <p style="color:#555;font-size:11px;margin-bottom:10px">Run <code>python dedup_check.py --write</code> to refresh. These businesses were reached in multiple zone passes.</p>
      <div id="dedup-section"></div>
    </div>

    <!-- Projects page -->
    <div id="page-projects" style="display:none">
      <p class="section-title">Active Projects</p>
      <p style="color:#555;font-size:11px;margin-bottom:16px">Clients move here automatically when marked Won or Booked</p>
      <div id="projects-board" style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px"></div>
    </div>

    <!-- Revenue log page -->
    <div id="page-revenue" style="display:none">
      <div style="display:flex;gap:20px;flex-wrap:wrap;margin-bottom:24px">
        <div class="card" style="min-width:160px;text-align:center">
          <div style="font-size:28px;font-weight:700;color:#C9A96E" id="rev-total">$0</div>
          <div style="color:#555;font-size:11px;margin-top:4px">Total Earned</div>
        </div>
        <div class="card" style="min-width:160px;text-align:center">
          <div style="font-size:28px;font-weight:700;color:#d8d8d8" id="rev-clients">0</div>
          <div style="color:#555;font-size:11px;margin-top:4px">Clients Won</div>
        </div>
        <div class="card" style="min-width:160px;text-align:center">
          <div style="font-size:28px;font-weight:700;color:#d8d8d8" id="rev-avg">$0</div>
          <div style="color:#555;font-size:11px;margin-top:4px">Avg per Client</div>
        </div>
      </div>
      <p class="section-title" style="margin-bottom:12px">Monthly Breakdown</p>
      <div id="revenue-chart" style="background:#141414;border:1px solid #222;border-radius:6px;padding:16px;margin-bottom:24px"></div>
      <p class="section-title" style="margin-bottom:8px">All Transactions</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Date</th><th>Business</th><th>Category</th><th>Package</th><th>Amount</th></tr></thead>
        <tbody id="revenue-rows"></tbody>
      </table></div>
    </div>

  </div>
</div>

<!-- Lead detail panel -->
<div id="panel-overlay" onclick="closePanel()"></div>
<div id="lead-panel">
  <div id="panel-header">
    <div>
      <h2 id="panel-name" style="color:#C9A96E;font-size:18px;font-family:Georgia,serif"></h2>
      <p id="panel-category" style="color:#888;font-size:13px;margin-top:3px"></p>
    </div>
    <button id="panel-close" onclick="closePanel()">✕</button>
  </div>
  <div id="panel-body"></div>
  <div class="action-bar" id="panel-actions"></div>
</div>

<div id="toast"></div>

<script>
const DATA = __DATA__;
let currentPhone = null;

// ── Response templates ─────────────────────────────────────────────────────────

const TEMPLATES = [
  { keys: ["how much","price","cost","rate","charge","fee"],
    sms: "Sites start at $799 flat — design, mobile build, SEO setup, live in 7 days. Fill out my quick form and I'll send a full breakdown: webbymaya.com/book — Maya",
    email: "Hi,\n\nSites start at $799 flat — that includes the full design, mobile-friendly build, basic SEO setup, and go-live within 7 days. No monthly fees.\n\nEverything's handled by email — fill out my intake form and I'll go over it all: webbymaya.com/book\n\n— Maya" },

  { keys: ["yes","interested","sure","sounds good","tell me more","go ahead","let's do","sign me up","definitely","absolutely","i want","i'd like","set it up"],
    sms: "That's great to hear! Fill out my quick intake form — takes 2 minutes and I'll get started: webbymaya.com/book — Maya",
    email: "Hi,\n\nGreat to hear! I work completely by email — just fill out my short intake form and I'll have a mockup ready fast.\n\nWebbymaya.com/book\n\nCan't wait to get started!\n— Maya" },

  { keys: ["already have","have a website","have one","have a site","got a website","have my own"],
    sms: "Got it! A lot of local business sites are hard to find on Google or look outdated on phones. Happy to take a free look at yours — no obligation. webbymaya.com/book — Maya",
    email: "Hi,\n\nTotally understand! A lot of local business sites I see are hard to find on Google or don't look great on phones, which costs customers.\n\nI'm happy to do a free review of yours — no obligation, just honest feedback. If it's doing great, awesome! If not, I can show you what I'd change.\n\nwebbymaya.com/book\n\n— Maya" },

  { keys: ["not interested","no thanks","no thank","don't need","dont need","leave me alone","remove me","take me off"],
    sms: "No problem at all — I understand! Best of luck with your business. 🙂",
    email: "Hi,\n\nNo problem at all! I completely understand. Best of luck with everything — feel free to reach out if things ever change.\n\n— Maya" },

  { keys: ["how long","when ready","how fast","how quick","turnaround","timeline"],
    sms: "Most sites go live in 7 days! Fill out my form → mockup in 48h → your approval → live. webbymaya.com/book — Maya",
    email: "Hi,\n\nMost sites go live within 7 days. Here's the typical timeline:\n\n• Day 1-2: Fill out my form + I gather your info\n• Day 2-3: I send you a mockup\n• Day 4-5: You review + request any tweaks\n• Day 6-7: Go live!\n\nWant to get started? webbymaya.com/book\n\n— Maya" },

  { keys: ["example","portfolio","show me","can i see","your work","past work","samples"],
    sms: "Check out my work at webbymaya.com! I can also put together a free mockup for your specific business — just say the word. — Maya",
    email: "Hi,\n\nYou can see examples of my work at webbymaya.com.\n\nI can also put together a free mockup specifically for your business — no call needed, just reply 'yes' and I'll get started. Takes me about 20 minutes and you're under no obligation.\n\n— Maya" },

  { keys: ["too expensive","can't afford","cant afford","too much","budget","cheaper","discount","payment plan"],
    sms: "Totally get it! I offer payment plans (2-3 months) and there's no monthly fee. One new customer usually covers the cost. Chat about options? webbymaya.com/book — Maya",
    email: "Hi,\n\nI totally understand — $799 is an investment. A couple of options that might help:\n\n• Payment plans: split over 2-3 months, no interest\n• No ongoing monthly fees ever\n• For most businesses, just one new customer from the site covers the full cost\n\nHappy to talk through what works for you: webbymaya.com/book\n\n— Maya" },

  { keys: ["call me","phone","call you","give me a call","reach me","contact me"],
    sms: "I work entirely via email and my website form — no calls needed! Reply here with any questions, or fill out my form: webbymaya.com/book — Maya",
    email: "Hi,\n\nI work entirely by email — no calls needed! Just reply here with any questions, or fill out my intake form and I'll take it from there: webbymaya.com/book\n\n— Maya" },
];

function suggestReply(body, channel) {
  const b = (body||'').toLowerCase();
  for (const t of TEMPLATES) {
    if (t.keys.some(k => b.includes(k))) {
      return channel === 'email' ? t.email : t.sms;
    }
  }
  return channel === 'email'
    ? "Hi,\n\nThanks for getting back to me! I work completely by email — fill out my quick intake form and I'll get started: webbymaya.com/book\n\n— Maya"
    : "Thanks for getting back to me! Fill out my quick form and I'll take it from there: webbymaya.com/book — Maya";
}

function toggleDraft(id, body, phone, channel, toEmail) {
  const row = document.getElementById('draft-' + id);
  if (row.style.display !== 'none') { row.style.display = 'none'; return; }
  const ta  = document.getElementById('draft-ta-' + id);
  ta.value  = suggestReply(body, channel);
  row.style.display = 'table-row';
  ta.focus();
}

async function generateMockup(phone, name, category, bizPhone, address) {
  const btn = [...document.querySelectorAll('#panel-actions button')].find(b=>b.textContent.includes('Mockup'));
  if (btn) { btn.disabled=true; btn.textContent='Generating…'; }
  const city = address ? address.split(',').slice(-2).join(',').trim() : 'Philadelphia, PA';
  const r = await fetch('/action/generate-mockup', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, category, phone: bizPhone, city})
  });
  const d = await r.json();
  if (btn) { btn.disabled=false; btn.textContent='🖥 Mockup'; }
  if (d.ok) {
    const url = d.url;
    toast('Mockup ready! Opening preview…');
    window.open(url, '_blank');
    // Also show the URL in panel so Maya can copy it
    const notes = document.getElementById('panel-note-txt');
    if (notes && !notes.value.includes('mockup')) {
      notes.value = (notes.value ? notes.value + '\n' : '') + 'Mockup: ' + url;
    }
  } else {
    toast('Mockup error: ' + d.error);
  }
}

async function sendDraftSms(id, phone) {
  const ta = document.getElementById('draft-ta-' + id);
  const body = ta.value.trim();
  if (!body || !phone) return;
  const btn = document.getElementById('draft-send-' + id);
  btn.disabled = true; btn.textContent = 'Sending…';
  const r = await fetch('/action/quick-reply-sms', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone, body})
  });
  const d = await r.json();
  if (d.ok) { toast('Sent!'); document.getElementById('draft-' + id).style.display='none'; }
  else { toast('Error: ' + d.error); btn.disabled=false; btn.textContent='Send SMS'; }
}

function copyDraft(id) {
  const ta = document.getElementById('draft-ta-' + id);
  navigator.clipboard.writeText(ta.value).then(()=>toast('Copied!'));
}

// ── Helpers ────────────────────────────────────────────────────────────────────

function fmtTs(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US',{month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true});
  } catch { return ts.slice(0,16); }
}

function daysAgo(ts) {
  if (!ts) return '—';
  try {
    const days = Math.floor((Date.now() - new Date(ts)) / 86400000);
    if (days === 0) return '<span style="color:#2ecc71">Today</span>';
    if (days < 7)   return days + 'd ago';
    return `<span style="color:#f39c12;font-weight:bold">${days}d ago ⚠</span>`;
  } catch { return '—'; }
}

function tag(text, color) {
  return `<span class="tag" style="background:${color}">${text}</span>`;
}

function statusTag(s) {
  const map={warm:'#f39c12',booked:'#27ae60',won:'#1a7a40',contacted:'#3498db',opted_out:'#888',not_interested:'#c0392b'};
  return tag((s||'contacted').replace(/_/g,' '), map[s]||'#555');
}

function toast(msg, isErr) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.style.background = isErr ? '#c0392b' : '#C9A96E';
  el.style.color = '#111';
  el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 3500);
}

function esc(s) { return (s||'').replace(/\\/g,'\\\\').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }

// ── Clicker alert ─────────────────────────────────────────────────────────────

function renderClickerAlert() {
  const leads = DATA.clicker_leads;
  if (!leads || !leads.length) return;
  const el = document.getElementById('clicker-alert');
  el.style.display = '';
  el.style.cssText = 'background:#0a1200;border:1px solid #1f3500;border-left:3px solid #7ed321;padding:12px 16px;border-radius:6px;margin-bottom:14px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px;font-size:13px';
  const names = leads.slice(0,3).map(l=>`<strong style="color:#a8e060">${l.name}</strong>`).join(', ');
  const more  = leads.length > 3 ? ` +${leads.length-3} more` : '';
  el.innerHTML = `
    <div style="color:#888;line-height:1.6">
      <span style="color:#7ed321;font-weight:700">🔥 ${leads.length} hot lead${leads.length!==1?'s':''} clicked your booking link</span>
      — ${names}${more}
      <span style="color:#555;font-size:11px;margin-left:6px">· follow up within 48h while they're warm</span>
    </div>
    <button class="btn btn-sm" style="background:#4a8a00;color:#fff;border:none"
      onclick="showPage('all-leads');document.getElementById('show-clickers').checked=true;filterLeads()">
      View All →
    </button>`;
}

// ── Automation health ──────────────────────────────────────────────────────────

function renderHealth() {
  const a = DATA.automation;
  if (!a) return;
  const dot   = a.status === 'ok' ? 'ok' : a.status === 'error' ? 'error' : 'unknown';
  const label = a.status === 'ok'
    ? `Cron OK · ${a.hours_ago}h ago`
    : a.status === 'error'
    ? `Cron ERROR · ${a.hours_ago}h ago`
    : 'Cron unknown';
  document.getElementById('hdr-health').innerHTML =
    `<div class="health-pill" title="${esc(a.last_line||'')}">
       <div class="health-dot ${dot}"></div>${label}
     </div>`;
}

// ── Pipeline ───────────────────────────────────────────────────────────────────

function renderPipeline() {
  const p = DATA.pipeline;
  const revenue = (p.booked + p.won) * ${SITE_PRICE};
  document.getElementById('pipeline-row').innerHTML = `
    <div class="pipeline">
      <div class="pipe-step">
        <div class="pipe-num">${p.contacted.toLocaleString()}</div>
        <div class="pipe-label">Contacted</div>
      </div>
      <div class="pipe-step">
        <div class="pipe-num warm">${p.warm}</div>
        <div class="pipe-label">Warm</div>
      </div>
      <div class="pipe-step">
        <div class="pipe-num booked">${p.booked}</div>
        <div class="pipe-label">Booked</div>
      </div>
      <div class="pipe-step">
        <div class="pipe-num green">${p.won}</div>
        <div class="pipe-label">Won</div>
      </div>
      ${(p.won > 0 || p.booked > 0) ? `<div class="pipe-revenue">
        ${p.won > 0 ? `<span style="color:#2ecc71;font-weight:600">$${(p.won*${SITE_PRICE}).toLocaleString()} earned</span><span style="color:#333;margin:0 10px">|</span>` : ''}
        ${p.booked > 0 ? `<span style="color:#a88840">$${(p.booked*${SITE_PRICE}).toLocaleString()} committed</span><span style="color:#333;margin:0 10px">|</span>` : ''}
        <span style="color:#555">${p.booked + p.won} client${p.booked+p.won!==1?'s':''} × $${SITE_PRICE}</span>
      </div>` : ''}
    </div>`;
}

// ── Backlog banner ─────────────────────────────────────────────────────────────

function renderBacklog() {
  const ct = DATA.backlog_count;
  if (!ct) return;
  const el = document.getElementById('backlog-banner');
  el.style.display = '';
  el.className = 'banner banner-backlog';
  el.innerHTML = `
    <div class="banner-text"><b>${ct} businesses</b> have an email on file but haven't been contacted yet</div>
    <button class="btn btn-sm" onclick="alert('Run in terminal:\\n\\npython3 ~/webbymaaya-scripts/batch_send_outreach.py')">
      View Backlog
    </button>`;
}

// ── Overdue nudge ──────────────────────────────────────────────────────────────

function renderNudge() {
  const ct = DATA.overdue.length;
  if (!ct) return;
  const el = document.getElementById('nudge-bar');
  el.style.display = '';
  el.className = 'banner banner-nudge';
  el.innerHTML = `
    <div class="banner-text"><b>${ct} leads</b> haven't been touched in 7+ days — ready to queue for follow-up</div>
    <button class="btn btn-sm btn-blue" onclick="queueAllOverdue()">Queue All (${ct})</button>`;
}

// ── Stats cards ────────────────────────────────────────────────────────────────

function renderStats() {
  const s   = DATA.stats;
  const sg  = DATA.sg_stats;
  const del = sg.delivered || 0;
  const openPct = del ? Math.round(sg.opens / del * 100) : 0;
  const unlogged = (sg.requests||0) - s.total_email;

  document.getElementById('stats-cards').innerHTML = `
    ${s.clicker_count > 0 ? `
    <div class="card" style="border-color:#2a4a00;cursor:pointer" onclick="showPage('all-leads');document.getElementById('show-clickers').checked=true;filterLeads()">
      <div class="card-num" style="color:#7ed321">${s.clicker_count}</div>
      <div class="card-label">🔥 Hot Clickers</div>
      <div style="color:#3a5a00;font-size:10px;margin-top:4px">clicked booking link</div>
    </div>` : ''}
    <div class="card"><div class="card-num orange">${s.warm}</div><div class="card-label">Warm Leads</div></div>
    <div class="card">
      <div class="card-num">${s.total_sms.toLocaleString()}</div>
      <div class="card-label">SMS Sent (Twilio)</div>
      <div style="color:#555;font-size:10px;margin-top:4px">${s.replies} replied · ${s.opt_outs} opted out</div>
    </div>
    <div class="card">
      <div class="card-num">${s.total_email.toLocaleString()}</div>
      <div class="card-label">Total Emails Sent</div>
      <div style="color:#555;font-size:10px;margin-top:4px;line-height:1.6">
        ${(s.email_by_type||{}).outreach||0} outreach
        ${(s.email_by_type||{}).followup ? '· '+(s.email_by_type.followup)+' follow-up' : ''}
        ${(s.email_by_type||{}).clicker  ? '· '+(s.email_by_type.clicker)+' clicker' : ''}
        ${(s.email_by_type||{}).reengagement ? '· '+(s.email_by_type.reengagement)+' re-eng' : ''}
        ${(s.email_by_type||{}).seasonal ? '· '+(s.email_by_type.seasonal)+' seasonal' : ''}
      </div>
    </div>
    <div class="card">
      <div class="card-num green">${openPct}%</div>
      <div class="card-label">Email Open Rate</div>
      <div style="color:#555;font-size:10px;margin-top:4px">${sg.opens||0} opens · ${sg.clicks||0} clicks</div>
    </div>
    <div class="card"><div class="card-num green">${s.replies}</div><div class="card-label">SMS Replies</div></div>
    <div class="card"><div class="card-num green">${DATA.gmail_replies.length}</div><div class="card-label">Email Replies</div></div>
    <div class="card"><div class="card-num red">${s.opt_outs}</div><div class="card-label">SMS Opt-Outs</div></div>
    <div class="card"><div class="card-num red">${s.bounces}</div><div class="card-label">Email Bounces</div></div>

    ${(() => {
      const pt  = DATA.provider_today || {};
      const ex  = DATA.provider_exhausted || {};
      const ig  = DATA.ig_stats || {};
      const providers = [
        { key:'sendgrid', label:'SendGrid', limit:100,  color:'#2980b9' },
        { key:'brevo',    label:'Brevo',    limit:300,  color:'#27ae60' },
        { key:'gmail',    label:'Gmail',    limit:500,  color:'#e67e22' },
      ];
      const provHTML = providers.map(p => {
        const used = pt[p.key] || 0;
        const pct  = Math.min(100, Math.round(used / p.limit * 100));
        const done = ex[p.key];
        const barColor = done ? '#555' : p.color;
        return `<div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
          <span style="width:58px;font-size:10px;color:#888">${p.label}</span>
          <div style="flex:1;background:#1a1a1a;border-radius:3px;height:6px;overflow:hidden">
            <div style="width:${pct}%;background:${barColor};height:100%;border-radius:3px;transition:width .3s"></div>
          </div>
          <span style="font-size:10px;color:${done?'#555':'#aaa'};width:52px;text-align:right">${used}/${p.limit}${done?' ✓':''}</span>
        </div>`;
      }).join('');
      const igLine = ig.post_count > 0
        ? `<div style="margin-top:6px;padding-top:6px;border-top:1px solid #1a1a1a;font-size:10px;color:#888">
            📸 Instagram · ${ig.post_count} post${ig.post_count!==1?'s':''} · last: ${ig.last_posted||'—'}
            · next in ${ig.next_post_in_days}d
          </div>`
        : '';
      return `<div class="card" style="grid-column:span 2;min-width:260px">
        <div class="card-label" style="margin-bottom:8px">Email Providers — Today</div>
        ${provHTML}
        <div style="margin-top:6px;font-size:10px;color:#555">Resets at midnight · auto-fallback active</div>
        ${igLine}
      </div>`;
    })()}
  `;
  document.getElementById('badge-warm').textContent      = s.warm;
  document.getElementById('badge-responses').textContent =
    DATA.real_replies.length + DATA.opt_outs.length + DATA.auto_replies.length + DATA.gmail_replies.length;
  document.getElementById('badge-queue').textContent     = DATA.queue.filter(q=>q.sent==='no').length;
  document.getElementById('badge-intake').textContent    = (DATA.intakes||[]).length;
  document.getElementById('last-updated').textContent    = 'Updated ' + new Date().toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});

  const dupCt = DATA.dup_phones.length;
  if (dupCt) {
    const bd = document.getElementById('badge-dups');
    bd.style.display = '';
    bd.textContent   = dupCt + ' dup';
  }
}

// ── Warm Leads ─────────────────────────────────────────────────────────────────

function renderWarm() {
  const el = document.getElementById('warm-list');
  if (!DATA.warm.length) { el.innerHTML = '<p class="empty">No warm leads yet. Keep sending!</p>'; return; }
  el.innerHTML = DATA.warm.map(l => `
    <div class="queue-item" onclick="openPanel('${l.phone}')" style="cursor:pointer">
      <div class="queue-info">
        <h4>${l.name} <span style="font-weight:normal;color:#888;font-size:12px">${l.category}</span></h4>
        <span>${l.phone} &nbsp;·&nbsp; ${l.sms_sent} SMS · ${l.email_sent} emails · last: ${daysAgo(l.last_contact).replace(/<[^>]+>/g,'')}</span>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0">
        <button class="btn btn-sm btn-green" onclick="event.stopPropagation();openPanel('${l.phone}')">View →</button>
      </div>
    </div>`).join('');
}

// ── Responses (SMS + Gmail) ────────────────────────────────────────────────────

function renderResponses() {
  const tbody = document.getElementById('responses-body');
  const smsAll = [
    ...DATA.real_replies.map(m=>({...m, kind:'real',  channel:'sms',   ts:m.date_sent, preview:(m.body||'').slice(0,100)})),
    ...DATA.opt_outs.map(m=>   ({...m, kind:'stop',   channel:'sms',   ts:m.date_sent, preview:(m.body||'').slice(0,100)})),
    ...DATA.auto_replies.map(m=>({...m,kind:'auto',   channel:'sms',   ts:m.date_sent, preview:(m.body||'').slice(0,100)})),
  ];
  const emailAll = DATA.gmail_replies.map(r=>({
    ...r, kind:'email_reply', channel:'email', ts:r.ts,
    from: r.from_email, preview: r.snippet,
  }));
  const all = [...smsAll, ...emailAll].sort((a,b)=>(b.ts||'').localeCompare(a.ts||''));

  if (!all.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty">No responses yet.</td></tr>'; return; }
  tbody.innerHTML = all.map((m, i) => {
    const lead    = DATA.leads.find(l=>l.phone===m.from || l.email===m.from_email)||{};
    const chColor = m.channel==='email'?'#9b59b6':'#3498db';
    const tyColor = m.kind==='real'||m.kind==='email_reply' ? '#f39c12' : m.kind==='stop'?'#888':'#555';
    const chLabel = m.channel==='email'?'EMAIL':'SMS';
    const tyLabel = m.kind==='email_reply'?'REPLY':m.kind==='real'?'REPLY':m.kind.toUpperCase();
    const isReal  = m.kind==='real'||m.kind==='email_reply';
    const phone   = m.from||'';
    const email   = m.from_email||lead.email||'';
    const bodyEsc = (m.preview||'').replace(/'/g,"\\'");
    const draftBtn = isReal
      ? `<button class="btn btn-sm" style="background:#1a2a1a;color:#2ecc71;border:1px solid #2ecc71"
           onclick="event.stopPropagation();toggleDraft(${i},'${bodyEsc}','${phone}','${m.channel}','${email}')">Draft Reply</button>`
      : '';
    const mailtoReply = m.channel==='email' && email
      ? `<a class="btn btn-sm btn-outline" href="mailto:${email}" onclick="event.stopPropagation()">Open Email</a>` : '';
    return `
    <tr class="clickable" onclick="openPanel('${phone||email}')">
      <td style="white-space:nowrap;color:#888">${fmtTs(m.ts)}</td>
      <td>${tag(chLabel,chColor)}</td>
      <td>${tag(tyLabel,tyColor)}</td>
      <td><strong>${lead.name||m.name||'Unknown'}</strong><br><span style="color:#666;font-size:11px">${lead.category||''}</span></td>
      <td style="font-size:12px">${m.preview||''}</td>
      <td style="white-space:nowrap">
        <div style="display:flex;gap:6px">
          ${draftBtn}${mailtoReply}
          <button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${phone||email}')">View</button>
        </div>
      </td>
    </tr>
    <tr id="draft-${i}" style="display:none;background:#0d1a0d">
      <td colspan="6" style="padding:10px 16px">
        <textarea id="draft-ta-${i}" rows="3"
          style="width:100%;background:#111;border:1px solid #2ecc71;color:#ddd;padding:8px;border-radius:4px;font-size:13px;resize:vertical"></textarea>
        <div style="display:flex;gap:8px;margin-top:6px">
          ${phone ? `<button id="draft-send-${i}" class="btn btn-sm btn-green" onclick="sendDraftSms(${i},'${phone}')">Send SMS</button>` : ''}
          <button class="btn btn-sm btn-outline" onclick="copyDraft(${i})">Copy</button>
          <button class="btn btn-sm" style="color:#888" onclick="document.getElementById('draft-${i}').style.display='none'">Cancel</button>
        </div>
      </td>
    </tr>`;
  }).join('');
}

// ── Follow-up Queue ────────────────────────────────────────────────────────────

function renderQueue() {
  const el      = document.getElementById('queue-list');
  const pending = DATA.queue.filter(q=>q.sent==='no');
  if (!pending.length) { el.innerHTML = '<p class="empty">No follow-ups queued.</p>'; return; }
  el.innerHTML = pending.map(q => `
    <div class="queue-item">
      <div class="queue-info">
        <h4 style="cursor:pointer" onclick="openPanel('${q.phone}')">${q.name}
          <span style="font-weight:normal;color:#888;font-size:12px">${q.category}</span></h4>
        <span>Send after: ${q.send_after} &nbsp;·&nbsp; ${q.reason}</span>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm btn-green" onclick="sendFollowup('${q.phone}','${esc(q.name)}')">Send Now</button>
      </div>
    </div>`).join('');
}

// ── All Leads ──────────────────────────────────────────────────────────────────

function renderAllLeads(leads) {
  const tbody   = document.getElementById('all-leads-body');
  const dupSet  = new Set(DATA.dup_phones);
  const overduePhones = new Set(DATA.overdue.map(o=>o.phone));
  if (!leads.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty">No leads.</td></tr>'; return; }
  const sorted = [...leads].sort((a,b) => {
    if (a.clicked && !b.clicked) return -1;
    if (!a.clicked && b.clicked) return 1;
    return (b.sms_sent+b.email_sent) - (a.sms_sent+a.email_sent);
  });
  tbody.innerHTML = sorted.slice(0,300).map(l => {
    const isOverdue = overduePhones.has(l.phone);
    const isDup     = dupSet.has(l.phone);
    const hotTag    = l.clicked ? ' <span style="color:#7ed321;font-size:10px;font-weight:700">🔥HOT</span>' : '';
    const dupTag    = isDup ? ' <span style="color:#e74c3c;font-size:10px">DUP</span>' : '';
    return `<tr class="clickable${isOverdue?' overdue':''}" onclick="openPanel('${l.phone}')">
      <td><strong>${l.name}</strong>${hotTag}${dupTag}</td>
      <td style="color:#666;font-size:12px">${l.category}</td>
      <td>${statusTag(l.status||'contacted')}</td>
      <td style="text-align:center;color:#888">${l.sms_sent}</td>
      <td style="text-align:center;color:#888">${l.email_sent}</td>
      <td>${l.replied?'<span style="color:#27ae60">✓</span>':'<span style="color:#2a2a2a">—</span>'}</td>
      <td style="font-size:12px">${daysAgo(l.last_contact)}</td>
      <td><button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${l.phone}')">View</button></td>
    </tr>`;
  }).join('');
}

function filterLeads() {
  const q            = document.getElementById('lead-search').value.toLowerCase();
  const showClickers = document.getElementById('show-clickers').checked;
  const showDups     = document.getElementById('show-dups').checked;
  const showOverdue  = document.getElementById('show-overdue').checked;
  const dupSet       = new Set(DATA.dup_phones);
  const overdueSet   = new Set(DATA.overdue.map(o=>o.phone));
  let leads = DATA.leads.filter(l=>
    (l.name||'').toLowerCase().includes(q) || (l.category||'').toLowerCase().includes(q)
  );
  if (showClickers) leads = leads.filter(l=>l.clicked);
  if (showDups)     leads = leads.filter(l=>dupSet.has(l.phone));
  if (showOverdue)  leads = leads.filter(l=>overdueSet.has(l.phone));
  renderAllLeads(leads);
}

// ── Revenue Forecast ──────────────────────────────────────────────────────────

function renderForecast() {
  const fc = DATA.revenue_forecast;
  if (!fc || !fc.daily_sends) { document.getElementById('forecast-row').innerHTML = ''; return; }

  const approx = fc.using_defaults
    ? ' <span style="font-size:10px;color:#555">(estimated — not enough data yet for real rates)</span>'
    : '';

  document.getElementById('forecast-row').innerHTML = `
    <div style="background:#0d0d0d;border:1px solid #1c1c1c;border-radius:8px;padding:14px 20px;
      display:flex;align-items:center;gap:24px;flex-wrap:wrap">
      <div>
        <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.8px;margin-bottom:4px">
          Projected Monthly Revenue${approx}
        </div>
        <div style="font-size:28px;font-weight:700;color:#27ae60">
          $${fc.projected_revenue.toLocaleString()}
        </div>
      </div>
      <div style="flex:1;display:flex;gap:20px;flex-wrap:wrap;font-size:12px;color:#555">
        <div><span style="color:#888">${fc.daily_sends}</span> emails/day
          &nbsp;→&nbsp; <span style="color:#888">${fc.monthly_sends.toLocaleString()}</span>/mo</div>
        <div><span style="color:#C9A96E">${fc.warm_rate_pct}%</span> warm rate</div>
        <div><span style="color:#C9A96E">${fc.close_rate_pct}%</span> close rate</div>
        <div style="color:#333">= <strong style="color:#27ae60">${fc.projected_closes}</strong> closes/mo
          × $${SITE_PRICE}</div>
      </div>
      <div style="font-size:11px;color:#2a2a2a;text-align:right;white-space:nowrap">
        ${fc.days_active} days active
      </div>
    </div>`;
}

// ── Conversion Funnel ─────────────────────────────────────────────────────────

function renderFunnel() {
  const sg   = DATA.sg_stats || {};
  const pip  = DATA.pipeline || {};
  const sent    = DATA.stats.total_email || sg.requests || 0;
  const opened  = sg.opens     || 0;
  const clicked = sg.clicks    || 0;
  const replied = (DATA.gmail_replies||[]).length + (DATA.real_replies||[]).length;
  const won     = (pip.won||0) + (pip.booked||0);

  if (!sent) { document.getElementById('funnel-row').innerHTML = ''; return; }

  const pct = (a, b) => b ? Math.round(a / b * 100) : 0;
  const steps = [
    { label: 'Sent',    val: sent,    sub: '100%',               color: '#555' },
    { label: 'Opened',  val: opened,  sub: pct(opened,sent)+'%', color: '#C9A96E' },
    { label: 'Clicked', val: clicked, sub: pct(clicked,sent)+'%',color: '#d4a017' },
    { label: 'Replied', val: replied, sub: pct(replied,sent)+'%',color: '#2980b9' },
    { label: 'Won/Booked', val: won,  sub: pct(won,sent)+'%',    color: '#27ae60' },
  ];

  document.getElementById('funnel-row').innerHTML =
    '<p class="section-title" style="margin-bottom:10px">Conversion Funnel</p>' +
    '<div style="display:flex;border:1px solid #1c1c1c;border-radius:8px;overflow:hidden;background:#111">' +
    steps.map((s, i) =>
      `<div style="flex:1;padding:14px 10px;border-right:${i<steps.length-1?'1px solid #1c1c1c':'none'};text-align:center">
        <div style="font-size:22px;font-weight:700;color:${s.color}">${s.val.toLocaleString()}</div>
        <div style="color:#444;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin:4px 0 2px">${s.label}</div>
        <div style="font-size:11px;color:#333">${s.sub}</div>
      </div>`
    ).join('') + '</div>';
}

// ── Hot-lead sound alert ───────────────────────────────────────────────────────

let _prevHotCount = -1;

function _playChime() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [880, 1100, 1320].forEach((freq, i) => {
      const osc  = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = freq;
      gain.gain.setValueAtTime(0.25, ctx.currentTime + i * 0.12);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.12 + 0.3);
      osc.start(ctx.currentTime + i * 0.12);
      osc.stop(ctx.currentTime  + i * 0.12 + 0.3);
    });
  } catch(e) {}
}

function _checkHotAlert(hotCount) {
  if (_prevHotCount >= 0 && hotCount > _prevHotCount) {
    _playChime();
    document.title = '(!) WebByMaya Console';
    toast('🔥 New hot lead detected!');
  } else {
    document.title = 'WebByMaya Console';
  }
  _prevHotCount = hotCount;
}

// Poll /data.json every 90s — light check for new hot leads
setInterval(() => {
  fetch('/data.json').then(r => r.json()).then(d => {
    const hotCount = (d.clicker_leads||[]).length;
    _checkHotAlert(hotCount);
  }).catch(() => {});
}, 90000);

// ── Zones ──────────────────────────────────────────────────────────────────────

function renderZones() {
  const tbody = document.getElementById('zones-body');
  if (!DATA.zone_stats || !DATA.zone_stats.length) {
    tbody.innerHTML = '<tr><td colspan="7" class="empty">No zone data yet.</td></tr>'; return;
  }
  tbody.innerHTML = DATA.zone_stats.map(z => `<tr>
    <td><strong>${z.zone}</strong></td>
    <td style="color:#888">${z.date||'—'}</td>
    <td style="text-align:center">${z.businesses}</td>
    <td style="text-align:center">${z.sent}</td>
    <td style="text-align:center;color:#888">${z.emails_sent||0}</td>
    <td style="text-align:center;color:${(z.open_rate||0)>=20?'#C9A96E':'#555'}">${z.emails_sent?z.open_rate+'%':'—'}</td>
    <td style="text-align:center;color:${(z.click_rate||0)>=5?'#27ae60':'#555'}">${z.emails_sent?z.click_rate+'%':'—'}</td>
  </tr>`).join('');
}

// ── SMS alert banner ──────────────────────────────────────────────────────────

function renderSmsAlert() {
  const d = DATA.sms_delivery;
  if (!d || !d.has_10dlc_issue) return;
  const el = document.getElementById('sms-alert');
  el.style.display = '';
  el.style.cssText = 'background:#1a0505;border:1px solid #4a0d0d;border-left:3px solid #e74c3c;padding:12px 16px;border-radius:6px;margin-bottom:14px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:16px;font-size:13px';
  const pct = d.total ? Math.round(d.blocked_10dlc / d.total * 100) : 0;
  el.innerHTML = `
    <div style="color:#aaa;line-height:1.7">
      <span style="color:#e74c3c;font-weight:700">SMS issue: ${pct}% of texts blocked by carriers</span>
      — your Twilio number isn't registered for business messaging (A2P 10DLC).
      Only <b style="color:#e87070">${d.delivery_rate}%</b> of messages are actually delivering.
      Fix it in Twilio Console → takes 1–3 days, required for commercial texting.
    </div>
    <button class="btn btn-sm btn-danger"
      onclick="window.open('https://console.twilio.com/us1/develop/sms/regulatory-compliance/a2p-10dlc','_blank')">
      Fix in Twilio →
    </button>`;
}

// ── SMS health (analytics page) ───────────────────────────────────────────────

function renderSmsHealth() {
  const el = document.getElementById('sms-health-section');
  if (!el) return;
  const d = DATA.sms_delivery;
  if (!d || !d.total) {
    el.innerHTML = '<p style="color:#444;font-size:13px">No Twilio delivery data available.</p>';
    return;
  }

  const pct10dlc   = d.total ? Math.round(d.blocked_10dlc / d.total * 100) : 0;
  const pctLand    = d.total ? Math.round(d.landlines     / d.total * 100) : 0;
  const pctUnreach = d.total ? Math.round(d.unreachable   / d.total * 100) : 0;
  const pctDel     = d.delivery_rate;
  const estDelivered = Math.round((DATA.stats.total_sms || 0) * d.delivery_rate / 100);

  // Funnel bars
  function bar(pct, color, label, count, note) {
    return `<div style="display:flex;align-items:center;gap:12px;margin-bottom:12px">
      <div style="width:180px;flex-shrink:0;background:#141414;border-radius:3px;overflow:hidden;height:22px">
        <div style="width:${pct}%;background:${color};height:100%;display:flex;align-items:center;padding:0 8px;min-width:2px">
          <span style="font-size:11px;font-weight:700;color:#111;white-space:nowrap">${pct > 8 ? pct+'%' : ''}</span>
        </div>
      </div>
      <div>
        <span style="color:#ccc;font-size:13px;font-weight:600">${count.toLocaleString()} — ${label}</span>
        ${note ? `<span style="color:#555;font-size:11px;margin-left:8px">${note}</span>` : ''}
      </div>
    </div>`;
  }

  el.innerHTML = `
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:20px">
      <div class="card" style="min-width:110px">
        <div class="card-num" style="color:${pctDel < 20 ? '#e74c3c' : '#27ae60'}">${pctDel}%</div>
        <div class="card-label">Delivery Rate</div>
        <div style="color:#555;font-size:10px;margin-top:4px">~${estDelivered.toLocaleString()} of ${(DATA.stats.total_sms||0).toLocaleString()} reached</div>
      </div>
      <div class="card" style="min-width:110px;border-color:${d.has_10dlc_issue?'#4a0d0d':'#1c1c1c'}">
        <div class="card-num red">${pct10dlc}%</div>
        <div class="card-label">Carrier Blocked</div>
        <div style="color:#555;font-size:10px;margin-top:4px">${d.blocked_10dlc.toLocaleString()} msgs · 10DLC</div>
      </div>
      <div class="card" style="min-width:110px">
        <div class="card-num orange">${pctLand}%</div>
        <div class="card-label">Landlines</div>
        <div style="color:#555;font-size:10px;margin-top:4px">${d.landlines.toLocaleString()} can't receive texts</div>
      </div>
      <div class="card" style="min-width:110px">
        <div class="card-num">${d.delivered.toLocaleString()}</div>
        <div class="card-label">Confirmed Delivered</div>
        <div style="color:#555;font-size:10px;margin-top:4px">of last ${d.total.toLocaleString()} checked</div>
      </div>
      <div class="card" style="min-width:110px">
        <div class="card-num" style="color:#888">${d.segments.toLocaleString()}</div>
        <div class="card-label">Billing Segments</div>
        <div style="color:#555;font-size:10px;margin-top:4px">${d.total.toLocaleString()} msgs split into segments</div>
      </div>
    </div>

    <p style="color:#555;font-size:11px;text-transform:uppercase;letter-spacing:.8px;margin-bottom:14px">Where your texts went</p>
    ${bar(pctDel,      '#27ae60', 'Delivered',              d.delivered,     'reached a real phone')}
    ${bar(pct10dlc,    '#e74c3c', 'Blocked — 10DLC',        d.blocked_10dlc, 'carriers filtered (fix: register A2P 10DLC in Twilio)')}
    ${bar(pctLand,     '#d4a017', 'Landline — undeliverable',d.landlines,    'number can\'t receive SMS')}
    ${bar(pctUnreach,  '#888',    'Unreachable',             d.unreachable,  'handset off or number disconnected')}

    <div style="background:#0f1800;border:1px solid #2a3800;border-left:3px solid #7ed321;padding:14px 16px;border-radius:6px;margin-top:18px;font-size:13px;line-height:1.8">
      <strong style="color:#a8e060">How to fix this — in order of impact:</strong><br>
      <span style="color:#888">
        1. <b style="color:#ddd">Register A2P 10DLC</b> — Twilio Console → Messaging → Regulatory Compliance → US A2P 10DLC.
           Free for standard tier, takes 1–3 business days. Fixes the 75% carrier block immediately.<br>
        2. <b style="color:#ddd">Filter landlines before sending</b> — Twilio Lookup API ($0.01/number) checks mobile vs landline.
           Add a pre-send check in scheduled_send.py to skip landlines.<br>
        3. <b style="color:#ddd">Shorten messages</b> — your current SMS is 3 segments (>320 chars). Cutting to 1 segment (&lt;160 chars)
           reduces cost by 3× and improves delivery on some carriers.
      </span>
    </div>`;
}

// ── Credit meter ──────────────────────────────────────────────────────────────

function renderCreditMeter() {
  const sgUsed = DATA.sg_today;
  document.getElementById('hdr-credit').innerHTML =
    `<div class="health-pill" title="Outbound emails go through Gmail (500/day free). SendGrid used for tracking only.">
       <span style="color:#2ecc71;font-weight:bold">Gmail</span>
       <span style="color:#444;margin:0 6px">·</span>
       <span style="font-size:11px;color:#666">${sgUsed} tracked via SG</span>
     </div>`;
}

// ── Analytics ──────────────────────────────────────────────────────────────────

function renderAnalytics() {
  const s   = DATA.stats;
  const sg  = DATA.sg_stats;
  const del = sg.delivered || 0;

  // ── SMS section ────────────────────────────────────────────────────────────
  const replyRate  = s.total_sms ? (s.replies / s.total_sms * 100).toFixed(1) : 0;
  const optOutRate = s.total_sms ? (s.opt_outs / s.total_sms * 100).toFixed(1) : 0;

  // ── Email section ──────────────────────────────────────────────────────────
  const openRate   = del ? Math.round(sg.opens   / del * 100) : 0;
  const clickRate  = del ? Math.round(sg.clicks  / del * 100) : 0;
  const bounceRate = sg.requests ? Math.round(sg.bounces / sg.requests * 100) : 0;
  const blockRate  = sg.requests ? Math.round((sg.blocks||0) / sg.requests * 100) : 0;
  const delivRate  = sg.requests ? Math.round(del / sg.requests * 100) : 0;
  const unlogged   = (sg.requests||0) - s.total_email;

  document.getElementById('analytics-rates').innerHTML = `
    <div style="width:100%">
      <p style="color:#3498db;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">
        ── SMS Channel (Twilio) ──
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:24px">
        <div class="card" style="min-width:120px">
          <div class="card-num">${s.total_sms.toLocaleString()}</div>
          <div class="card-label">Total Sent</div>
          <div style="color:#555;font-size:10px;margin-top:4px">via Twilio</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num green">${s.replies}</div>
          <div class="card-label">Replies</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${replyRate}% reply rate</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num red">${s.opt_outs}</div>
          <div class="card-label">Opt-Outs (STOP)</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${optOutRate}% opt-out rate</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num orange">${s.warm}</div>
          <div class="card-label">Warm Leads</div>
          <div style="color:#555;font-size:10px;margin-top:4px">replied &amp; interested</div>
        </div>
      </div>

      <p style="color:#C9A96E;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">
        ── Email Channel (SendGrid) ──
      </p>
      <div style="display:flex;flex-wrap:wrap;gap:12px;margin-bottom:12px">
        <div class="card" style="min-width:120px">
          <div class="card-num">${(sg.requests||0).toLocaleString()}</div>
          <div class="card-label">Total Sent</div>
          <div style="color:#555;font-size:10px;margin-top:4px">SendGrid all-time</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num green">${del.toLocaleString()}</div>
          <div class="card-label">Delivered</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${delivRate}% delivery rate</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num green">${openRate}%</div>
          <div class="card-label">Open Rate</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${sg.opens||0} opens</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num green">${clickRate}%</div>
          <div class="card-label">Click Rate</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${sg.clicks||0} link clicks</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num ${bounceRate > 5 ? 'red' : 'orange'}">${bounceRate}%</div>
          <div class="card-label">Bounce Rate</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${sg.bounces||0} bounced</div>
        </div>
        <div class="card" style="min-width:120px">
          <div class="card-num red">${sg.blocks||0}</div>
          <div class="card-label">Blocked</div>
          <div style="color:#555;font-size:10px;margin-top:4px">${blockRate}% block rate</div>
        </div>
      </div>
      <div style="background:#111;border:1px solid #222;border-radius:4px;padding:10px 14px;font-size:11px;color:#666;margin-bottom:4px">
        Local log breakdown: ${(s.email_by_type||{}).outreach||0} cold outreach
        · ${(s.email_by_type||{}).followup||0} follow-ups
        · ${(s.email_by_type||{}).clicker||0} clicker follow-ups
        · ${(s.email_by_type||{}).reengagement||0} re-engagement
        · ${(s.email_by_type||{}).seasonal||0} seasonal
        = <b style="color:#C9A96E">${s.total_email.toLocaleString()} total</b>
        ${sg.requests > 0 ? '(SendGrid API reports '+(sg.requests||0).toLocaleString()+' via SG only)' : ''}
      </div>
    </div>`;

  // Daily activity chart — SMS from local logs, email from SendGrid (more accurate)
  const sgByDate  = {};
  DATA.sg_daily.forEach(d => sgByDate[d.date] = d);
  const smsByDate = {};
  DATA.daily_sms.forEach(d => smsByDate[d.date] = d.sms);

  const allDates    = new Set([...Object.keys(sgByDate), ...Object.keys(smsByDate)]);
  const sortedDates = [...allDates].sort();
  const maxSms   = Math.max(1, ...sortedDates.map(d => smsByDate[d]||0));
  const maxEmail = Math.max(1, ...sortedDates.map(d => (sgByDate[d]||{}).sent||0));
  const maxVal   = Math.max(maxSms, maxEmail);

  const chartHtml = sortedDates.map(d => {
    const sgd     = sgByDate[d] || {};
    const smsCt   = smsByDate[d] || 0;
    const emailCt = sgd.sent || 0;
    const smsPct  = Math.round(smsCt   / maxVal * 100);
    const emailPct= Math.round(emailCt / maxVal * 100);
    const label   = d.slice(5);
    return `<div style="display:flex;align-items:flex-start;gap:10px;margin-bottom:11px">
      <span style="color:#555;font-size:11px;width:38px;flex-shrink:0;text-align:right;padding-top:2px">${label}</span>
      <div style="flex:1;display:flex;flex-direction:column;gap:4px">
        ${smsCt ? `<div style="display:flex;align-items:center;gap:7px">
          <div style="width:${smsPct}%;background:#3498db;height:12px;border-radius:2px;min-width:3px;flex-shrink:0"></div>
          <span style="color:#6aafe6;font-size:11px;white-space:nowrap">${smsCt.toLocaleString()} SMS</span>
        </div>` : ''}
        ${emailCt ? `<div style="display:flex;align-items:center;gap:7px">
          <div style="width:${emailPct}%;background:#C9A96E;height:12px;border-radius:2px;min-width:3px;flex-shrink:0"></div>
          <span style="color:#C9A96E;font-size:11px;white-space:nowrap">${emailCt} emails · ${sgd.opens||0} opens · ${sgd.clicks||0} clicks${sgd.bounces ? ' · <span style="color:#e74c3c">'+sgd.bounces+' bounced</span>' : ''}</span>
        </div>` : ''}
        ${!smsCt && !emailCt ? '<div style="color:#2a2a2a;font-size:11px">—</div>' : ''}
      </div>
    </div>`;
  }).join('');

  document.getElementById('analytics-chart').innerHTML = chartHtml ||
    '<p style="color:#444;font-size:13px;text-align:center;padding:24px">No activity data yet.</p>';

  // Email performance by day table (from SendGrid)
  const sgBody = document.getElementById('sg-daily-body');
  if (!DATA.sg_daily.length) {
    sgBody.innerHTML = '<tr><td colspan="5" class="empty">No SendGrid data.</td></tr>';
  } else {
    sgBody.innerHTML = [...DATA.sg_daily].reverse().map(d => {
      const openPct  = d.sent ? Math.round(d.opens  / d.sent * 100) : 0;
      const delivPct = d.sent ? Math.round((d.sent - d.bounces) / d.sent * 100) : 0;
      return `<tr>
        <td style="color:#888">${d.date}</td>
        <td>${d.sent}</td>
        <td>${d.opens} <span style="color:#555;font-size:10px">(${openPct}%)</span></td>
        <td>${d.clicks}</td>
        <td>${d.bounces ? `<span style="color:#e74c3c">${d.bounces}</span>` : '<span style="color:#2ecc71">0</span>'}</td>
      </tr>`;
    }).join('');
  }

  renderSmsHealth();

  // Category breakdown table
  const catBody = document.getElementById('cat-breakdown-body');
  if (!DATA.cat_breakdown.length) {
    catBody.innerHTML = '<tr><td colspan="4" class="empty">No data.</td></tr>';
  } else {
    catBody.innerHTML = DATA.cat_breakdown.map(c => `<tr>
      <td style="text-transform:capitalize">${c.category}</td>
      <td style="text-align:center;color:#6aafe6">${c.sms || '—'}</td>
      <td style="text-align:center;color:#C9A96E">${c.email || '—'}</td>
      <td style="text-align:center;color:#888;font-weight:bold">${c.total}</td>
    </tr>`).join('');
  }

  // Bounce domain breakdown
  const bd = DATA.bounce_domains || [];
  const bdEl = document.getElementById('bounce-domains-section');
  if (!bd.length) {
    bdEl.innerHTML = '<p style="color:#333;font-size:12px">No bounce data yet.</p>';
  } else {
    const maxCount = bd[0].count;
    bdEl.innerHTML = '<div style="display:flex;flex-direction:column;gap:6px;max-width:480px">' +
      bd.map(b => {
        const w = Math.round(b.count / maxCount * 100);
        return `<div style="display:flex;align-items:center;gap:10px;font-size:12px">
          <span style="width:190px;color:#888;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
            title="${b.domain}">${b.domain}</span>
          <div style="flex:1;height:6px;background:#1a1a1a;border-radius:3px;overflow:hidden">
            <div style="height:6px;background:#c0392b;width:${w}%;border-radius:3px"></div>
          </div>
          <span style="color:#e87070;width:24px;text-align:right">${b.count}</span>
        </div>`;
      }).join('') + '</div>';
  }

  const ddEl = document.getElementById('dedup-section');
  const dups = DATA.dedup_flags || [];
  if (!dups.length) {
    ddEl.innerHTML = '<p style="color:#333;font-size:12px">No duplicate flags — run <code>python dedup_check.py --write</code> to scan.</p>';
  } else {
    ddEl.innerHTML = `<p style="color:#888;font-size:11px;margin-bottom:8px">${dups.length} duplicate contact${dups.length!==1?'s':''} found across zone passes</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Name</th><th>Match</th><th>Type</th><th>Category</th><th>Times</th><th>First</th><th>Last</th></tr></thead>
        <tbody>${dups.slice(0,100).map(d=>`
          <tr>
            <td style="color:#C9A96E">${d.name||'—'}</td>
            <td style="font-size:11px;color:#555">${d.match_value}</td>
            <td><span class="tag">${d.match_type}</span></td>
            <td>${d.category||'—'}</td>
            <td style="color:#e87070;text-align:center">${d.contact_count}</td>
            <td style="color:#666">${d.first_date}</td>
            <td style="color:#666">${d.last_date}</td>
          </tr>`).join('')}
        </tbody>
      </table></div>`;
  }
}

// ── SMS / Email / Bounces ──────────────────────────────────────────────────────

function renderSmsLog() {
  const tbody = document.getElementById('sms-body');
  const rows  = [...DATA.sms_logs].reverse().slice(0,300);
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No SMS logs.</td></tr>'; return; }
  tbody.innerHTML = rows.map(r => {
    const bc = r.status==='sent'?'#2ecc71':r.status==='failed'?'#e74c3c':'#888';
    return `<tr class="clickable" onclick="openPanelByName('${esc(r.name)}')">
      <td style="white-space:nowrap;color:#888">${fmtTs(r.timestamp)}</td>
      <td><strong>${r.name}</strong></td>
      <td style="color:#888">${r.category||''}</td>
      <td style="font-size:12px">${r.phone||''}</td>
      <td>${tag(r.status||'',bc)}</td>
    </tr>`;
  }).join('');
}

function renderEmailLog() {
  const tbody      = document.getElementById('email-body');
  const rows       = [...DATA.send_logs].reverse().slice(0,300);
  const suppressed = new Set(DATA.suppressed);
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No email logs.</td></tr>'; return; }
  tbody.innerHTML = rows.map(r => {
    const bc   = r.status==='sent'?'#2ecc71':r.status==='bounced'||r.status==='failed'?'#e74c3c':'#888';
    const supp = suppressed.has((r.email_sent_to||'').toLowerCase()) ? ' ⚠' : '';
    return `<tr class="clickable" onclick="openPanelByName('${esc(r.name)}')">
      <td style="white-space:nowrap;color:#888">${fmtTs(r.timestamp)}</td>
      <td><strong>${r.name}</strong></td>
      <td style="color:#888">${r.category||''}</td>
      <td style="font-size:12px">${r.email_sent_to||''}${supp}</td>
      <td>${tag(r.status||'',bc)}</td>
    </tr>`;
  }).join('');
}

function renderBounces() {
  const tbody = document.getElementById('bounces-body');
  if (!DATA.bounces.length) { tbody.innerHTML = '<tr><td colspan="4" class="empty">No bounces.</td></tr>'; return; }
  tbody.innerHTML = DATA.bounces.map(b => `<tr>
    <td style="color:#888;white-space:nowrap">${fmtTs(b.timestamp)}</td>
    <td>${b.email||''}</td>
    <td>${tag(b.type||'',b.type==='bounce'?'#e74c3c':'#888')}</td>
    <td style="font-size:12px;color:#666">${(b.reason||'').slice(0,100)}</td>
  </tr>`).join('');
}

// ── Lead Panel ─────────────────────────────────────────────────────────────────

function openPanel(phone) {
  const lead = DATA.leads.find(l=>l.phone===phone || l.email===phone);
  if (!lead) return;
  currentPhone = lead.phone;
  _renderPanel(lead);
}

function openPanelByName(name) {
  const lead = DATA.leads.find(l=>(l.name||'').toLowerCase()===name.toLowerCase());
  if (!lead) return;
  currentPhone = lead.phone;
  _renderPanel(lead);
}

function _renderPanel(lead) {
  document.getElementById('panel-name').textContent     = lead.name;
  document.getElementById('panel-category').textContent = lead.category + (lead.rating ? '  ★ '+lead.rating : '');

  const touchDotColors = {sms_out:'#3498db',email_out:'#C9A96E',sms_in:'#2ecc71',email_in:'#9b59b6'};
  const touchLabels    = {sms_out:'SMS Sent',email_out:'Email Sent',sms_in:'SMS Reply',email_in:'Email Reply'};

  const touchHtml = (lead.touches||[]).map(t => `
    <div class="touch-item">
      <div class="touch-dot" style="background:${touchDotColors[t.type]||'#555'}"></div>
      <div>
        <div style="font-size:13px;color:#ccc">${touchLabels[t.type]||t.type}</div>
        <div class="touch-meta">${fmtTs(t.ts)} &nbsp;·&nbsp; ${t.note||''}</div>
      </div>
    </div>`).join('') || '<p style="color:#555;font-size:13px">No touchpoints yet.</p>';

  const mapsLink = lead.maps_url
    ? `<a href="${lead.maps_url}" target="_blank" style="font-size:12px">Open Maps →</a>`
    : lead.address
    ? `<a href="https://maps.google.com?q=${encodeURIComponent(lead.address)}" target="_blank" style="font-size:12px">Open Maps →</a>`
    : '';

  const defaultSms = `Hi ${lead.name}! This is Maya from WebByMaya following up on my earlier message. I'd love to get ${lead.name} online — fill out my quick form and I'll get started: https://webbymaya.com/book`;

  document.getElementById('panel-body').innerHTML = `
    <div class="panel-section">
      <div class="panel-section-title">Contact Info</div>
      <div class="info-grid">
        <span class="info-label">Phone</span>
        <span class="info-val"><a href="tel:${lead.phone}">${lead.phone}</a></span>
        <span class="info-label">Email</span>
        <span class="info-val">${lead.email ? `<a href="mailto:${lead.email}">${lead.email}</a>` : '—'}</span>
        <span class="info-label">Address</span>
        <span class="info-val">${lead.address||'—'}</span>
        ${lead.rating ? `<span class="info-label">Rating</span><span class="info-val">★ ${lead.rating} (${lead.reviews||'?'} reviews)</span>` : ''}
        <span class="info-label">Status</span>
        <span class="info-val">${statusTag(lead.status||'contacted')}</span>
      </div>
      ${mapsLink ? `<div style="margin-top:10px">${mapsLink}</div>` : ''}
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Outreach Summary</div>
      <div class="info-grid">
        <span class="info-label">SMS Sent</span><span class="info-val">${lead.sms_sent}</span>
        <span class="info-label">Emails Sent</span><span class="info-val">${lead.email_sent}</span>
        <span class="info-label">Replied</span><span class="info-val">${lead.replied?'<span style="color:#2ecc71">Yes</span>':'No'}</span>
        <span class="info-label">Last Contact</span><span class="info-val">${daysAgo(lead.last_contact).replace(/<[^>]+>/g,'')} (${fmtTs(lead.last_contact)})</span>
      </div>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Send Custom SMS</div>
      <textarea class="sms-compose" id="custom-sms-txt">${defaultSms}</textarea>
      <button class="btn btn-sm btn-green" style="margin-top:6px"
        onclick="sendCustomSms('${lead.phone}','${esc(lead.name)}')">Send SMS</button>
      <span id="sms-char" style="color:#666;font-size:11px;margin-left:8px"></span>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Notes</div>
      <textarea class="note-area" id="panel-note-txt">${esc(lead.note||'')}</textarea>
      <button class="btn btn-sm btn-outline" style="margin-top:6px"
        onclick="saveNote('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}')">Save Note</button>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Activity Timeline</div>
      ${touchHtml}
    </div>`;

  // SMS character counter
  const smsArea = document.getElementById('custom-sms-txt');
  const smsCtr  = document.getElementById('sms-char');
  function updateCtr() { smsCtr.textContent = smsArea.value.length + ' chars'; }
  smsArea.addEventListener('input', updateCtr); updateCtr();

  let emailBtn;
  if (!lead.email) {
    emailBtn = `<button class="btn btn-sm" style="background:#1a1a1a;color:#444;cursor:not-allowed" title="No email on file">No Email</button>`;
  } else if (lead.clicked) {
    const cd  = lead.click_data || {};
    const tip = `Clicked ${cd.clicks||'?'}x · opened ${cd.opens||'?'}x — send them a mockup offer instead of a call`;
    emailBtn = `<button class="btn btn-sm" style="background:#4a8a00;color:#fff" title="${tip}"
      onclick="sendClickerEmail('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.email)}')">
      🔥 Mockup Offer</button>`;
  } else {
    emailBtn = `<button class="btn btn-sm btn-green"
      onclick="sendFollowupEmail('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.email)}')">
      Follow-up Email</button>`;
  }

  document.getElementById('panel-actions').innerHTML = `
    ${emailBtn}
    <button class="btn btn-sm" style="background:#1a1a2e;color:#7eb8f7;border:1px solid #3a5a8a"
      onclick="generateMockup('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.phone)}','${esc(lead.address||'')}')">🖥 Mockup</button>
    <button class="btn btn-sm btn-green" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','booked')">Booked ✓</button>
    <button class="btn btn-sm btn-green" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','won')">Won 🏆</button>
    <button class="btn btn-sm btn-outline" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','warm')">Warm</button>
    <button class="btn btn-sm btn-danger" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','not_interested')">Not Interested</button>
    <a href="tel:${lead.phone}" class="btn btn-sm btn-outline">Call</a>`;

  document.getElementById('panel-overlay').classList.add('open');
  document.getElementById('lead-panel').classList.add('open');
}

function closePanel() {
  document.getElementById('panel-overlay').classList.remove('open');
  document.getElementById('lead-panel').classList.remove('open');
  currentPhone = null;
}

// ── Actions ────────────────────────────────────────────────────────────────────

function sendFollowup(phone, name) {
  if (!confirm(`Send follow-up SMS to ${name}?`)) return;
  fetch('/action/send-followup',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name})}).then(r=>r.json()).then(d=>{
    if (d.ok) toast('SMS sent to '+name+'!'); else toast('Error: '+(d.error||'unknown'),true);
  });
}

function sendCustomSms(phone, name) {
  const body = document.getElementById('custom-sms-txt').value.trim();
  if (!body) { toast('Message is empty',true); return; }
  if (!confirm(`Send SMS to ${name}?\n\n"${body.slice(0,80)}..."`)) return;
  fetch('/action/send-custom-sms',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name,body})}).then(r=>r.json()).then(d=>{
    if (d.ok) toast('SMS sent!'); else toast('Error: '+(d.error||'unknown'),true);
  });
}

function sendFollowupEmail(phone, name, category, email) {
  if (!confirm(`Send follow-up email to ${name} at ${email}?`)) return;
  fetch('/action/send-followup-email',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name,category,email})}).then(r=>r.json()).then(d=>{
    if (d.ok) toast('Email sent to '+email+'!'); else toast('Error: '+(d.error||'unknown'),true);
  });
}

function sendClickerEmail(phone, name, category, email) {
  if (!confirm(`Send mockup-offer email to ${name} at ${email}?\n\n"Can I send you a mockup?" — lower friction than booking a call.`)) return;
  fetch('/action/send-clicker-email',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name,category,email})}).then(r=>r.json()).then(d=>{
    if (d.ok) toast('Mockup offer sent to '+name+'!'); else toast('Error: '+(d.error||'unknown'),true);
  });
}

function markStatus(phone, name, category, status) {
  fetch('/action/mark-status',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name,category,status})}).then(r=>r.json()).then(d=>{
    if (d.ok) { toast('Marked as '+status.replace(/_/g,' ')); setTimeout(()=>location.reload(),1500); }
    else toast('Error: '+(d.error||'unknown'),true);
  });
}

function saveNote(phone, name, category) {
  const note = document.getElementById('panel-note-txt').value;
  fetch('/action/save-note',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,name,category,note})}).then(r=>r.json()).then(d=>{
    if (d.ok) toast('Note saved!'); else toast('Error: '+(d.error||'unknown'),true);
  });
}

function queueAllOverdue() {
  if (!confirm(`Queue ${DATA.overdue.length} overdue leads for follow-up?`)) return;
  fetch('/action/queue-overdue',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({leads:DATA.overdue})}).then(r=>r.json()).then(d=>{
    if (d.ok) { toast(`Queued ${d.queued} leads!`); setTimeout(()=>location.reload(),1800); }
    else toast('Error: '+(d.error||'unknown'),true);
  });
}

// ── Intake Forms ───────────────────────────────────────────────────────────────

function renderIntakes() {
  const el   = document.getElementById('intake-list');
  const rows = DATA.intakes || [];
  if (!rows.length) {
    el.innerHTML = '<p class="empty">No form submissions yet — share webbymaya.com/book with interested leads.</p>';
    return;
  }
  el.innerHTML = rows.map(r => {
    const budgetBg = r.budget && r.budget.includes('1,5') ? '#1a3a5a'
                   : r.budget && r.budget.includes('1,1') ? '#1a3a1a'
                   : r.budget ? '#3a2a00' : '#222';
    const budgetColor = r.budget && r.budget.includes('1,5') ? '#6aafe6'
                      : r.budget && r.budget.includes('1,1') ? '#2ecc71'
                      : r.budget ? '#C9A96E' : '#666';
    const tags = [
      r.budget    ? `<span class="tag" style="background:${budgetBg};color:${budgetColor}">${r.budget}</span>` : '',
      r.timeline  ? `<span class="tag" style="background:#1a3a5a;color:#6aafe6">${r.timeline}</span>` : '',
      r.primary_goal ? `<span class="tag" style="background:#2a1a2a;color:#b39ddb">${r.primary_goal}</span>` : '',
    ].filter(Boolean).join(' ');
    const howFound  = Array.isArray(r.how_found) ? r.how_found.join(', ') : (r.how_found||'');
    const emailHref = r.contact_email ? `<a href="mailto:${r.contact_email}">${r.contact_email}</a>` : '—';
    return `
    <div class="queue-item" style="display:block">
      <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:12px;flex-wrap:wrap;margin-bottom:8px">
        <div>
          <div style="font-size:15px;font-weight:700;color:#C9A96E;font-family:Georgia,serif">${r.business_name||'Unnamed Business'}</div>
          <div style="color:#888;font-size:12px;margin-top:2px">
            ${r.contact_name||''} &nbsp;·&nbsp; ${emailHref}
            ${r.contact_phone ? ' &nbsp;·&nbsp; <a href="tel:'+r.contact_phone+'">'+r.contact_phone+'</a>' : ''}
          </div>
        </div>
        <span style="color:#555;font-size:11px;flex-shrink:0;padding-top:2px">${fmtTs(r.submitted_at)}</span>
      </div>
      ${tags ? `<div style="margin-bottom:8px">${tags}</div>` : ''}
      ${r.current_website ? `<div style="font-size:12px;color:#666;margin-bottom:4px">Current site: <a href="${r.current_website}" target="_blank" style="color:#6aafe6">${r.current_website}</a></div>` : ''}
      ${howFound ? `<div style="font-size:12px;color:#555;margin-bottom:4px">Finds clients via: ${howFound}</div>` : ''}
      ${r.what_you_do ? `<div style="font-size:12px;color:#888;margin-top:8px;padding-top:8px;border-top:1px solid #1c1c1c;line-height:1.6">${r.what_you_do.slice(0,200)}${r.what_you_do.length>200?'…':''}</div>` : ''}
      ${r.anything_else ? `<div style="font-size:12px;color:#555;margin-top:6px;font-style:italic">"${r.anything_else.slice(0,150)}${r.anything_else.length>150?'…':''}"</div>` : ''}
    </div>`;
  }).join('');
}

// ── Nav ────────────────────────────────────────────────────────────────────────

function showPage(name) {
  document.querySelectorAll('[id^="page-"]').forEach(el=>el.style.display='none');
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('page-'+name).style.display='block';
  document.getElementById('nav-'+name).classList.add('active');
  const nudge = document.getElementById('nudge-bar');
  nudge.style.display = (name==='warm'||name==='all-leads') ? '' : 'none';
}

// ── Init ───────────────────────────────────────────────────────────────────────
renderHealth();
renderCreditMeter();
renderClickerAlert();
renderSmsAlert();
renderPipeline();
renderBacklog();
function renderProjects() {
  const board = document.getElementById('projects-board');
  const badge = document.getElementById('badge-projects');
  const projects = DATA.projects || [];
  const STAGES = ['Form received','Mockup sent','Mockup approved','In build','Live'];
  const STAGE_COLORS = {
    'Form received':'#1a2a3a','Mockup sent':'#1a2a1a','Mockup approved':'#2a2a00',
    'In build':'#2a1a00','Live':'#0a2a0a'
  };
  const STAGE_BORDER = {
    'Form received':'#1e5799','Mockup sent':'#196F3D','Mockup approved':'#7D6608',
    'In build':'#a04000','Live':'#1a7a1a'
  };
  badge.textContent = projects.filter(p=>p.stage!=='Live').length || '';
  if (!projects.length) {
    board.innerHTML = '<p class="empty" style="padding:20px">No active projects yet — mark a lead as Won or Booked to start tracking it here.</p>';
    return;
  }
  const byStage = {};
  STAGES.forEach(s => byStage[s] = []);
  projects.forEach(p => {
    const s = STAGES.includes(p.stage) ? p.stage : 'Form received';
    byStage[s].push(p);
  });
  board.innerHTML = STAGES.map(stage => {
    const items = byStage[stage];
    const cards = items.map(p => `
      <div style="background:#1a1a1a;border:1px solid ${STAGE_BORDER[stage]};border-radius:6px;padding:12px;margin-bottom:8px">
        <div style="font-weight:700;color:#C9A96E;margin-bottom:2px">${p.name}</div>
        <div style="color:#666;font-size:11px;margin-bottom:8px">${p.category} &nbsp;·&nbsp; started ${p.started||'—'}</div>
        ${p.deadline ? `<div style="color:#e67e22;font-size:11px;margin-bottom:8px">Due: ${p.deadline}</div>` : ''}
        ${p.notes ? `<div style="color:#888;font-size:11px;margin-bottom:8px;font-style:italic">${p.notes}</div>` : ''}
        <div style="display:flex;gap:6px;flex-wrap:wrap">
          ${STAGES.filter(s=>s!==stage).map(s=>`
            <button class="btn-sm" onclick="moveProject('${p.phone}','${s}')" style="font-size:10px;padding:3px 7px">${s==='Live'?'✓ Live':s}</button>
          `).join('')}
        </div>
      </div>
    `).join('') || '<div style="color:#333;font-size:11px;padding:8px 0">Empty</div>';
    return `
      <div style="flex:0 0 200px;min-width:180px">
        <div style="font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:.6px;color:#888;margin-bottom:10px;padding:6px 8px;background:${STAGE_COLORS[stage]};border-radius:4px;border-left:3px solid ${STAGE_BORDER[stage]}">
          ${stage} <span style="color:#555">(${items.length})</span>
        </div>
        ${cards}
      </div>
    `;
  }).join('');
}

function moveProject(phone, stage) {
  fetch('/action/update-project-stage',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone,stage})
  }).then(()=>{ DATA.projects=(DATA.projects||[]).map(p=>p.phone===phone?{...p,stage}:p); renderProjects(); });
}

function renderRevenue() {
  const hist = DATA.revenue_history || {};
  const rows = [];
  (DATA.send_logs||[]).forEach(()=>{});
  const totalEl   = document.getElementById('rev-total');
  const clientsEl = document.getElementById('rev-clients');
  const avgEl     = document.getElementById('rev-avg');
  const chart     = document.getElementById('revenue-chart');
  const tbody     = document.getElementById('revenue-rows');
  const total     = hist.total || 0;
  const clients   = hist.clients || 0;
  if (totalEl)   totalEl.textContent   = '$' + total.toLocaleString();
  if (clientsEl) clientsEl.textContent = clients;
  if (avgEl)     avgEl.textContent     = clients ? '$' + Math.round(total/clients).toLocaleString() : '$0';
  const byMonth = hist.by_month || [];
  if (chart) {
    if (!byMonth.length) {
      chart.innerHTML = '<p class="empty">No revenue recorded yet.</p>';
    } else {
      const maxRev = Math.max(...byMonth.map(m=>m.revenue), 1);
      chart.innerHTML = byMonth.map(m => {
        const w = Math.round((m.revenue / maxRev) * 100);
        return `<div style="display:flex;align-items:center;gap:10px;margin-bottom:8px">
          <div style="width:72px;color:#888;font-size:11px;text-align:right">${m.month}</div>
          <div style="flex:1;background:#222;border-radius:3px;height:20px;position:relative">
            <div style="height:100%;width:${w}%;background:#C9A96E;border-radius:3px;transition:width .3s"></div>
          </div>
          <div style="width:60px;color:#C9A96E;font-size:12px;font-weight:700">$${m.revenue.toLocaleString()}</div>
        </div>`;
      }).join('');
    }
  }
  if (tbody) {
    const revRows = (hist.rows || []).slice().reverse();
    if (!revRows.length) {
      tbody.innerHTML = '<tr><td colspan="5" style="color:#555;text-align:center">No transactions yet</td></tr>';
    } else {
      tbody.innerHTML = revRows.map(r => `
        <tr>
          <td>${r.date||'—'}</td>
          <td style="color:#C9A96E">${r.name||'—'}</td>
          <td>${r.category||'—'}</td>
          <td>${r.package||'Standard'}</td>
          <td style="color:#2ecc71;font-weight:700">$${(r.amount||0).toLocaleString()}</td>
        </tr>
      `).join('');
    }
  }
}

renderNudge();
renderStats();
renderWarm();
renderResponses();
renderQueue();
renderAllLeads(DATA.leads);
renderSmsLog();
renderEmailLog();
renderBounces();
renderForecast();
renderFunnel();
renderZones();
renderAnalytics();
renderIntakes();
renderProjects();
renderRevenue();
_checkHotAlert((DATA.clicker_leads||[]).length);
</script>
</body></html>"""

# Patch in SITE_PRICE constant for JS
HTML = HTML.replace('${SITE_PRICE}', str(SITE_PRICE))

# ── HTTP handlers ───────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        os.chdir(SCRIPT_DIR)
        # Serve mockup files
        if self.path.startswith("/mockup/"):
            filename = self.path[len("/mockup/"):]
            if filename and ".." not in filename:
                mock_path = SCRIPT_DIR / "mockups" / filename
                if mock_path.exists() and mock_path.suffix == ".html":
                    self._respond(200, "text/html; charset=utf-8", mock_path.read_bytes())
                    return
            self._respond(404, "text/plain", b"Mockup not found")
            return
        if self.path == "/data.json":
            data      = build_dataset()
            data_json = json.dumps(data, default=str)
            self._respond(200, "application/json", data_json.encode("utf-8"))
            return
        data      = build_dataset()
        data_json = json.dumps(data, default=str)
        html      = HTML.replace('__DATA__', data_json)
        self._respond(200, "text/html; charset=utf-8", html.encode("utf-8"))

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body   = json.loads(self.rfile.read(length)) if length else {}

        if self.path == "/action/send-followup":
            phone = body.get("phone","")
            name  = body.get("name","")
            msg   = FOLLOWUP_MSG.format(name=name)
            sid, err = twilio_send_sms(phone, msg)
            if sid:
                self._log_sms(name, phone, "follow-up", "manual follow-up")
                self._respond(200,"application/json",json.dumps({"ok":True}).encode())
            else:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/send-custom-sms":
            phone = body.get("phone","")
            name  = body.get("name","")
            msg   = body.get("body","").strip()
            if not msg:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"Empty message"}).encode())
                return
            sid, err = twilio_send_sms(phone, msg)
            if sid:
                self._log_sms(name, phone, "custom", "custom SMS from dashboard")
                self._respond(200,"application/json",json.dumps({"ok":True}).encode())
            else:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/send-clicker-email":
            phone    = body.get("phone","")
            name     = body.get("name","")
            category = body.get("category","")
            email    = body.get("email","").strip()
            if not email:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"No email on file."}).encode())
                return
            subject = CLICKER_EMAIL_SUBJECT.format(name=name)
            plain   = CLICKER_EMAIL_PLAIN.format(name=name)
            ok, err = gmail_send_email(email, subject, plain)
            if ok:
                self._log_email(name, category, email, subject)
                self._respond(200,"application/json",json.dumps({"ok":True}).encode())
            else:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/send-followup-email":
            phone    = body.get("phone","")
            name     = body.get("name","")
            category = body.get("category","")
            email    = body.get("email","").strip()
            if not email:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"No email on file."}).encode())
                return
            subject = FOLLOWUP_EMAIL_SUBJECT.format(name=name)
            plain   = FOLLOWUP_EMAIL_PLAIN.format(name=name)
            ok, err = gmail_send_email(email, subject, plain)
            if ok:
                self._log_email(name, category, email, subject)
                self._respond(200,"application/json",json.dumps({"ok":True}).encode())
            else:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/generate-mockup":
            name     = body.get("name","").strip()
            category = body.get("category","").strip()
            phone    = body.get("phone","").strip()
            city     = body.get("city","Philadelphia, PA").strip()
            if not name:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"No business name."}).encode())
                return
            try:
                import generate_mockup as gm
                theme  = gm.get_theme(category)
                fkeys  = gm.get_flickr_keys(category)
                html   = gm.generate_html(name, category, phone, city, theme, fkeys)
                filename = gm.slug(name) + ".html"
                out_path = gm.MOCKUPS_DIR / filename
                out_path.write_text(html, encoding="utf-8")
                url = f"http://localhost:{PORT}/mockup/{filename}"
                self._respond(200,"application/json",json.dumps({"ok":True,"url":url,"file":str(out_path)}).encode())
            except Exception as e:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":str(e)}).encode())

        elif self.path == "/action/quick-reply-sms":
            phone = body.get("phone","").strip()
            msg   = body.get("body","").strip()
            if not phone or not msg:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"Missing phone or body."}).encode())
                return
            sid, err = twilio_send_sms(phone, msg)
            if sid:
                self._respond(200,"application/json",json.dumps({"ok":True}).encode())
            else:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/mark-status":
            save_status(body.get("phone",""), body.get("name",""),
                        body.get("category",""), body.get("status",""))
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/save-note":
            save_note_only(body.get("phone",""), body.get("name",""),
                           body.get("category",""), body.get("note",""))
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/update-project-stage":
            phone = body.get("phone","")
            stage = body.get("stage","")
            projects = _load_projects()
            for p in projects:
                if p.get("phone") == phone:
                    p["stage"] = stage
                    if stage == "Live":
                        p["live_date"] = datetime.now().strftime("%Y-%m-%d")
                    break
            _save_projects(projects)
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/update-project-notes":
            phone = body.get("phone","")
            notes = body.get("notes","")
            deadline = body.get("deadline","")
            projects = _load_projects()
            for p in projects:
                if p.get("phone") == phone:
                    if notes:    p["notes"]    = notes
                    if deadline: p["deadline"] = deadline
                    break
            _save_projects(projects)
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/queue-overdue":
            leads  = body.get("leads",[])
            queued = 0
            send_after = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
            for l in leads:
                ok = add_to_queue(l["phone"], l["name"], l["category"],
                                  send_after, f"overdue {l.get('days_ago',0)}d")
                if ok: queued += 1
            self._respond(200,"application/json",json.dumps({"ok":True,"queued":queued}).encode())

        else:
            self._respond(404,"text/plain",b"Not found")

    def _log_sms(self, name, phone, category, notes):
        today    = datetime.now().strftime("%Y-%m-%d")
        log_path = SCRIPT_DIR / f"sms_log_{today}.csv"
        exists   = log_path.exists()
        with open(log_path,"a",newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","name","phone","category","carrier_type","status","notes"])
            if not exists: w.writeheader()
            w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"),
                        "name": name, "phone": phone, "category": category,
                        "carrier_type": "", "status": "sent", "notes": notes})

    def _log_email(self, name, category, email, subject):
        today    = datetime.now().strftime("%Y-%m-%d")
        log_path = SCRIPT_DIR / f"send_log_{today}.csv"
        exists   = log_path.exists()
        with open(log_path,"a",newline="") as f:
            w = csv.DictWriter(f, fieldnames=["timestamp","name","category","email_sent_to","subject","status","notes"])
            if not exists: w.writeheader()
            w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"),
                        "name": name, "category": category, "email_sent_to": email,
                        "subject": subject, "status": "sent", "notes": "manual follow-up"})

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass

if __name__ == "__main__":
    os.chdir(SCRIPT_DIR)
    print(f"\n  WebByMaya Outreach Console v3")
    print(f"  Open: http://localhost:{PORT}\n")
    HTTPServer(("", PORT), Handler).serve_forever()
