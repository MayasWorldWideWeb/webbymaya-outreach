#!/usr/bin/env python3
"""
dashboard.py — WebByMaya Outreach Console v3
Run:  python3 dashboard.py
Open: http://localhost:8787
"""
import base64, csv, email.mime.multipart, email.mime.text, json, os, re, time, threading, urllib.request, urllib.parse, urllib.error
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

def fetch_client_onboarding():
    """Pull submitted client onboarding forms from Supabase."""
    url = (f"{SUPABASE_URL_WBM}/rest/v1/client_onboarding"
           "?select=*&order=created_at.desc&limit=50")
    req = urllib.request.Request(url, headers={
        "apikey":        SUPABASE_KEY_WBM,
        "Authorization": f"Bearer {SUPABASE_KEY_WBM}",
    })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=8).read())
    except Exception:
        return []

def make_onboard_link(business_name, client_email):
    """Generate a unique onboarding link for a client."""
    import hashlib
    token = hashlib.md5(f"{business_name}{client_email}".encode()).hexdigest()[:12]
    return f"http://localhost:8787/onboard?token={token}"

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

    # 2. Email follow-up logs (rounds 1–3) — two naming conventions
    _fu_files = sorted(set(
        list(SCRIPT_DIR.glob("email_followup_log_*.csv")) +
        list(SCRIPT_DIR.glob("followup_log_*.csv"))
    ))
    for p in _fu_files:
        for r in load_csv(p):
            rows.append({
                "date":          (r.get("timestamp","") or "")[:10],
                "name":          r.get("name",""),
                "category":      r.get("category",""),
                "email_sent_to": r.get("email",""),
                "subject":       r.get("subject",""),
                "status":        "sent" if r.get("status","").lower() == "sent" else r.get("status",""),
                "provider":      r.get("notes", r.get("provider","")),
                "log_type":      "followup",
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
INVOICES_FILE  = SCRIPT_DIR / "invoices.json"

MILESTONE_DEFAULTS = [
    "Intake form received",
    "Mockup created & sent",
    "Mockup approved by client",
    "Site built & tested",
    "Domain / DNS connected",
    "Live & delivered to client",
]

def _load_projects() -> list:
    if not PROJECTS_FILE.exists():
        return []
    try:
        return json.loads(PROJECTS_FILE.read_text())
    except Exception:
        return []

def _save_projects(projects: list):
    PROJECTS_FILE.write_text(json.dumps(projects, indent=2))

def _load_invoices() -> list:
    if not INVOICES_FILE.exists():
        return []
    try:
        return json.loads(INVOICES_FILE.read_text())
    except Exception:
        return []

def _save_invoices(invoices: list):
    INVOICES_FILE.write_text(json.dumps(invoices, indent=2))

def _create_project(phone: str, name: str, category: str, stage: str = "Form received"):
    projects = _load_projects()
    if any(p.get("phone") == phone for p in projects):
        return  # already exists
    projects.append({
        "phone":      phone,
        "name":       name,
        "category":   category,
        "stage":      stage,
        "started":    datetime.now().strftime("%Y-%m-%d"),
        "deadline":   "",
        "notes":      "",
        "milestones": [{"label": m, "done": False} for m in MILESTONE_DEFAULTS],
    })
    _save_projects(projects)

# ── Lead scoring ────────────────────────────────────────────────────────────────

_HIGH_VALUE_CATS = {
    "restaurant","dentist","dental","auto","attorney","law","medical","doctor",
    "clinic","plumber","contractor","hvac","electrician","florist","spa","salon",
    "mechanic","roofing","landscaping","moving",
}

def calc_lead_score(lead: dict) -> int:
    score = 0
    click_data = lead.get("click_data") or {}
    if lead.get("clicked") and not click_data.get("likely_bot"):
        score += 40
    if lead.get("replied"):
        score += 25
    touches = lead.get("touches") or []
    if any(t.get("type") == "email_in" for t in touches):
        score += 20
    ct = len(touches)
    score += 10 if ct >= 5 else 5 if ct >= 3 else 0
    try:
        r = float(lead.get("rating") or 0)
        score += 8 if r >= 4.5 else 4 if r >= 4.0 else 0
    except (ValueError, TypeError):
        pass
    cat = (lead.get("category") or "").lower()
    if any(c in cat for c in _HIGH_VALUE_CATS):
        score += 5
    lc = lead.get("last_contact", "")
    if lc:
        try:
            days = (datetime.now() - datetime.fromisoformat(lc)).days
            score -= min(20, (days // 7) * 5)
        except Exception:
            pass
    return max(0, min(100, score))

def get_reengagement_phones(send_logs: list, leads_list: list) -> set:
    names = {r.get("name","").strip().lower() for r in send_logs
             if r.get("log_type") == "reengagement" and r.get("status") == "sent"}
    return {l["phone"] for l in leads_list if l["name"].strip().lower() in names}

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

_CLICKER_PERSIST = SCRIPT_DIR / "clicker_cache.json"

def _load_clicker_cache():
    """Load previously-seen clickers from local file."""
    try:
        if _CLICKER_PERSIST.exists():
            return json.loads(_CLICKER_PERSIST.read_text())
    except Exception:
        pass
    return {}

def _save_clicker_cache(clickers):
    try:
        _CLICKER_PERSIST.write_text(json.dumps(clickers))
    except Exception:
        pass

def fetch_sg_clickers():
    """Returns {email: {clicks, opens, businesses[], likely_bot}} for emails that clicked.
    Persists results to clicker_cache.json so clickers survive the 1000-message API window."""
    persisted = _load_clicker_cache()
    if not SG:
        return persisted
    try:
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/messages?limit=1000",
            headers={"Authorization": f"Bearer {SG}"})
        msgs = json.loads(urllib.request.urlopen(req, timeout=15).read()).get("messages", [])
        fresh = {}
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
            is_bot = domain in SCANNER_DOMAINS or (clicks >= 4 and opens == 0)
            if email not in fresh:
                fresh[email] = {"clicks": 0, "opens": 0, "businesses": [], "likely_bot": is_bot}
            fresh[email]["clicks"] += clicks
            fresh[email]["opens"]  += opens
            if biz and biz not in fresh[email]["businesses"]:
                fresh[email]["businesses"].append(biz)
        # Merge: persisted fills in clickers no longer in the API window; fresh takes precedence
        merged = {**persisted, **fresh}
        _save_clicker_cache(merged)
        return merged
    except Exception:
        return persisted

def get_daily_send_detail(send_logs, sg_clickers):
    """Group sent emails by date, attach Activity Feed click/open data."""
    by_date = {}
    for row in send_logs:
        if row.get("status") != "sent":
            continue
        ts   = row.get("timestamp", "") or row.get("date", "")
        date = ts[:10] if len(ts) >= 10 else ""
        if not date:
            continue
        email = (row.get("email_sent_to", "") or "").strip().lower()
        cd    = sg_clickers.get(email, {})
        entry = {
            "name":     row.get("name", ""),
            "email":    email,
            "category": row.get("category", ""),
            "subject":  row.get("subject", ""),
            "log_type": row.get("log_type", "outreach"),
            "clicked":  bool(cd.get("clicks", 0)) and not cd.get("likely_bot", False),
            "opens":    cd.get("opens", 0),
            "clicks":   cd.get("clicks", 0),
            "is_bot":   cd.get("likely_bot", False),
        }
        by_date.setdefault(date, []).append(entry)
    return by_date


def get_pending_queue():
    """Read tomorrow's (or most recent) enriched CSV as the pending send queue."""
    from datetime import datetime as _dt, timedelta as _td
    tomorrow = (_dt.now() + _td(days=1)).strftime("%Y-%m-%d")
    today    = _dt.now().strftime("%Y-%m-%d")

    already_sent = set()
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        for row in load_csv(p):
            if row.get("status") == "sent":
                already_sent.add((row.get("email_sent_to") or "").strip().lower())

    for date in [tomorrow, today]:
        for suffix in ["_enriched.csv", ".csv"]:
            csv_path = SCRIPT_DIR / f"prospects_{date}{suffix}"
            if not csv_path.exists():
                continue
            try:
                rows  = load_csv(csv_path)
                queue = []
                for row in rows:
                    if row.get("email_status", "").strip() in ("sent", "bounced", "unsubscribed"):
                        continue
                    email = (row.get("email") or "").strip()
                    if not email or "@" not in email:
                        continue
                    if email.lower() in already_sent:
                        continue
                    queue.append({
                        "name":        row.get("name", ""),
                        "email":       email,
                        "category":    row.get("category", ""),
                        "phone":       row.get("phone", ""),
                        "address":     row.get("address", ""),
                        "city":        row.get("city", "Philadelphia, PA"),
                        "rating":      row.get("rating", ""),
                        "reviews":     row.get("review_count", ""),
                        "has_website": row.get("has_website", ""),
                        "date":        date,
                    })
                if queue:
                    return queue, date, str(csv_path.name)
            except Exception:
                continue
    return [], "", ""


def fetch_sg_daily():
    """Returns per-day SendGrid stats for last 45 days."""
    if not SG: return []
    start = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
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
    """Pull email replies from Gmail via IMAP using app password."""
    import imaplib, email as _email, email.header as _hdr
    gmail_user = "mayas.worldwide.web@gmail.com"
    app_pass   = os.environ.get("GMAIL_APP_PASSWORD", "")
    if not app_pass:
        return []
    try:
        mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
        mail.login(gmail_user, app_pass)
        mail.select("INBOX")
        _, data = mail.search(None, "ALL")
        ids = data[0].split()[-100:]  # last 100 messages
        out = []
        seen = set()
        for mid in reversed(ids):
            _, msg_data = mail.fetch(mid, "(RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)] BODY.PEEK[TEXT])")
            if not msg_data or not msg_data[0]: continue
            raw = msg_data[0][1]
            msg = _email.message_from_bytes(raw)
            frm = msg.get("From", "")
            match = re.search(r'<([^>]+)>', frm)
            addr  = match.group(1).lower().strip() if match else frm.lower().strip()
            if addr not in email_to_name: continue
            if addr in seen: continue
            seen.add(addr)
            def _decode(val):
                parts = _hdr.decode_header(val or "")
                return "".join(p.decode(enc or "utf-8") if isinstance(p, bytes) else p for p, enc in parts)
            subj = _decode(msg.get("Subject", ""))
            date = msg.get("Date", "")
            body_text = ""
            for part in msg_data:
                if isinstance(part, tuple) and len(part) == 2:
                    if isinstance(part[1], bytes) and not part[1].startswith(b'('):
                        try:
                            body_text = part[1].decode('utf-8', errors='replace')[:800].strip()
                        except Exception:
                            pass
                        break
            out.append({
                "kind":       "email_in",
                "from_email": addr,
                "name":       email_to_name[addr],
                "subject":    subj[:120],
                "snippet":    subj[:120],
                "body":       body_text,
                "ts":         date,
            })
        mail.logout()
        return out
    except Exception as e:
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

    date_to_zones = {}
    for e in completed:
        d = e.get("date",""); z = e.get("zone","")
        if d and z:
            date_to_zones.setdefault(d, []).append(z)

    zone_counts = {}
    for row in sms_logs:
        if row.get("status") != "sent": continue
        ts    = row.get("timestamp","")
        date  = ts[:10] if len(ts) >= 10 else ""
        zones = date_to_zones.get(date, [])
        for zone in zones:
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
        zones = date_to_zones.get(date, [])
        em = row.get("email_sent_to","").strip().lower()
        for zone in zones:
            if zone not in zone_counts:
                zone_counts[zone] = {"sent": 0, "phones": set(), "emails": set()}
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
        today_str = datetime.now().strftime("%Y-%m-%d")
        text  = log_path.read_text(encoding="utf-8", errors="replace").strip()
        lines = text.split("\n") if text else []
        mtime = datetime.fromtimestamp(log_path.stat().st_mtime)
        hours_ago = round((datetime.now() - mtime).total_seconds() / 3600, 1)

        # Find the most recent run's start line index for today
        today_header = f"WebByMaya Daily Run — {today_str}"
        run_starts = [i for i, l in enumerate(lines) if today_header in l]
        if run_starts:
            last_run_lines = lines[run_starts[-1]:]
            # Check only the current run's output for errors, not zombie output
            tail = "\n".join(last_run_lines[-20:]).lower()
            ran_today = True
        else:
            tail = "\n".join(lines[-15:]).lower()
            ran_today = False

        has_error = "traceback" in tail  # only flag actual Python crashes, not send errors
        status = "error" if has_error else ("ok" if ran_today else "warning")
        return {
            "status":    status,
            "hours_ago": hours_ago,
            "ran_today": ran_today,
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

def generate_reply_suggestion(name, category, body=""):
    lower = (body or "").lower()
    if any(w in lower for w in ["price","cost","how much","rate","charge","fee","afford"]):
        hook = f"Our starter package for {category or 'local'} businesses is $1,500 for a full custom site — includes design, copy, and going live within a week."
    elif any(w in lower for w in ["example","portfolio","see","look","show","sample"]):
        hook = "I'd love to show you some examples! Check out webbymaya.com/portfolio for sites I've built for similar businesses."
    elif any(w in lower for w in ["time","when","how long","fast","quick","rush"]):
        hook = "I can usually get a site live within 5–7 days once we start."
    else:
        hook = f"I'd love to get {name or 'your business'} set up with a site that actually brings in customers."
    return (f"Hi there,\n\nThank you for getting back to me! {hook}\n\n"
            "Would you be available for a quick 15-minute call this week? "
            "I can walk you through everything and answer any questions.\n\n"
            "Best,\nMaya\nWebByMaya | webbymaya.com")


def get_subject_stats(send_logs, sg_clickers):
    stats = {}
    for row in send_logs:
        if row.get("status") != "sent": continue
        subj = row.get("subject","").strip()
        if not subj: continue
        em = row.get("email_sent_to","").strip().lower()
        if subj not in stats:
            stats[subj] = {"sent": 0, "clicks": 0, "opens": 0}
        stats[subj]["sent"] += 1
        cd = sg_clickers.get(em, {})
        if cd.get("clicks", 0) > 0 and not cd.get("likely_bot"):
            stats[subj]["clicks"] += 1
        if cd.get("opens", 0) > 0:
            stats[subj]["opens"] += 1
    result = []
    for subj, s in stats.items():
        if s["sent"] < 3: continue
        result.append({
            "subject":    subj,
            "sent":       s["sent"],
            "clicks":     s["clicks"],
            "opens":      s["opens"],
            "click_rate": round(s["clicks"] / s["sent"] * 100, 1),
            "open_rate":  round(s["opens"]  / s["sent"] * 100, 1),
        })
    return sorted(result, key=lambda x: x["click_rate"], reverse=True)


def get_category_click_stats(send_logs, sg_clickers):
    """Rank business categories by click rate."""
    cats = {}
    for row in send_logs:
        if row.get("status") != "sent": continue
        cat   = (row.get("category","") or "unknown").strip().lower()
        email = row.get("email_sent_to","").strip().lower()
        if cat not in cats:
            cats[cat] = {"sent": 0, "clicks": 0, "opens": 0}
        cats[cat]["sent"] += 1
        cd = sg_clickers.get(email, {})
        if cd.get("clicks", 0) > 0 and not cd.get("likely_bot"):
            cats[cat]["clicks"] += 1
        if cd.get("opens", 0) > 0:
            cats[cat]["opens"] += 1
    result = []
    for cat, s in cats.items():
        if s["sent"] < 5: continue
        result.append({
            "category":   cat,
            "sent":       s["sent"],
            "clicks":     s["clicks"],
            "opens":      s["opens"],
            "click_rate": round(s["clicks"] / s["sent"] * 100, 1),
            "open_rate":  round(s["opens"]  / s["sent"] * 100, 1),
        })
    return sorted(result, key=lambda x: x["click_rate"], reverse=True)


def get_send_timing_stats(send_logs, sg_clickers):
    """Analyze which days of week and hours get best click rates."""
    days  = {i: {"sent": 0, "clicks": 0} for i in range(7)}
    hours = {i: {"sent": 0, "clicks": 0} for i in range(24)}
    day_names = ["Mon","Tue","Wed","Thu","Fri","Sat","Sun"]
    for row in send_logs:
        if row.get("status") != "sent": continue
        ts = row.get("timestamp","")
        if not ts: continue
        try:
            dt    = datetime.fromisoformat(ts[:19])
            email = row.get("email_sent_to","").strip().lower()
            clicked = (sg_clickers.get(email, {}).get("clicks", 0) > 0
                       and not sg_clickers.get(email, {}).get("likely_bot"))
            days[dt.weekday()]["sent"]  += 1
            hours[dt.hour]["sent"]      += 1
            if clicked:
                days[dt.weekday()]["clicks"] += 1
                hours[dt.hour]["clicks"]     += 1
        except: continue
    day_result  = [{"label": day_names[i], "sent": days[i]["sent"], "clicks": days[i]["clicks"],
                    "rate": round(days[i]["clicks"] / days[i]["sent"] * 100, 1) if days[i]["sent"] else 0}
                   for i in range(7)]
    hour_result = [{"label": f"{i:02d}:00", "sent": hours[i]["sent"], "clicks": hours[i]["clicks"],
                    "rate": round(hours[i]["clicks"] / hours[i]["sent"] * 100, 1) if hours[i]["sent"] else 0}
                   for i in range(24) if hours[i]["sent"] > 0]
    return {"days": day_result, "hours": hour_result}


def load_email_template():
    p = SCRIPT_DIR / "email_template.json"
    if p.exists():
        try: return json.load(open(p))
        except: pass
    return {
        "subject": "Your {name} customers can't find you online — I made a free site",
        "body": "Hi there,\n\nI noticed {name} doesn't have a website yet — so I built one for you.\n\nIt's free to look at: [link]\n\nIf you like it and want to go live, I charge $1,500 for the full build.\n\nBest,\nMaya\nWebByMaya | webbymaya.com",
        "followup_subject": "Still thinking about it, {name}?",
        "followup_body": "Hi again,\n\nJust following up on my earlier message about {name}. The site I built is still available.\n\nAny questions? Reply here and I'll get right back to you.\n\nBest,\nMaya",
    }


def send_proposal_email(name, email, category):
    """Send a pre-written proposal email to a warm lead."""
    if not SG: return {"ok": False, "error": "No SendGrid key"}
    subject = f"Here's my proposal for {name}"
    html = f"""<div style="font-family:sans-serif;max-width:560px;margin:auto;color:#222;line-height:1.6">
  <p>Hi there,</p>
  <p>Thank you for your interest in getting {name} set up with a professional website. Here's what I can build for you:</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <h3 style="margin:0 0 10px;color:#b8860b">What's Included — $1,500</h3>
    <ul style="margin:0;padding-left:20px">
      <li>Custom website designed for {category} businesses</li>
      <li>Mobile-friendly — looks great on phones</li>
      <li>Services, hours, location, and contact info</li>
      <li>Google-optimized so customers can find you</li>
      <li>Live within 5–7 days of approval</li>
      <li>1 month of free edits after launch</li>
    </ul>
  </div>
  <p>See examples at <a href="https://webbymaya.com/portfolio">webbymaya.com/portfolio</a>.</p>
  <p>Ready to start? Reply to this email or book a call: <a href="https://webbymaya.com/book">webbymaya.com/book</a></p>
  <p>Best,<br><b>Maya</b><br>WebByMaya · <a href="https://webbymaya.com">webbymaya.com</a></p>
</div>"""
    try:
        payload = json.dumps({
            "personalizations": [{"to": [{"email": email}]}],
            "from":    {"email": "maya@webbymaya.com", "name": "Maya — WebByMaya"},
            "subject": subject,
            "content": [{"type": "text/html", "value": html}]
        }).encode()
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send", data=payload,
            headers={"Authorization": f"Bearer {SG}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def send_weekly_digest():
    """Send Maya a weekly performance summary. Called from cron on Sundays."""
    if not SG: return
    try:
        data      = build_dataset()
        hot       = data.get("clicker_leads", [])
        replies   = data.get("gmail_replies", [])
        sg_stats  = data.get("sg_stats", {})
        month_rev = data.get("month_revenue", 0)
        goal      = (data.get("revenue_goal") or {}).get("monthly", 3000)
        pct       = round(month_rev / goal * 100) if goal else 0
        top_leads = sorted(hot, key=lambda x: x.get("score", 0), reverse=True)[:5]
        top_html  = "".join(
            f"<li><b>{l['name']}</b> ({l.get('category','')}) — score {l.get('score',0)}</li>"
            for l in top_leads
        ) or "<li>No hot leads this week</li>"
        html = f"""<div style="font-family:sans-serif;max-width:540px;margin:auto;color:#222">
  <h2 style="color:#b8860b">WebByMaya Weekly Digest</h2>
  <p style="color:#666">{datetime.now().strftime('%B %d, %Y')}</p>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <h3 style="margin:0 0 8px">Revenue This Month</h3>
    <div style="font-size:28px;font-weight:800;color:#b8860b">${month_rev:,.0f}
      <span style="font-size:14px;color:#888">/ ${goal:,} goal ({pct}%)</span></div>
  </div>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <h3 style="margin:0 0 8px">Outreach Stats (All-Time)</h3>
    <ul style="margin:0;padding-left:20px">
      <li>Total sent: <b>{sg_stats.get('requests',0):,}</b></li>
      <li>Opens: <b>{sg_stats.get('opens',0):,}</b></li>
      <li>Clicks: <b>{sg_stats.get('clicks',0):,}</b></li>
      <li>Hot leads: <b>{len(hot)}</b></li>
      <li>Email replies: <b>{len(replies)}</b></li>
    </ul>
  </div>
  <div style="background:#f8f8f8;border-radius:8px;padding:16px;margin:16px 0">
    <h3 style="margin:0 0 8px">Top Leads to Contact This Week</h3>
    <ul style="margin:0;padding-left:20px">{top_html}</ul>
  </div>
  <p style="color:#aaa;font-size:12px">Sent automatically by your WebByMaya dashboard every Sunday.</p>
</div>"""
        payload = json.dumps({
            "personalizations": [{"to": [{"email": "mayasierra1999@gmail.com"}]}],
            "from":    {"email": "maya@webbymaya.com", "name": "WebByMaya"},
            "subject": f"Weekly Digest — ${month_rev:,.0f} earned, {len(hot)} hot leads",
            "content": [{"type": "text/html", "value": html}]
        }).encode()
        req = urllib.request.Request(
            "https://api.sendgrid.com/v3/mail/send", data=payload,
            headers={"Authorization": f"Bearer {SG}", "Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=10)
    except Exception as e:
        print(f"[digest] Failed: {e}")


def fetch_stripe_revenue():
    """Pull payment data from Supabase payment_transactions (written by Lovable/Stripe)."""
    url = (f"{SUPABASE_URL_WBM}/rest/v1/payment_transactions"
           "?select=amount_cents,currency,customer_email,description,kind,environment,created_at"
           "&order=created_at.desc&limit=200")
    req = urllib.request.Request(url, headers={
        "apikey":        SUPABASE_KEY_WBM,
        "Authorization": f"Bearer {SUPABASE_KEY_WBM}",
    })
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=8).read())
        return [{
            "amount":      round(r.get("amount_cents", 0) / 100, 2),
            "currency":    r.get("currency", "usd").upper(),
            "customer":    r.get("customer_email", ""),
            "description": r.get("description", ""),
            "kind":        r.get("kind", ""),
            "environment": r.get("environment", ""),
            "date":        (r.get("created_at") or "")[:10],
        } for r in rows]
    except Exception:
        return []


def generate_homepage_copy(name, category, rating=None, reviews=None, description=""):
    """Call Claude API to generate homepage copy for a business."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    rating_str = f" (rated {rating}/5 with {reviews} reviews on Yelp)" if rating else ""
    prompt = f"""Write homepage copy for a small business website. Be warm, local, and conversion-focused. Keep it concise.

Business: {name}
Type: {category}{rating_str}
{f"Notes: {description}" if description else ""}

Return ONLY a JSON object with these exact keys:
{{
  "headline": "Main H1 headline (under 10 words, catchy)",
  "tagline": "Subheadline (1 sentence, benefit-focused)",
  "about": "About section paragraph (2-3 sentences, local and personal)",
  "cta": "Call-to-action button text (3-5 words)",
  "services_intro": "Brief intro sentence before the services list"
}}"""
    try:
        payload = json.dumps({
            "model": "claude-haiku-4-5-20251001",
            "max_tokens": 600,
            "messages": [{"role": "user", "content": prompt}]
        }).encode()
        req = urllib.request.Request(
            "https://api.anthropic.com/v1/messages",
            data=payload,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json"
            },
            method="POST"
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
        text = resp["content"][0]["text"].strip()
        m = re.search(r'\{.*\}', text, re.DOTALL)
        if m:
            return json.loads(m.group())
        return {"error": "parse_error", "raw": text}
    except Exception as e:
        return {"error": str(e)}


def load_revenue_goal():
    p = SCRIPT_DIR / "revenue_goal.json"
    if p.exists():
        try: return json.load(open(p))
        except: pass
    return {"monthly": 3000}


def get_month_revenue(invoices, stripe_payments=None):
    month_str = datetime.now().strftime("%Y-%m")
    manual = sum(float(inv.get("amount", inv.get("balance", 0)) or 0)
                 for inv in (invoices or [])
                 if inv.get("paid") and
                 (inv.get("date","") or inv.get("paid_date","") or "")[:7] == month_str)
    stripe = sum(p["amount"] for p in (stripe_payments or [])
                 if p.get("date","")[:7] == month_str)
    return manual + stripe


_CACHE = {"data": None, "ts": 0.0, "lock": threading.Lock(), "building": False}

def _refresh_cache():
    """Build fresh dataset and store in cache. Safe to call from any thread."""
    global _CACHE
    with _CACHE["lock"]:
        if _CACHE["building"]:
            return
        _CACHE["building"] = True
    try:
        fresh = build_dataset()
        with _CACHE["lock"]:
            _CACHE["data"] = fresh
            _CACHE["ts"]   = time.time()
    except Exception as e:
        print(f"[cache] refresh failed: {e}")
    finally:
        with _CACHE["lock"]:
            _CACHE["building"] = False

def _cache_loop():
    """Background thread: rebuild data every 5 minutes."""
    _refresh_cache()          # immediate first build
    while True:
        time.sleep(300)
        _refresh_cache()

def get_cached_data():
    with _CACHE["lock"]:
        return _CACHE["data"]

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
                "category":    pr.get("category","") or row.get("category",""),
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
            ts = row.get("date","") or row.get("timestamp","")
            if ts and ts > (matched.get("last_contact") or ""):
                matched["last_contact"] = ts
            matched["touches"].append({
                "type":     "email_out",
                "ts":       ts,
                "note":     email,
                "subject":  row.get("subject",""),
                "log_type": row.get("log_type","outreach"),
            })

    # Add email-only leads (emailed but never texted — 64% of outreach)
    sms_lead_names = {v["name"].strip().lower() for v in leads.values()}
    email_only_seen = {}  # email -> key, to deduplicate multiple sends to same address
    for row in send_logs:
        if row.get("status") != "sent": continue
        name  = row.get("name","").strip()
        email = row.get("email_sent_to","").strip().lower()
        if not email or "@" not in email: continue
        if name.strip().lower() in sms_lead_names: continue  # already merged above
        key = f"email:{email}"
        if key not in leads:
            pr = prospects.get(name.strip().lower(), {})
            leads[key] = {
                "phone": "", "name": name,
                "category":    pr.get("category","") or row.get("category",""),
                "address":     pr.get("address",""),
                "maps_url":    pr.get("maps_url",""),
                "email":       email,
                "clicked":     email in clicker_emails,
                "click_data":  sg_clickers.get(email, {}),
                "sms_sent": 0, "email_sent": 0,
                "replied": False, "opted_out": False,
                "last_contact": "", "touches": [],
                "status": "contacted", "note": "",
                "rating":  pr.get("rating",""),
                "reviews": pr.get("review_count",""),
            }
        ts = row.get("date","") or row.get("timestamp","")
        leads[key]["email_sent"] += 1
        if ts > (leads[key].get("last_contact") or ""):
            leads[key]["last_contact"] = ts
        leads[key]["touches"].append({
            "type":     "email_out",
            "ts":       ts,
            "note":     email,
            "subject":  row.get("subject",""),
            "log_type": row.get("log_type","outreach"),
        })

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
        l["score"] = calc_lead_score(l)

    # Feature 9: duplicates
    phone_counts = Counter(r.get("phone","") for r in sms_logs if r.get("status")=="sent")
    dup_phones   = {p for p, c in phone_counts.items() if c > 1}

    # Cross-zone dedup flags (from dedup_check.py output or live scan)
    dedup_flags = load_csv(SCRIPT_DIR / "dedup_flags.csv") if (SCRIPT_DIR / "dedup_flags.csv").exists() else []

    # Overdue leads — clickers flagged at 2 days, everyone else at 7 days
    # Max 14 days: after that the drip sequence is exhausted, not actionable
    now     = datetime.now()
    overdue = []
    for l in leads.values():
        if l["status"] in ("opted_out","booked","not_interested","won"): continue
        lc = l.get("last_contact","")
        if not lc: continue
        try:
            last      = datetime.fromisoformat(lc)
            days_ago  = (now - last).days
            # Skip leads older than 14 days — drip sequence done, nothing actionable
            if days_ago > 14: continue
            # Skip leads where every email touch was skipped/bounced (unreachable)
            email_touches = [t for t in l.get("touches",[]) if t.get("type") == "email_out"]
            if email_touches and all(
                t.get("note","").lower() in ("skipped","bounced","failed","")
                for t in email_touches
            ): continue
            threshold = timedelta(days=2) if l.get("clicked") else timedelta(days=7)
            if last < (now - threshold):
                overdue.append({
                    "phone":    l["phone"] or l.get("email",""), "name": l["name"],
                    "category": l["category"],
                    "days_ago": days_ago,
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
    email_to_name  = {row.get("email_sent_to","").strip().lower(): row.get("name","")
                      for row in send_logs
                      if row.get("status")=="sent" and row.get("email_sent_to")}
    gmail_replies  = fetch_gmail_replies(email_to_name)

    daily_send_detail = get_daily_send_detail(send_logs, sg_clickers)
    pending_queue, queue_date, queue_csv = get_pending_queue()

    # Engaged = non-bot email clicker OR SMS replier OR email replier
    gmail_replied_emails = {r.get("from_email","").lower() for r in gmail_replies}
    # Hot = email signal only (clicked link OR replied via email) — SMS excluded for now
    real_clickers = [l for l in all_list
                     if ((l.get("clicked") and not l.get("click_data",{}).get("likely_bot"))
                         or l.get("email","").lower() in gmail_replied_emails)
                     and l.get("status") not in ("opted_out","won")]

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
        "brevo2":   sum(1 for r in today_sent if r.get("provider","") == "brevo2"),
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

    reengagement_phones = get_reengagement_phones(send_logs, all_list)
    projects_data = _load_projects()
    active_projects = [p for p in projects_data if p.get("stage") != "Live"]

    # Suggested replies — after all_list is built so we can look up category
    email_to_category = {l.get("email","").lower(): l.get("category","") for l in all_list}
    for r in gmail_replies:
        cat = email_to_category.get(r.get("from_email","").lower(), "")
        r["suggested_reply"] = generate_reply_suggestion(r.get("name",""), cat, r.get("body",""))

    subject_stats  = get_subject_stats(send_logs, sg_clickers)
    category_stats = get_category_click_stats(send_logs, sg_clickers)
    timing_stats   = get_send_timing_stats(send_logs, sg_clickers)
    email_template = load_email_template()
    sched_path     = SCRIPT_DIR / "send_schedule.json"
    send_schedule  = json.load(open(sched_path)) if sched_path.exists() else {}
    invoices_data  = _load_invoices()
    stripe_payments = fetch_stripe_revenue()
    revenue_goal   = load_revenue_goal()
    month_revenue  = get_month_revenue(invoices_data, stripe_payments)

    return {
        "intakes":          fetch_intake_responses(),
        "client_onboarding": fetch_client_onboarding(),
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
        "projects":          projects_data,
        "active_project_count": len(active_projects),
        "invoices":          invoices_data,
        "subject_stats":     subject_stats,
        "category_stats":    category_stats,
        "timing_stats":      timing_stats,
        "email_template":    email_template,
        "send_schedule":     send_schedule,
        "revenue_goal":      revenue_goal,
        "month_revenue":     month_revenue,
        "stripe_payments":   stripe_payments,
        "reengagement_phones": list(reengagement_phones),
        "sms_delivery":   sms_delivery,
        "cat_breakdown":  cat_breakdown,
        "daily_sms":      daily_sms,
        "clicker_leads":  real_clickers,
        "clicker_data":   sg_clickers,
        "daily_send_detail": daily_send_detail,
        "pending_queue":  pending_queue,
        "queue_date":     queue_date,
        "queue_csv":      queue_csv,
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
            "reengagement_count": len(reengagement_phones),
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
body{background:#0d0d0f;color:#d0d0d4;font-family:"Inter",-apple-system,BlinkMacSystemFont,"Segoe UI",Arial,sans-serif;font-size:13px;line-height:1.5;display:flex;flex-direction:column;height:100vh;overflow:hidden}
a{color:#C9A96E;text-decoration:none}
a:hover{color:#dbbe8a}

/* ── Header ──────────────────────────────────────────────────────────────── */
header{background:#09090d;border-bottom:1px solid #16161e;padding:0 24px;height:52px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0;gap:16px}
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
.sidebar{width:200px;background:#09090d;border-right:1px solid #16161e;display:flex;flex-direction:column;flex-shrink:0;overflow-y:auto;padding:8px 0}
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
.pipe-step{padding:16px 12px;text-align:center;border-right:1px solid #1c1c1c;position:relative;cursor:pointer;transition:background .15s}
.pipe-step:hover{background:#161616}
.pipe-step:hover .pipe-label{color:#888}
.pipe-step:last-child{border-right:none}
.pipe-num{font-size:32px;font-weight:700;color:#C9A96E;line-height:1}
.pipe-num.green{color:#27ae60}
.pipe-num.warm{color:#d4a017}
.pipe-num.booked{color:#2980b9}
.pipe-label{color:#444;font-size:10px;text-transform:uppercase;letter-spacing:.6px;margin-top:6px;transition:color .15s}
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
.card{background:#111116;border:1px solid #1e1e28;border-radius:10px;padding:16px 18px;min-width:110px;flex:1;transition:border-color .2s,background .2s,transform .15s,box-shadow .2s;position:relative}
.card:hover{border-color:#28283a;background:#141419}
.card-link{cursor:pointer}
.card-link:hover{border-color:#C9A96E !important;background:#13100a !important;transform:translateY(-3px);box-shadow:0 8px 32px rgba(201,169,110,.18)}
.card-link::after{content:"↗";position:absolute;top:10px;right:12px;font-size:11px;color:#2a2a2a;transition:color .2s}
.card-link:hover::after{color:#C9A96E}
.card-num{font-size:28px;font-weight:700;color:#C9A96E;line-height:1}
.card-num.green{color:#27ae60}
.card-num.red{color:#c0392b}
.card-num.orange{color:#d4a017}
.card-label{color:#666;font-size:10px;margin-top:6px;text-transform:uppercase;letter-spacing:.5px}

/* ── Section titles ──────────────────────────────────────────────────────── */
.section-title{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1.2px;margin-bottom:14px;display:flex;align-items:center;gap:10px}
.section-title::after{content:"";flex:1;height:1px;background:#181818}

/* ── Tables ──────────────────────────────────────────────────────────────── */
.tbl-wrap{overflow-x:auto;border:1px solid #1a1a24;border-radius:10px;overflow:hidden}
table{width:100%;border-collapse:collapse}
th{background:#0d0d12;color:#3a3a52;font-size:10px;text-transform:uppercase;letter-spacing:.5px;padding:10px 14px;text-align:left;border-bottom:1px solid #1a1a24;position:sticky;top:0;z-index:1;font-weight:700}
td{padding:10px 14px;border-bottom:1px solid #14141a;vertical-align:middle;color:#ccc}
tbody tr:last-child td{border-bottom:none}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:#111116}
tr.overdue td{background:#100d00}
tr.overdue:hover td{background:#181200}
.tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:10px;font-weight:700;color:#fff;text-transform:uppercase;letter-spacing:.3px}
.empty{color:#333;text-align:center;padding:52px;font-size:13px}
.notice{background:#111;border:1px solid #1c1c1c;border-left:3px solid #C9A96E;padding:11px 15px;border-radius:6px;margin-bottom:14px;font-size:12px;color:#666;line-height:1.6}

/* ── Lead Panel ──────────────────────────────────────────────────────────── */
#panel-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.7);z-index:100;backdrop-filter:blur(2px)}
#panel-overlay.open{display:block}
#lead-panel{position:fixed;right:-580px;top:0;bottom:0;width:580px;background:#0d0d12;border-left:1px solid #1a1a24;z-index:101;transition:right .22s ease;display:flex;flex-direction:column;overflow:hidden}
#lead-panel.open{right:0}
#panel-header{background:#09090d;border-bottom:1px solid #1a1a24;padding:18px 22px;display:flex;align-items:flex-start;justify-content:space-between}
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

/* ── Lead Score ──────────────────────────────────────────────────────────── */
.score-badge{display:inline-block;padding:2px 7px;border-radius:10px;font-size:10px;font-weight:700;letter-spacing:.2px}
.score-0{background:#1a1a1a;color:#444}
.score-1{background:#1a2a3a;color:#6aafe6}
.score-2{background:#2a1800;color:#C9A96E}
.score-3{background:#0a2a0a;color:#2ecc71}

/* ── Milestone ───────────────────────────────────────────────────────────── */
.milestone-row{display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #141414;cursor:pointer}
.milestone-row:hover{background:#111}
.milestone-row:last-child{border-bottom:none}
.milestone-row input[type=checkbox]{accent-color:#C9A96E;width:14px;height:14px;cursor:pointer;flex-shrink:0}
.milestone-done{text-decoration:line-through;color:#333 !important}

/* ── Invoice ─────────────────────────────────────────────────────────────── */
.inv-card{background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:14px 18px;margin-bottom:8px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:12px}
.inv-card:hover{border-color:#2a2a2a}
.inv-unpaid{border-left:3px solid #C9A96E}
.inv-paid{border-left:3px solid #27ae60;opacity:.65}

/* ── Today page ──────────────────────────────────────────────────────────── */
.today-section{background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:16px 20px;margin-bottom:14px}
.today-section-title{color:#555;font-size:10px;text-transform:uppercase;letter-spacing:1px;margin-bottom:12px;display:flex;align-items:center;gap:10px}
.today-section-title::after{content:"";flex:1;height:1px;background:#181818}
.today-row{display:flex;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid #141414;cursor:pointer;transition:background .1s}
.today-row:hover{background:#131313}
.today-row:last-child{border-bottom:none}

/* ── Queue / warm cards ──────────────────────────────────────────────────── */
.queue-item{background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:13px 16px;margin-bottom:8px;display:grid;grid-template-columns:1fr auto;align-items:center;gap:14px;transition:border-color .15s}
.queue-item:hover{border-color:#2a2a2a}
.queue-info h4{font-size:14px;color:#ddd;margin-bottom:3px;font-weight:600}
.queue-info span{font-size:12px;color:#555}

/* ── Toast ───────────────────────────────────────────────────────────────── */
#toast{position:fixed;bottom:24px;right:24px;background:#C9A96E;color:#111;padding:11px 18px;border-radius:8px;font-weight:700;font-size:12px;display:none;z-index:200;box-shadow:0 6px 28px rgba(0,0,0,.6)}

/* ── Row Actions (inline hover buttons on table rows) ─────────────────────── */
.row-actions{display:flex;gap:5px;opacity:0;transition:opacity .15s;white-space:nowrap;align-items:center}
tr:hover .row-actions,.row-actions:focus-within{opacity:1}
.act-btn{background:#16161e;border:1px solid #24243a;color:#888;padding:3px 9px;border-radius:5px;cursor:pointer;font-size:10px;font-weight:600;letter-spacing:.2px;transition:all .12s;white-space:nowrap;line-height:1.6}
.act-btn:hover{background:#C9A96E;color:#111;border-color:#C9A96E}
.act-btn.sms{border-color:#1e4a2e;color:#2ecc71}
.act-btn.sms:hover{background:#2ecc71;color:#111;border-color:#2ecc71}
.act-btn.email{border-color:#1a3a5a;color:#6aafe6}
.act-btn.email:hover{background:#2980b9;color:#fff;border-color:#2980b9}

/* ── Warm Lead Cards (Notion-style) ────────────────────────────────────────── */
.warm-card{background:#111116;border:1px solid #1e1e28;border-radius:10px;padding:16px 20px;margin-bottom:10px;display:grid;grid-template-columns:1fr auto;align-items:start;gap:16px;cursor:pointer;transition:border-color .15s,background .15s,transform .15s,box-shadow .15s}
.warm-card:hover{border-color:#2a2a40;background:#141419;transform:translateY(-2px);box-shadow:0 6px 24px rgba(0,0,0,.4)}
.wc-name{font-size:15px;font-weight:700;color:#e0e0e8;margin-bottom:5px;letter-spacing:-.1px}
.wc-meta{font-size:12px;color:#4a4a66;display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.wc-tags{display:flex;gap:6px;flex-wrap:wrap;margin-top:9px;align-items:center}
.wc-actions{display:flex;flex-direction:column;gap:6px;align-items:stretch;min-width:90px}

/* ── Quick Popover ─────────────────────────────────────────────────────────── */
#quick-popover{display:none;position:fixed;z-index:500;background:#13131a;border:1px solid #26263a;border-radius:10px;padding:16px 18px;box-shadow:0 16px 56px rgba(0,0,0,.7);min-width:300px;max-width:360px;top:50%;left:50%;transform:translate(-50%,-50%)}
#quick-popover.open{display:block}
.qp-title{font-size:11px;font-weight:700;color:#444;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px}
.qp-name{font-size:15px;font-weight:700;color:#C9A96E;margin-bottom:12px}
.qp-input{width:100%;background:#0d0d12;border:1px solid #26263a;color:#ddd;padding:9px 11px;border-radius:6px;font-size:12px;resize:vertical;font-family:inherit;outline:none;min-height:72px}
.qp-input:focus{border-color:#C9A96E}
.qp-actions{display:flex;gap:6px;margin-top:10px;justify-content:flex-end;flex-wrap:wrap}

/* ── Two-column Today layout ───────────────────────────────────────────────── */
.today-grid{display:grid;grid-template-columns:1fr 320px;gap:18px;align-items:start}
@media(max-width:860px){.today-grid{grid-template-columns:1fr}}

/* ── Lead panel quick-links bar ────────────────────────────────────────────── */
.panel-links{display:flex;gap:6px;padding:10px 22px;border-bottom:1px solid #1a1a24;flex-wrap:wrap;background:#0a0a0e}
.pl-btn{background:#14141a;border:1px solid #22223a;color:#666;padding:5px 12px;border-radius:5px;cursor:pointer;font-size:11px;font-weight:600;transition:all .12s;white-space:nowrap}
.pl-btn:hover{background:#C9A96E;color:#111;border-color:#C9A96E}
.pl-btn.green:hover{background:#2ecc71;color:#111;border-color:#2ecc71}
.pl-btn.blue:hover{background:#2980b9;color:#fff;border-color:#2980b9}
.pl-btn.danger:hover{background:#e74c3c;color:#fff;border-color:#e74c3c}

/* ── Outreach inner tabs ─────────────────────────────────────────────────────── */
.otab-bar{display:flex;gap:0;border-bottom:1px solid #1c1c1c;margin-bottom:20px;overflow-x:auto;flex-shrink:0}
.otab{background:none;border:none;border-bottom:2px solid transparent;color:#444;padding:9px 16px;cursor:pointer;font-size:11px;font-weight:600;text-transform:uppercase;letter-spacing:.6px;white-space:nowrap;transition:color .15s,border-color .15s;margin-bottom:-1px;display:flex;align-items:center;gap:5px}
.otab:hover{color:#aaa;background:#111}
.otab.active{color:#C9A96E;border-bottom-color:#C9A96E;background:#111}
</style>
</head>
<body>

<header>
  <h1>WebByMaya — Outreach Console</h1>
  <div class="hdr-center" id="hdr-health"></div>
  <div class="hdr-right" style="gap:10px">
    <div id="hdr-credit"></div>
    <span id="last-updated"></span>
    <span id="last-refresh" style="font-size:11px;color:#333;margin-left:4px"></span>
    <button class="btn" onclick="location.reload()">↻ Refresh</button>
  </div>
</header>

<div class="main">
  <div class="sidebar">
    <div class="nav-item active" onclick="showPage('today')" id="nav-today">📋 Today</div>
    <div class="nav-item" onclick="showPage('pipeline')" id="nav-pipeline">📊 Pipeline</div>
    <div class="nav-item" onclick="showPage('outreach')" id="nav-outreach">
      📧 Outreach <span class="badge-count gold" id="badge-outreach"></span>
    </div>
    <div class="nav-item" onclick="showPage('all-leads')" id="nav-all-leads">
      👥 All Leads <span class="badge-count blue" id="badge-all-leads" style="background:#1a3a5a;color:#6aafe6"></span>
    </div>
    <div style="flex:1"></div>
    <div class="nav-divider"></div>
    <div class="nav-item" onclick="showPage('intake')" id="nav-intake">
      Intake Forms <span class="badge-count gold" id="badge-intake">0</span>
    </div>
    <!-- Hidden badge spans — updated by JS, not visible -->
    <span id="badge-warm" style="display:none"></span>
    <span id="badge-sms-replies" style="display:none"></span>
    <span id="badge-queue" style="display:none"></span>
    <span id="badge-clickers" style="display:none"></span>
    <span id="badge-projects" style="display:none"></span>
    <span id="badge-invoices" style="display:none"></span>
  </div>

  <div class="content" id="main-content">

    <!-- Page: Today (default) -->
    <div id="page-today">
      <div id="today-content"></div>
    </div>

    <!-- Page: Pipeline — stats, funnel, warm leads, projects, invoices, revenue -->
    <div id="page-pipeline" style="display:none">
      <div id="clicker-alert" style="display:none"></div>
      <div id="nudge-bar" style="display:none"></div>
      <div id="backlog-banner" style="display:none"></div>
      <div id="sms-alert" style="display:none"></div>
      <div class="cards" id="stats-cards"></div>
      <div id="funnel-row" style="margin-bottom:14px"></div>
      <div id="forecast-row" style="margin-bottom:20px"></div>
      <div id="pipeline-row" style="margin-bottom:18px"></div>

      <p class="section-title" style="margin-bottom:12px">Warm Leads — replied or took action</p>
      <div id="warm-list"></div>

      <p class="section-title" style="margin-top:28px;margin-bottom:8px">Active Projects</p>
      <p style="color:#555;font-size:11px;margin-bottom:14px">Clients move here automatically when marked Won or Booked</p>
      <div id="projects-board" style="display:flex;gap:12px;overflow-x:auto;padding-bottom:8px"></div>

      <div style="margin-top:28px;display:flex;align-items:center;justify-content:space-between;margin-bottom:18px;flex-wrap:wrap;gap:12px">
        <p class="section-title" style="margin:0">Invoice & Payment Tracker</p>
        <button class="btn btn-sm" onclick="showNewInvoiceForm()">+ New Invoice</button>
      </div>
      <div id="invoice-new-form" style="display:none;background:#111;border:1px solid #2a2a00;border-radius:8px;padding:16px 20px;margin-bottom:16px">
        <p style="color:#C9A96E;font-size:12px;font-weight:700;margin-bottom:12px;text-transform:uppercase;letter-spacing:.5px">New Invoice</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px">
          <div>
            <label style="color:#666;font-size:11px">Client Name</label>
            <input id="inv-name" list="inv-name-list" placeholder="Business name"
              style="width:100%;background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 10px;border-radius:4px;font-size:12px;margin-top:4px">
            <datalist id="inv-name-list"></datalist>
          </div>
          <div>
            <label style="color:#666;font-size:11px">Amount ($)</label>
            <input id="inv-amount" type="number" value="799" placeholder="799"
              style="width:100%;background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 10px;border-radius:4px;font-size:12px;margin-top:4px">
          </div>
          <div>
            <label style="color:#666;font-size:11px">Due Date</label>
            <input id="inv-due" type="date"
              style="width:100%;background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 10px;border-radius:4px;font-size:12px;margin-top:4px">
          </div>
          <div>
            <label style="color:#666;font-size:11px">Package / Notes</label>
            <input id="inv-notes" placeholder="Starter site, domain, etc."
              style="width:100%;background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:7px 10px;border-radius:4px;font-size:12px;margin-top:4px">
          </div>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-sm" onclick="createInvoice()">Create Invoice</button>
          <button class="btn btn-sm btn-outline" onclick="document.getElementById('invoice-new-form').style.display='none'">Cancel</button>
        </div>
      </div>
      <div id="invoices-summary" style="display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px"></div>
      <div id="invoice-list"></div>
      <div id="stripe-payments-section" style="margin-top:16px"></div>

      <p class="section-title" style="margin-top:28px;margin-bottom:12px">Revenue Log</p>
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
      <div id="revenue-chart" style="background:#141414;border:1px solid #222;border-radius:6px;padding:16px;margin-bottom:24px"></div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Date</th><th>Business</th><th>Category</th><th>Package</th><th>Amount</th></tr></thead>
        <tbody id="revenue-rows"></tbody>
      </table></div>
    </div>

    <!-- Outreach tab bar — persistent header for all outreach sub-pages -->
    <div id="outreach-tabbar" style="display:none">
      <div class="otab-bar">
        <button class="otab" data-ot="send-queue" onclick="showPage('send-queue')">
          📋 Send Queue <span id="badge-send-queue" style="background:#3a2a00;color:#C9A96E;border-radius:8px;padding:1px 6px;font-size:10px;font-weight:700"></span>
        </button>
        <button class="otab" data-ot="send-detail" onclick="showPage('send-detail')">Send History</button>
        <button class="otab" data-ot="email-replies" onclick="showPage('email-replies')">
          Email Replies <span id="badge-email-replies" style="background:#2a1a3a;color:#9b59b6;border-radius:8px;padding:1px 6px;font-size:10px;font-weight:700"></span>
        </button>
        <button class="otab" data-ot="email" onclick="showPage('email')">Email Log</button>
        <button class="otab" data-ot="bounces" onclick="showPage('bounces')">Bounces</button>
        <button class="otab" data-ot="analytics" onclick="showPage('analytics')">Analytics</button>
        <button class="otab" data-ot="zones" onclick="showPage('zones')">Zones</button>
        <button class="otab" data-ot="subjects" onclick="showPage('subjects')">📊 Subject Lines</button>
        <button class="otab" data-ot="categories" onclick="showPage('categories')">🏷 Categories</button>
        <button class="otab" data-ot="timing" onclick="showPage('timing')">⏰ Best Time</button>
        <button class="otab" data-ot="templates" onclick="showPage('templates')">✏ Templates</button>
        <button class="otab" data-ot="copywriter" onclick="showPage('copywriter')">✨ Copy Writer</button>
      </div>
    </div>

    <!-- Outreach sub-pages -->
    <div id="page-send-queue" style="display:none">
      <div id="send-queue-content"></div>
    </div>

    <div id="page-send-detail" style="display:none">
      <div id="send-detail-content"></div>
    </div>

    <div id="page-email-replies" style="display:none">
      <div class="notice">Replies land at <strong>mayas.worldwide.web@gmail.com</strong>
        &nbsp;<a href="https://mail.google.com" target="_blank">Open Gmail →</a></div>
      <p class="section-title">📧 Email Replies — inbound from Gmail</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th style="width:100px">Time</th><th>Reply &amp; Draft</th><th style="width:60px"></th></tr></thead>
        <tbody id="email-replies-body"></tbody>
      </table></div>
    </div>

    <div id="page-email" style="display:none">
      <div class="notice">Email replies → <strong>maya@webbymaya.com</strong>
        &nbsp;<a href="https://mail.google.com" target="_blank">Open Gmail →</a></div>
      <p class="section-title">Email Send Log (most recent first)</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Email</th><th>Status</th></tr></thead>
        <tbody id="email-body"></tbody>
      </table></div>
    </div>

    <div id="page-bounces" style="display:none">
      <p class="section-title">Bounce & Suppression List</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Email</th><th>Type</th><th>Reason</th></tr></thead>
        <tbody id="bounces-body"></tbody>
      </table></div>
    </div>

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
      <p style="color:#555;font-size:11px;margin-bottom:10px">Run <code>python dedup_check.py --write</code> to refresh.</p>
      <div id="dedup-section"></div>
    </div>

    <div id="page-zones" style="display:none">
      <p class="section-title">Zone Performance</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Zone</th><th>Date Run</th><th>Businesses</th><th>SMS Sent</th><th>Emails Sent</th><th>Open %</th><th>Click %</th></tr></thead>
        <tbody id="zones-body"></tbody>
      </table></div>
    </div>

    <div id="page-subjects" style="display:none">
      <div id="subjects-content"></div>
    </div>

    <div id="page-categories" style="display:none">
      <div id="categories-content"></div>
    </div>

    <div id="page-timing" style="display:none">
      <div id="timing-content"></div>
    </div>

    <div id="page-templates" style="display:none">
      <div id="templates-content"></div>
    </div>

    <div id="page-copywriter" style="display:none">
      <div id="copywriter-content"></div>
    </div>

    <!-- Page: All Leads -->
    <div id="page-all-leads" style="display:none">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:14px;flex-wrap:wrap">
        <p class="section-title" style="margin:0">All Contacts</p>
        <input id="lead-search" type="text" placeholder="Search name or category..."
          oninput="filterLeads()"
          style="background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:6px 12px;border-radius:3px;font-size:13px;width:240px">
        <label style="color:#7ed321;font-size:12px;cursor:pointer;font-weight:600">
          <input type="checkbox" id="show-clickers" onchange="filterLeads()" style="margin-right:4px">
          🔥 Engaged only (clicked · replied)
        </label>
        <label style="color:#888;font-size:12px;cursor:pointer">
          <input type="checkbox" id="show-dups" onchange="filterLeads()" style="margin-right:4px">
          Duplicates only
        </label>
        <label style="color:#888;font-size:12px;cursor:pointer">
          <input type="checkbox" id="show-overdue" onchange="filterLeads()" style="margin-right:4px">
          Overdue (7d+)
        </label>
        <label style="color:#888;font-size:12px;cursor:pointer">
          <input type="checkbox" id="show-reengaged" onchange="filterLeads()" style="margin-right:4px">
          Re-engaged
        </label>
      </div>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Business</th><th>Category</th><th>Score</th><th>Status</th><th>SMS</th><th>Email</th><th>Replied</th><th>Last Contact</th><th></th></tr></thead>
        <tbody id="all-leads-body"></tbody>
      </table></div>
    </div>

    <!-- Intake Forms -->
    <div id="page-intake" style="display:none">
      <p class="section-title">Website Intake Form Submissions (webbymaya.com/book)</p>
      <div id="intake-list"></div>
    </div>

    <!-- SMS log kept for data access but not linked in nav -->
    <div id="page-sms" style="display:none">
      <p class="section-title">SMS Send Log</p>
      <div class="tbl-wrap"><table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Phone</th><th>Status</th></tr></thead>
        <tbody id="sms-body"></tbody>
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
<div id="quick-popover"></div>

<script>
const DATA = __DATA__;
let currentPhone = null;

// ── Response templates ─────────────────────────────────────────────────────────

const TEMPLATES = [
  { keys: ["how much","price","cost","rate","charge","fee"],
    sms: "Sites start at $499 — design, mobile build, SEO setup, live in 7 days. Fill out my quick form and I'll send a full breakdown: webbymaya.com/book — Maya",
    email: "Hi,\n\nSites start at $499 — that includes the full design, mobile-friendly build, basic SEO setup, and go-live within 7 days. No monthly fees.\n\nEverything's handled by email — fill out my intake form and I'll go over it all: webbymaya.com/book\n\n— Maya" },

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
  const city = address ? address.split(',').slice(-2).join(',').trim() : 'Philadelphia, PA';
  const r = await fetch('/action/generate-mockup', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, category, phone: bizPhone, city})
  });
  const d = await r.json();
  return d;
}

async function generateMockupPanel(phone, name, category, address) {
  const pv = document.getElementById('panel-mockup-preview');
  if (pv) { pv.innerHTML = '<span style="color:#555;font-size:12px">Generating mockup…</span>'; }
  const d = await generateMockup(phone, name, category, phone, address);
  if (!pv) return;
  if (d.ok) {
    const url = d.url;
    toast('Mockup ready!');
    pv.innerHTML = `
      <div style="background:#0a0a0a;border:1px solid #222;border-radius:6px;overflow:hidden">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 12px;border-bottom:1px solid #1a1a1a">
          <span style="font-size:11px;color:#555">Mockup preview — same as what's emailed</span>
          <a href="${url}" target="_blank" class="btn btn-sm btn-outline" style="font-size:10px;padding:3px 8px">Open full ↗</a>
        </div>
        <iframe src="${url}" style="width:100%;height:340px;border:none;display:block;transform:scale(1);transform-origin:top left"></iframe>
      </div>`;
    // Store URL in notes
    const notes = document.getElementById('panel-note-txt');
    if (notes && !notes.value.includes('mockup')) {
      notes.value = (notes.value ? notes.value + '\n' : '') + 'Mockup: ' + url;
    }
  } else {
    pv.innerHTML = `<span style="color:#e74c3c;font-size:12px">Error: ${d.error||'unknown'}</span>`;
  }
}

function previewEmail(name, category, email, subject) {
  const w = window.open('', '_blank', 'width=680,height=700,scrollbars=yes');
  w.document.write('<html><head><title>Email Preview</title></head><body style="margin:0;background:#f4f4f4"><p style="font-family:Arial;font-size:12px;color:#999;padding:12px 20px">Loading preview…</p></body></html>');
  fetch('/action/preview-email', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, category, subject})
  }).then(r=>r.json()).then(d=>{
    if (d.html) {
      w.document.open();
      w.document.write(d.html);
      w.document.close();
    } else {
      w.document.body.innerHTML = '<p style="font-family:Arial;padding:20px;color:red">Error: ' + (d.error||'unknown') + '</p>';
    }
  });
}

function previewEmailTemplate(name, category) {
  previewEmail(name, category, '', '');
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
      <span style="color:#7ed321;font-weight:700">🔥 ${leads.length} engaged lead${leads.length!==1?'s':''}</span>
      — ${names}${more}
      <span style="color:#555;font-size:11px;margin-left:6px">· clicked, replied, or responded — follow up now</span>
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
      <div class="pipe-step" onclick="showPage('all-leads')" title="View all contacted leads">
        <div class="pipe-num">${p.contacted.toLocaleString()}</div>
        <div class="pipe-label">Contacted</div>
      </div>
      <div class="pipe-step" onclick="showPage('warm')" title="View warm leads">
        <div class="pipe-num warm">${p.warm}</div>
        <div class="pipe-label">Warm ↗</div>
      </div>
      <div class="pipe-step" onclick="showPage('projects')" title="View booked projects">
        <div class="pipe-num booked">${p.booked}</div>
        <div class="pipe-label">Booked</div>
      </div>
      <div class="pipe-step" onclick="showPage('projects')" title="View won projects">
        <div class="pipe-num green">${p.won}</div>
        <div class="pipe-label">Won 🏆</div>
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

  const clickPct = del ? Math.round((sg.clicks||0) / del * 100) : 0;
  document.getElementById('stats-cards').innerHTML = `
    <div class="card card-link" style="border-color:#2a4a00" onclick="showPage('all-leads');document.getElementById('show-clickers').checked=true;filterLeads()">
      <div class="card-num" style="color:#7ed321">${s.clicker_count}</div>
      <div class="card-label">🔥 Hot Leads</div>
      <div style="color:#4a5a00;font-size:10px;margin-top:5px">clicked email link · email replied</div>
    </div>
    <div class="card card-link" onclick="showPage('email-replies')">
      <div class="card-num" style="color:#9b59b6">${DATA.gmail_replies.length}</div>
      <div class="card-label">Email Replies</div>
      <div style="color:#555;font-size:10px;margin-top:5px">inbound to Gmail</div>
    </div>
    <div class="card card-link" onclick="showPage('analytics')">
      <div class="card-num green">${openPct}%</div>
      <div class="card-label">Open Rate</div>
      <div style="color:#555;font-size:10px;margin-top:5px">${(sg.opens||0).toLocaleString()} opens · ${s.total_email.toLocaleString()} sent</div>
    </div>
    <div class="card card-link" onclick="showPage('send-detail')" style="border-color:#1a2a1a">
      <div class="card-num" style="color:#a8e060">${clickPct}%</div>
      <div class="card-label">Click Rate</div>
      <div style="color:#555;font-size:10px;margin-top:5px">${(sg.clicks||0).toLocaleString()} clicks · see who →</div>
    </div>
    <div class="card card-link" onclick="showPage('bounces')">
      <div class="card-num red">${s.bounces}</div>
      <div class="card-label">Bounces</div>
      <div style="color:#555;font-size:10px;margin-top:5px">${s.total_email ? Math.round(s.bounces/s.total_email*100) : 0}% of sent</div>
    </div>

    ${(() => {
      const pt  = DATA.provider_today || {};
      const ex  = DATA.provider_exhausted || {};
      const ig  = DATA.ig_stats || {};
      const providers = [
        { key:'sendgrid', label:'SendGrid', limit:100,  color:'#2980b9' },
        { key:'brevo',    label:'Brevo 1',  limit:300,  color:'#27ae60' },
        { key:'brevo2',   label:'Brevo 2',  limit:300,  color:'#1abc9c' },
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

    ${(() => {
      const active = DATA.active_project_count || 0;
      const cap = 5;
      const pct = Math.min(100, Math.round(active / cap * 100));
      const capColor = active >= cap ? '#e74c3c' : active >= 3 ? '#d4a017' : '#27ae60';
      const capLabel = active >= cap ? 'AT CAPACITY' : active >= 3 ? 'Busy' : 'Available';
      const nextDl = (DATA.projects||[])
        .filter(p => p.stage !== 'Live' && p.deadline)
        .map(p => p.deadline).sort()[0];
      return `<div class="card card-link" onclick="showPage('projects')" style="min-width:140px">
        <div class="card-num" style="color:${capColor}">${active}/${cap}</div>
        <div class="card-label">Capacity</div>
        <div style="font-size:10px;color:${capColor};margin-top:4px;font-weight:700">${capLabel}</div>
        <div style="margin-top:6px;background:#1a1a1a;border-radius:3px;height:5px">
          <div style="width:${pct}%;background:${capColor};height:5px;border-radius:3px;transition:width .3s"></div>
        </div>
        ${nextDl ? `<div style="font-size:10px;color:#555;margin-top:4px">Next deadline: ${nextDl}</div>` : ''}
      </div>`;
    })()}
  `;
  document.getElementById('badge-warm').textContent         = s.warm || '';
  const smsBadgeCt = DATA.real_replies.length + DATA.opt_outs.length + DATA.auto_replies.length;
  const emailBadgeCt = (DATA.gmail_replies||[]).length;
  document.getElementById('badge-sms-replies').textContent   = smsBadgeCt || '';
  document.getElementById('badge-email-replies').textContent = emailBadgeCt || '';
  document.getElementById('badge-queue').textContent         = DATA.queue.filter(q=>q.sent==='no').length || '';
  document.getElementById('badge-intake').textContent    = (DATA.intakes||[]).length || '';
  document.getElementById('badge-all-leads').textContent = DATA.leads.length.toLocaleString();
  document.getElementById('badge-clickers').textContent  = s.clicker_count || '';
  const _bout = document.getElementById('badge-outreach');
  if (_bout) _bout.textContent = emailBadgeCt || '';
  document.getElementById('last-updated').textContent    = 'Updated ' + new Date().toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});

  const dupCt = DATA.dup_phones.length;
  if (dupCt) {
    const bd = document.getElementById('badge-dups');
    if (bd) { bd.style.display = ''; bd.textContent = dupCt + ' dup'; }
  }
}

// ── Today / Daily Command Center ───────────────────────────────────────────────

function renderToday() {
  const el = document.getElementById('today-content');
  if (!el) return;
  const now     = new Date();
  const today   = now.toISOString().slice(0,10);
  const dateStr = now.toLocaleDateString('en-US',{weekday:'long',month:'long',day:'numeric'});

  // ── Section 1: Needs attention ────────────────────────────────────────────
  // Email replies (highest priority — someone wrote back)
  const gmailReplies = (DATA.gmail_replies || []).map(r => {
    const lead = DATA.leads.find(l => l.email === r.from_email) || {};
    return { ...r, _lead: lead, _type: 'email_reply', _ts: r.ts };
  });

  // Email clickers not already in replies
  const repliedEmails = new Set(gmailReplies.map(r => r.from_email));
  const clickers = (DATA.clicker_leads || [])
    .filter(l => l.email && !repliedEmails.has(l.email))
    .map(l => ({ _lead: l, _type: 'clicked', _ts: l.last_contact, name: l.name,
                 from_email: l.email, category: l.category }));

  const attention = [...gmailReplies, ...clickers]
    .sort((a, b) => (b._ts || '').localeCompare(a._ts || ''));

  const attRows = attention.map(item => {
    const lead  = item._lead || {};
    const phone = lead.phone || '';
    const email = item.from_email || lead.email || '';
    const name  = item.name || lead.name || email;
    const cat   = item.category || lead.category || '';

    let reasonBadge, actionBtn;
    if (item._type === 'email_reply') {
      reasonBadge = `<span style="background:#1a0d2a;color:#9b59b6;font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px">EMAIL REPLY</span>`;
      const rSubj = encodeURIComponent('Re: ' + (item.subject||''));
      const rBody = encodeURIComponent(item.suggested_reply||'');
      actionBtn   = `<a class="btn btn-sm" style="background:#1a0d2a;color:#9b59b6;border:1px solid #6a3a8a;text-decoration:none;font-size:11px"
                       href="mailto:${email}?subject=${rSubj}&body=${rBody}" onclick="event.stopPropagation()">✉ Reply →</a>`;
    } else {
      reasonBadge = `<span style="background:#1a3a00;color:#7ed321;font-size:9px;font-weight:700;padding:2px 7px;border-radius:3px">CLICKED LINK</span>`;
      actionBtn   = email
        ? `<button class="btn btn-sm" style="background:#1a2a0a;color:#a8e060;border:1px solid #3a6a10;font-size:11px"
             onclick="event.stopPropagation();sendQuickEmail('${phone}','${esc(name)}','${esc(cat)}','${esc(email)}')">📧 Follow Up</button>`
        : '';
    }

    const snippet = item.snippet ? `<div style="color:#444;font-size:11px;margin-top:2px;font-style:italic">"${item.snippet.slice(0,80)}${item.snippet.length>80?'…':''}"</div>` : '';

    return `<div class="today-row" onclick="${phone ? `openPanel('${phone}')` : ''}">
      <div style="flex:1;min-width:0">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">
          <span style="font-weight:600;color:#e0e0e0;font-size:14px">${name}</span>
          ${reasonBadge}
          <span style="color:#444;font-size:11px">${cat}</span>
        </div>
        ${snippet}
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0;margin-left:12px">
        ${actionBtn}
        ${phone ? `<button class="btn btn-sm btn-outline" style="font-size:11px" onclick="event.stopPropagation();openPanel('${phone}')">View</button>` : ''}
      </div>
    </div>`;
  }).join('');

  // ── Section 2: Today's send ───────────────────────────────────────────────
  const sentToday   = (DATA.send_logs || []).filter(r => r.status === 'sent' && (r.timestamp || r.date || '').startsWith(today)).length;
  const queueCount  = (DATA.pending_queue || []).length;
  const pt          = DATA.provider_today || {};
  const ex          = DATA.provider_exhausted || {};
  const providers   = [
    {key:'sendgrid',label:'SG',  limit:100,  color:'#2980b9'},
    {key:'brevo',   label:'Br1', limit:300,  color:'#27ae60'},
    {key:'brevo2',  label:'Br2', limit:300,  color:'#1abc9c'},
    {key:'gmail',   label:'GM',  limit:500,  color:'#e67e22'},
  ];
  const quotaBars = providers.map(p => {
    const used = pt[p.key] || 0;
    const pct  = Math.min(100, Math.round(used / p.limit * 100));
    const done = ex[p.key];
    return `<div style="display:flex;align-items:center;gap:6px">
      <span style="font-size:10px;color:#444;width:18px">${p.label}</span>
      <div style="width:60px;background:#1a1a24;border-radius:2px;height:4px">
        <div style="width:${pct}%;background:${done?'#333':p.color};height:4px;border-radius:2px"></div>
      </div>
      <span style="font-size:10px;color:${done?'#e74c3c':'#444'}">${used}/${p.limit}</span>
    </div>`;
  }).join('');

  // ── Section 3: Money ─────────────────────────────────────────────────────
  const invoices  = DATA.invoices || [];
  const unpaid    = invoices.filter(i => !i.balance_paid);
  const unpaidAmt = unpaid.reduce((s, i) => s + (parseFloat(i.balance) || 0), 0);

  const moneyRows = unpaid.slice(0, 5).map(inv => {
    const dueDate = inv.due_date || '';
    const overdue = dueDate && dueDate < today;
    return `<div class="today-row" onclick="showPage('invoices')">
      <div style="flex:1">
        <span style="font-weight:600;color:#e0e0e0">${inv.client}</span>
        <span style="color:#555;font-size:11px;margin-left:8px">${inv.type || 'balance'}</span>
        ${overdue ? `<span style="color:#e74c3c;font-size:10px;margin-left:6px">OVERDUE</span>` : dueDate ? `<span style="color:#555;font-size:10px;margin-left:6px">due ${dueDate}</span>` : ''}
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
        <span style="color:#C9A96E;font-weight:700">$${(parseFloat(inv.balance)||0).toLocaleString()}</span>
        <button class="btn btn-sm btn-outline" style="font-size:10px"
          onclick="event.stopPropagation();markInvoicePaid('${inv.id}')">Mark Paid</button>
      </div>
    </div>`;
  }).join('');

  // ── Section 4: Quick status bar ──────────────────────────────────────────
  const active     = DATA.active_project_count || 0;
  const capColor   = active >= 5 ? '#e74c3c' : active >= 3 ? '#f39c12' : '#27ae60';
  const overdueLen = (DATA.overdue || []).length;

  // Revenue goal bar
  const goal    = (DATA.revenue_goal||{}).monthly || 3000;
  const earned  = DATA.month_revenue || 0;
  const gPct    = Math.min(Math.round(earned / goal * 100), 100);
  const gColor  = gPct >= 100 ? '#7ed321' : gPct >= 50 ? '#C9A96E' : '#e74c3c';
  const daysInMo  = new Date(now.getFullYear(), now.getMonth()+1, 0).getDate();
  const expPct    = Math.round(now.getDate() / daysInMo * 100);
  const pace      = gPct >= expPct ? '▲ ahead' : gPct < expPct - 15 ? '▼ behind' : '→ on pace';
  const paceColor = gPct >= expPct ? '#7ed321' : gPct < expPct - 15 ? '#e74c3c' : '#555';
  const goalBar = `
  <div style="background:#0d0d10;border:1px solid #1c1c28;border-radius:10px;padding:14px 20px;margin-bottom:18px">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
      <div>
        <span style="font-size:24px;font-weight:800;color:#C9A96E">$${earned.toLocaleString()}</span>
        <span style="font-size:12px;color:#333;margin-left:6px">/ $${goal.toLocaleString()} goal</span>
      </div>
      <div style="display:flex;align-items:center;gap:10px">
        <span style="font-size:11px;color:${paceColor}">${pace}</span>
        <span style="font-size:12px;color:#333">${gPct}%</span>
        <button class="btn btn-sm btn-outline" style="font-size:10px" onclick="showGoalEditor()">Edit</button>
      </div>
    </div>
    <div style="background:#111;border-radius:4px;height:7px;position:relative">
      <div style="background:${gColor};height:7px;border-radius:4px;width:${gPct}%;transition:width .6s"></div>
      <div style="position:absolute;top:-3px;left:${expPct}%;width:2px;height:13px;background:#2a2a2a;border-radius:1px" title="Expected by today"></div>
    </div>
    ${earned===0?'<div style="font-size:11px;color:#2a2a2a;margin-top:7px">No paid invoices this month — mark one paid in Pipeline → Invoices</div>':''}
  </div>`;

  // Aging alerts: clickers not followed up in 48h+, everyone else in 7d+
  const _now48h = Date.now() - 48*3600*1000;
  const _now7d  = Date.now() - 7*24*3600*1000;
  const _now14d = Date.now() - 14*24*60*60*1000;
  const _aging  = (DATA.leads||[]).filter(l => {
    if (!l.last_contact) return false;
    if (['opted_out','won','booked','not_interested'].includes(l.status)) return false;
    const ms = new Date(l.last_contact).getTime();
    if (ms < _now14d) return false;  // older than 14 days = drip exhausted, not actionable
    return l.clicked ? ms < _now48h : (ms < _now7d && (l.email_sent||0) >= 1);
  }).sort((a,b) => new Date(a.last_contact) - new Date(b.last_contact)).slice(0,5);

  const agingHtml = _aging.length ? `
  <div style="background:#130808;border:1px solid #2e1212;border-radius:10px;padding:14px 18px;margin-bottom:18px">
    <div style="font-size:11px;color:#e74c3c;font-weight:700;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">
      ⚠ ${_aging.length} lead${_aging.length!==1?'s':''} overdue for follow-up
    </div>
    ${_aging.map(l => {
      const days  = Math.floor((Date.now()-new Date(l.last_contact).getTime())/86400000);
      const badge = l.clicked ? '<span style="background:#2a1500;color:#f39c12;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:5px">CLICKED</span>' : '';
      const fuEmail = 'mailto:'+l.email+'?subject='+encodeURIComponent('Following up, '+l.name)+'&body='+encodeURIComponent('Hi there,\n\nJust wanted to follow up on my earlier message about getting '+l.name+' set up with a website.\n\nAny questions I can answer?\n\nBest,\nMaya\nWebByMaya | webbymaya.com');
      return '<div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #1e0d0d">'
        +'<div><span style="font-size:13px;color:#ddd;cursor:pointer" onclick="openPanel(\''+(l.phone||l.email)+'\')">'
        +l.name+'</span>'+badge
        +'<div style="font-size:11px;color:#444;margin-top:2px">'+(l.category||'')+(l.category?' · ':'')+days+'d ago</div></div>'
        +'<a href="'+fuEmail+'" class="btn btn-sm" style="background:#200a0a;border-color:#3a1212;color:#e74c3c;text-decoration:none;font-size:11px;flex-shrink:0">Follow Up</a>'
        +'</div>';
    }).join('')}
  </div>` : '';

  el.innerHTML = `
    <div style="margin-bottom:22px">
      <div style="color:#C9A96E;font-size:11px;font-weight:700;letter-spacing:1.5px;text-transform:uppercase;margin-bottom:2px">Morning Briefing</div>
      <div style="color:#2a2a3a;font-size:12px">${dateStr}</div>
    </div>

    ${goalBar}

    ${agingHtml}

    <!-- SECTION 1: Needs attention -->
    <div style="margin-bottom:24px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <span style="color:#e0e0e0;font-size:13px;font-weight:700">
          ${attention.length ? `🔥 Needs your attention` : '✓ Nothing urgent'}
        </span>
        ${attention.length ? `<span style="background:#1a3a00;color:#7ed321;font-size:10px;font-weight:700;padding:2px 8px;border-radius:3px">${attention.length}</span>` : ''}
      </div>
      ${attention.length
        ? attRows
        : `<div style="color:#2a2a3a;font-size:13px;padding:12px 0">No email replies or clickers right now. Check back after today's send goes out.</div>`}
    </div>

    <!-- SECTION 2: Today's send -->
    <div style="background:#111;border:1px solid #1c1c1c;border-radius:8px;padding:16px 20px;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
        <div style="flex:1">
          <div style="font-size:13px;font-weight:700;color:#e0e0e0;margin-bottom:4px">📧 Today's Send</div>
          <div style="font-size:12px;color:#555">
            ${sentToday > 0
              ? `<span style="color:#27ae60;font-weight:600">${sentToday} sent</span> today`
              : queueCount > 0
                ? `<span style="color:#C9A96E;font-weight:600">${queueCount} queued</span> — not sent yet`
                : `No queue found yet — runs at 9AM`}
          </div>
        </div>
        <div style="display:flex;gap:6px;align-items:center;flex-wrap:wrap">
          ${quotaBars}
        </div>
        <div style="display:flex;gap:8px;flex-shrink:0">
          <button class="btn btn-sm btn-outline" onclick="showPage('send-queue')">Preview Queue →</button>
          ${sentToday === 0 && queueCount > 0
            ? `<button class="btn btn-sm btn-green" onclick="sendQueueNow()">Send Now</button>`
            : `<button class="btn btn-sm btn-outline" onclick="showPage('send-detail')">View History →</button>`}
        </div>
      </div>
    </div>

    <!-- SECTION 3: Money -->
    ${unpaid.length ? `
    <div style="background:#111;border:1px solid #2a2200;border-radius:8px;padding:16px 20px;margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:12px">
        <span style="font-size:13px;font-weight:700;color:#e0e0e0">💰 Money Owed</span>
        <span style="color:#C9A96E;font-weight:700;font-size:14px">$${unpaidAmt.toLocaleString()}</span>
        <span style="color:#555;font-size:11px">across ${unpaid.length} invoice${unpaid.length!==1?'s':''}</span>
      </div>
      ${moneyRows}
      ${unpaid.length > 5 ? `<div style="color:#444;font-size:11px;margin-top:8px;cursor:pointer" onclick="showPage('invoices')">${unpaid.length-5} more — view all invoices →</div>` : ''}
    </div>` : ''}

    <!-- SECTION 4: Quick status line -->
    <div style="display:flex;gap:20px;flex-wrap:wrap;padding:10px 0;border-top:1px solid #151515;margin-top:4px">
      <span style="font-size:11px;color:#333">
        Capacity: <span style="color:${capColor};font-weight:600">${active}/5</span> active projects
      </span>
      ${overdueLen ? `<span style="font-size:11px;color:#333;cursor:pointer" onclick="showPage('all-leads');document.getElementById('show-overdue').checked=true;filterLeads()">
        Overdue: <span style="color:#f39c12;font-weight:600">${overdueLen}</span> leads 7d+ no contact
      </span>` : ''}
      <span style="font-size:11px;color:#333;cursor:pointer" onclick="showPage('all-leads')">
        Total reached: <span style="color:#555;font-weight:600">${(DATA.leads||[]).length.toLocaleString()}</span>
      </span>
    </div>`;
}

// ── Warm Leads ─────────────────────────────────────────────────────────────────

function renderWarm() {
  const el = document.getElementById('warm-list');
  if (!DATA.warm.length) { el.innerHTML = '<p class="empty">No warm leads yet. Keep sending!</p>'; return; }
  el.innerHTML = DATA.warm.map(l => {
    const score  = l.score || 0;
    const sClass = score >= 60 ? 'score-3' : score >= 35 ? 'score-2' : score >= 15 ? 'score-1' : 'score-0';
    const hotBadge   = l.clicked ? '<span style="background:#1a3a00;color:#7ed321;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.2px">🔥 HOT</span>' : '';
    const replyBadge = l.replied ? '<span style="background:#2a1a00;color:#f39c12;font-size:10px;font-weight:700;padding:2px 7px;border-radius:4px;letter-spacing:.2px">REPLIED</span>' : '';
    const ratingHtml = l.rating ? `<span style="color:#C9A96E;font-size:11px">★ ${l.rating}</span>` : '';
    const lastDay    = daysAgo(l.last_contact).replace(/<[^>]+>/g,'');
    const emailBtn   = l.email
      ? `<button class="pl-btn blue" onclick="event.stopPropagation();sendQuickEmail('${l.phone}','${esc(l.name)}','${esc(l.category)}','${esc(l.email)}')" style="font-size:10px">📧 Email</button>`
      : '';
    return `
    <div class="warm-card" onclick="openPanel('${l.phone}')">
      <div>
        <div class="wc-name">${l.name}</div>
        <div class="wc-meta">
          <span style="text-transform:capitalize;color:#555">${l.category}</span>
          ${ratingHtml}
          <span style="color:#3a3a52">${l.sms_sent} SMS · ${l.email_sent} email${l.email_sent!==1?'s':''}</span>
          <span style="color:${lastDay.includes('d ago')&&parseInt(lastDay)>=7?'#f39c12':'#3a3a52'}">${lastDay}</span>
        </div>
        <div class="wc-tags">
          ${hotBadge}${replyBadge}
          <span class="score-badge ${sClass}">Score: ${score}</span>
        </div>
      </div>
      <div class="wc-actions">
        <button class="pl-btn green" onclick="event.stopPropagation();openPanel('${l.phone}')" style="text-align:center;font-size:11px">View →</button>
        <button class="pl-btn sms" onclick="event.stopPropagation();sendQuickSms('${l.phone}','${esc(l.name)}','${esc(l.category)}')" style="background:#0f1e10;border-color:#1e4a2e;color:#2ecc71;font-size:10px;text-align:center">📱 SMS</button>
        ${emailBtn}
        ${l.email ? `<button class="pl-btn" onclick="event.stopPropagation();sendProposal('${esc(l.name)}','${esc(l.email)}','${esc(l.category||'')}')" style="background:#1a1000;border-color:#3a2800;color:#C9A96E;font-size:10px;text-align:center">📄 Proposal</button>` : ''}
        ${l.email ? `<button class="pl-btn" onclick="event.stopPropagation();sendOnboardLink('${esc(l.name)}','${esc(l.email)}','${esc(l.category||'')}')" style="background:#0a1a2a;border-color:#1a3a5a;color:#2980b9;font-size:10px;text-align:center">📋 Onboard</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── SMS Replies / Email Replies ────────────────────────────────────────────────

function renderSmsReplies() {
  const tbody = document.getElementById('sms-replies-body');
  if (!tbody) return;
  const rows = [
    ...DATA.real_replies.map((m,i)=>({...m, kind:'real', ts:m.date_sent, preview:(m.body||'').slice(0,120), _idx:'r'+i})),
    ...DATA.opt_outs.map((m,i)=>   ({...m, kind:'stop', ts:m.date_sent, preview:(m.body||'').slice(0,120), _idx:'s'+i})),
    ...DATA.auto_replies.map((m,i)=>({...m, kind:'auto', ts:m.date_sent, preview:(m.body||'').slice(0,120), _idx:'a'+i})),
  ].sort((a,b)=>(b.ts||'').localeCompare(a.ts||''));

  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No SMS replies yet.</td></tr>'; return; }
  tbody.innerHTML = rows.map((m, i) => {
    const lead    = DATA.leads.find(l=>l.phone===m.from)||{};
    const phone   = m.from||'';
    const tyColor = m.kind==='real'?'#f39c12':m.kind==='stop'?'#e74c3c':'#555';
    const tyLabel = m.kind==='real'?'REPLY':m.kind==='stop'?'STOP':'AUTO';
    const bodyEsc = (m.preview||'').replace(/'/g,"\\'");
    const draftBtn = m.kind==='real'
      ? `<button class="btn btn-sm" style="background:#1a2a1a;color:#2ecc71;border:1px solid #2ecc71"
           onclick="event.stopPropagation();toggleDraft(${i},'${bodyEsc}','${phone}','sms','')">Draft Reply</button>`
      : '';
    return `
    <tr class="clickable" onclick="openPanel('${phone}')">
      <td style="white-space:nowrap;color:#888">${fmtTs(m.ts)}</td>
      <td>${tag(tyLabel,tyColor)}</td>
      <td><strong>${lead.name||m.name||phone}</strong><br><span style="color:#666;font-size:11px">${lead.category||''}</span></td>
      <td style="font-size:12px">${m.preview||''}</td>
      <td style="white-space:nowrap">
        <div style="display:flex;gap:6px">
          ${draftBtn}
          <button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${phone}')">View</button>
        </div>
      </td>
    </tr>
    <tr id="draft-${i}" style="display:none;background:#0d1a0d">
      <td colspan="5" style="padding:10px 16px">
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

function renderEmailReplies() {
  const tbody = document.getElementById('email-replies-body');
  if (!tbody) return;
  const rows  = [...(DATA.gmail_replies||[])].sort((a,b)=>(b.ts||'').localeCompare(a.ts||''));
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="3" class="empty">No email replies yet.</td></tr>'; return; }
  tbody.innerHTML = rows.map((r, idx) => {
    const lead  = DATA.leads.find(l=>l.email===r.from_email)||{};
    const email = r.from_email||'';
    const name  = lead.name||r.name||email;
    const cat   = lead.category||'';
    const sugg  = (r.suggested_reply||'').replace(/\\/g,'\\\\').replace(/`/g,'\\`').replace(/\$/g,'\\$');
    const bodyPreview = (r.body||r.snippet||'').slice(0,250).replace(/</g,'&lt;');
    const mailtoBody  = encodeURIComponent(r.suggested_reply||'');
    const mailtoSubj  = encodeURIComponent('Re: ' + (r.subject||''));
    const mailto = `mailto:${email}?subject=${mailtoSubj}&body=${mailtoBody}`;
    return `<tr>
      <td style="vertical-align:top;white-space:nowrap;color:#888;padding-top:14px">${fmtTs(r.ts)}</td>
      <td style="vertical-align:top;padding-top:14px">
        <div style="font-weight:700;color:#e0e0e0;font-size:14px;margin-bottom:2px">${name}</div>
        <div style="color:#555;font-size:11px;margin-bottom:6px">${cat} · ${email}</div>
        ${bodyPreview ? `<div style="background:#0a0a0e;border:1px solid #1c1c1c;border-radius:6px;padding:10px;font-size:12px;color:#666;margin-bottom:10px;font-style:italic;max-width:500px">"${bodyPreview}${(r.body||'').length>250?'…':''}"</div>` : ''}
        <div style="display:flex;gap:8px;flex-wrap:wrap;align-items:center">
          <a href="${mailto}" class="btn btn-sm" style="background:#1a0d2a;color:#9b59b6;border:1px solid #9b59b6;text-decoration:none">✉ Reply in Gmail</a>
          <button class="btn btn-sm btn-outline" onclick="
            const d=document.getElementById('draft-${idx}');
            d.style.display=d.style.display==='none'?'block':'none';
            this.textContent=d.style.display==='none'?'📝 View Draft':'Hide Draft'
          ">📝 View Draft</button>
          ${lead.phone ? `<button class="btn btn-sm btn-outline" style="font-size:10px" onclick="openPanel('${lead.phone}')">View Lead</button>` : ''}
        </div>
        <div id="draft-${idx}" style="display:none;margin-top:10px;max-width:520px">
          <textarea style="width:100%;background:#0d0d12;border:1px solid #2a2a3a;color:#ccc;padding:10px;border-radius:6px;font-size:12px;min-height:140px;resize:vertical;font-family:inherit" onclick="this.select()">${(r.suggested_reply||'').replace(/</g,'&lt;')}</textarea>
          <div style="font-size:10px;color:#333;margin-top:4px">Click text to select all · paste into Gmail</div>
        </div>
      </td>
      <td style="vertical-align:top;padding-top:14px;white-space:nowrap">
        <span style="background:#1a0d2a;color:#9b59b6;font-size:10px;font-weight:700;padding:2px 8px;border-radius:3px">REPLY</span>
      </td>
    </tr>`;
  }).join('');
}

// ── Follow-up Queue ────────────────────────────────────────────────────────────

function renderQueue() {
  const el      = document.getElementById('queue-list');
  if (!el) return;
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

function scoreBadge(score) {
  const cls = score >= 60 ? 'score-3' : score >= 35 ? 'score-2' : score >= 15 ? 'score-1' : 'score-0';
  return `<span class="score-badge ${cls}">${score}</span>`;
}

function renderAllLeads(leads) {
  const tbody      = document.getElementById('all-leads-body');
  const dupSet     = new Set(DATA.dup_phones);
  const overduePhones = new Set(DATA.overdue.map(o=>o.phone));
  const reengSet   = new Set(DATA.reengagement_phones||[]);
  if (!leads.length) { tbody.innerHTML = '<tr><td colspan="9" class="empty">No leads.</td></tr>'; return; }
  const sorted = [...leads].sort((a,b) => {
    if (a.clicked && !b.clicked) return -1;
    if (!a.clicked && b.clicked) return 1;
    return (b.score||0) - (a.score||0);
  });
  tbody.innerHTML = sorted.map(l => {
    const isOverdue = overduePhones.has(l.phone);
    const isDup     = dupSet.has(l.phone);
    const isReeng   = reengSet.has(l.phone);
    const hotTags = [];
    if (l.clicked) hotTags.push('<span style="background:#1a3a00;color:#7ed321;font-size:9px;font-weight:700;padding:1px 5px;border-radius:3px;margin-left:4px">CLICKED</span>');
    const dupTag    = isDup  ? ' <span style="color:#e74c3c;font-size:10px">DUP</span>' : '';
    const reengTag  = isReeng ? ' <span style="color:#9b59b6;font-size:10px">RE-ENG</span>' : '';
    const emailBtn  = l.email
      ? `<button class="act-btn email" onclick="event.stopPropagation();sendQuickEmail('${l.phone}','${esc(l.name)}','${esc(l.category)}','${esc(l.email)}')" title="Quick email">📧</button>`
      : '';
    return `<tr class="clickable${isOverdue?' overdue':''}" onclick="openPanel('${l.phone}')">
      <td><strong>${l.name}</strong>${hotTags.join('')}${dupTag}${reengTag}</td>
      <td style="color:#555;font-size:12px">${l.category}</td>
      <td>${scoreBadge(l.score||0)}</td>
      <td>${statusTag(l.status||'contacted')}</td>
      <td style="text-align:center;color:#666">${l.sms_sent}</td>
      <td style="text-align:center;color:#666">${l.email_sent}</td>
      <td>${l.replied?'<span style="color:#27ae60;font-weight:700">✓</span>':'<span style="color:#222">—</span>'}</td>
      <td style="font-size:12px">${daysAgo(l.last_contact)}</td>
      <td><div class="row-actions">
        <button class="act-btn sms" onclick="event.stopPropagation();sendQuickSms('${l.phone}','${esc(l.name)}','${esc(l.category)}')" title="Quick SMS">📱</button>
        ${emailBtn}
        <button class="act-btn" onclick="event.stopPropagation();openPanel('${l.phone}')">View →</button>
      </div></td>
    </tr>`;
  }).join('');
}

function filterLeads() {
  const q            = document.getElementById('lead-search').value.toLowerCase();
  const showClickers = document.getElementById('show-clickers').checked;
  const showDups     = document.getElementById('show-dups').checked;
  const showOverdue  = document.getElementById('show-overdue').checked;
  const showReeng    = document.getElementById('show-reengaged') && document.getElementById('show-reengaged').checked;
  const dupSet       = new Set(DATA.dup_phones);
  const overdueSet   = new Set(DATA.overdue.map(o=>o.phone));
  const reengSet     = new Set(DATA.reengagement_phones||[]);
  let leads = DATA.leads.filter(l=>
    (l.name||'').toLowerCase().includes(q) || (l.category||'').toLowerCase().includes(q)
  );
  const engagedPhones = new Set((DATA.clicker_leads||[]).map(l=>l.phone));
  if (showClickers) leads = leads.filter(l=>engagedPhones.has(l.phone));
  if (showDups)     leads = leads.filter(l=>dupSet.has(l.phone));
  if (showOverdue)  leads = leads.filter(l=>overdueSet.has(l.phone));
  if (showReeng)    leads = leads.filter(l=>reengSet.has(l.phone));
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
    { label: 'Sent',       val: sent,    sub: '100%',                color: '#888',    action: "showPage('email')" },
    { label: 'Opened',     val: opened,  sub: pct(opened,sent)+'%',  color: '#C9A96E', action: "showPage('analytics')" },
    { label: 'Clicked',    val: clicked, sub: pct(clicked,sent)+'%', color: '#d4a017', action: "showPage('analytics')" },
    { label: 'Replied',    val: replied, sub: pct(replied,sent)+'%', color: '#2980b9', action: "showPage('email-replies')" },
    { label: 'Won/Booked', val: won,     sub: pct(won,sent)+'%',     color: '#27ae60', action: "showPage('projects')" },
  ];

  document.getElementById('funnel-row').innerHTML =
    '<p class="section-title" style="margin-bottom:10px">Conversion Funnel <span style="color:#333;font-size:9px;font-weight:normal;letter-spacing:0">— click any stage</span></p>' +
    '<div style="display:flex;border:1px solid #1c1c1c;border-radius:8px;overflow:hidden;background:#111">' +
    steps.map((s, i) =>
      `<div onclick="${s.action}" style="flex:1;padding:16px 10px;border-right:${i<steps.length-1?'1px solid #1c1c1c':'none'};text-align:center;cursor:pointer;transition:background .15s" onmouseover="this.style.background='#161616'" onmouseout="this.style.background=''">
        <div style="font-size:24px;font-weight:700;color:${s.color};line-height:1">${s.val.toLocaleString()}</div>
        <div style="color:#666;font-size:10px;text-transform:uppercase;letter-spacing:.5px;margin:5px 0 3px">${s.label}</div>
        <div style="font-size:12px;color:${s.color};opacity:.7">${s.sub}</div>
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

// ── Subject Line Performance ──────────────────────────────────────────────────

function renderSubjectStats() {
  const el = document.getElementById('subjects-content');
  if (!el) return;
  const data = DATA.subject_stats || [];
  if (!data.length) {
    el.innerHTML = '<p class="empty">Not enough data yet — need at least 3 sends per subject line.</p>';
    return;
  }
  const max = data[0].click_rate || 1;
  const rows = data.map((s, i) => {
    const bar   = Math.round(s.click_rate / max * 100);
    const medal = i===0 ? '🥇' : i===1 ? '🥈' : i===2 ? '🥉' : `<span style="color:#444">${i+1}.</span>`;
    const color = s.click_rate >= 3 ? '#7ed321' : s.click_rate >= 1 ? '#f39c12' : '#555';
    return `<tr>
      <td style="width:28px;font-size:12px">${medal}</td>
      <td style="max-width:420px">
        <div style="font-size:13px;color:#ddd;margin-bottom:5px">${s.subject.replace(/</g,'&lt;')}</div>
        <div style="background:#111;border-radius:3px;height:4px;width:100%">
          <div style="background:${color};height:4px;border-radius:3px;width:${bar}%;transition:width .4s"></div>
        </div>
      </td>
      <td style="text-align:center;color:#555;font-size:12px">${s.sent}</td>
      <td style="text-align:center;color:#f39c12;font-size:12px">${s.opens} <span style="color:#333;font-size:10px">(${s.open_rate}%)</span></td>
      <td style="text-align:center;color:${color};font-weight:700;font-size:13px">${s.clicks} <span style="color:#333;font-size:10px">(${s.click_rate}%)</span></td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <p class="section-title" style="margin-bottom:4px">Subject Line Performance</p>
    <p style="font-size:12px;color:#444;margin-bottom:16px">Ranked by click rate · opens/clicks from Activity Feed (7-day window)</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th></th><th>Subject Line</th><th style="text-align:center">Sent</th><th style="text-align:center">Opens</th><th style="text-align:center">Clicks</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
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

// ── Category Performance ───────────────────────────────────────────────────────

function renderCategoryStats() {
  const el   = document.getElementById('categories-content');
  if (!el) return;
  const data = DATA.category_stats || [];
  if (!data.length) { el.innerHTML = '<p class="empty">Not enough data yet — need 5+ sends per category.</p>'; return; }
  const maxRate = data[0].click_rate || 1;
  const rows = data.map((c,i) => {
    const bar   = Math.round(c.click_rate / maxRate * 100);
    const col   = c.click_rate >= 3 ? '#7ed321' : c.click_rate >= 1 ? '#f39c12' : '#e74c3c';
    const label = c.category.replace(/\b\w/g, l => l.toUpperCase());
    return `<tr>
      <td style="width:20px;color:#444;font-size:11px">${i+1}</td>
      <td style="min-width:160px">
        <div style="font-size:13px;color:#ddd;margin-bottom:4px">${label}</div>
        <div style="background:#111;border-radius:3px;height:4px">
          <div style="background:${col};height:4px;border-radius:3px;width:${bar}%"></div>
        </div>
      </td>
      <td style="text-align:center;color:#555;font-size:12px">${c.sent}</td>
      <td style="text-align:center;color:#f39c12;font-size:12px">${c.opens} <span style="color:#333;font-size:10px">(${c.open_rate}%)</span></td>
      <td style="text-align:center;color:${col};font-weight:700">${c.clicks} <span style="color:#333;font-size:10px">(${c.click_rate}%)</span></td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <p class="section-title" style="margin-bottom:4px">Category Performance</p>
    <p style="font-size:12px;color:#444;margin-bottom:16px">Which business types respond most — focus prospecting here</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th></th><th>Category</th><th style="text-align:center">Sent</th><th style="text-align:center">Opens</th><th style="text-align:center">Clicks</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

// ── Best Time to Send ──────────────────────────────────────────────────────────

function renderTimingStats() {
  const el = document.getElementById('timing-content');
  if (!el) return;
  const ts    = DATA.timing_stats || {};
  const days  = ts.days  || [];
  const hours = (ts.hours || []).filter(h => h.sent > 0);
  if (!days.length) { el.innerHTML = '<p class="empty">Not enough send data yet.</p>'; return; }
  const maxDay  = Math.max(...days.map(d => d.rate),  0.1);
  const maxHour = Math.max(...hours.map(h => h.rate), 0.1);
  const bestDay  = [...days].sort((a,b) => b.rate - a.rate)[0];
  const bestHour = hours.length ? [...hours].sort((a,b) => b.rate - a.rate)[0] : null;
  const dayBars = days.map(d => {
    const h   = Math.max(Math.round(d.rate / maxDay * 80), d.sent > 0 ? 2 : 0);
    const col = d.rate >= bestDay.rate * 0.8 ? '#C9A96E' : '#2a2a2a';
    return `<div style="display:flex;flex-direction:column;align-items:center;gap:4px;flex:1">
      <div style="font-size:10px;color:#555">${d.rate}%</div>
      <div style="background:${col};width:100%;height:${h}px;border-radius:3px 3px 0 0;min-height:2px"></div>
      <div style="font-size:11px;color:#666">${d.label}</div>
      <div style="font-size:10px;color:#333">${d.sent}</div>
    </div>`;
  }).join('');
  const hourBars = hours.map(h => {
    const ht  = Math.max(Math.round(h.rate / maxHour * 60), 2);
    const col = bestHour && h.rate >= bestHour.rate * 0.7 ? '#7ed321' : '#1e1e1e';
    return `<div style="display:flex;flex-direction:column;align-items:center;gap:3px;min-width:36px">
      <div style="background:${col};width:28px;height:${ht}px;border-radius:2px 2px 0 0;min-height:2px"></div>
      <div style="font-size:9px;color:#444">${h.label}</div>
    </div>`;
  }).join('');
  el.innerHTML = `
    <p class="section-title" style="margin-bottom:4px">Best Time to Send</p>
    <p style="font-size:12px;color:#444;margin-bottom:20px">
      Best day: <span style="color:#C9A96E;font-weight:700">${bestDay.label}</span> (${bestDay.rate}% click rate)
      ${bestHour ? ` · Best hour: <span style="color:#7ed321;font-weight:700">${bestHour.label}</span>` : ''}
    </p>
    <div style="margin-bottom:28px">
      <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px">By Day of Week</div>
      <div style="display:flex;gap:6px;align-items:flex-end;height:110px;padding-bottom:4px">${dayBars}</div>
    </div>
    <div>
      <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.6px;margin-bottom:12px">By Hour Sent</div>
      <div style="display:flex;gap:4px;align-items:flex-end;height:80px;overflow-x:auto;padding-bottom:4px">${hourBars}</div>
    </div>`;
}

// ── Email Template Editor ──────────────────────────────────────────────────────

function renderTemplateEditor() {
  const el = document.getElementById('templates-content');
  if (!el) return;
  const t = DATA.email_template || {};
  el.innerHTML = `
    <p class="section-title" style="margin-bottom:4px">Email Template Editor</p>
    <p style="font-size:12px;color:#444;margin-bottom:20px">Changes save to email_template.json · use {name} for business name</p>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:20px">
      <div>
        <div style="font-size:11px;color:#C9A96E;text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px">Initial Outreach</div>
        <label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Subject</label>
        <input id="tpl-subject" value="${(t.subject||'').replace(/"/g,'&quot;')}"
          style="width:100%;background:#0d0d12;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:12px;margin-bottom:10px;font-family:inherit;box-sizing:border-box">
        <label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Body</label>
        <textarea id="tpl-body" rows="10"
          style="width:100%;background:#0d0d12;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:12px;resize:vertical;font-family:inherit;box-sizing:border-box">${t.body||''}</textarea>
      </div>
      <div>
        <div style="font-size:11px;color:#f39c12;text-transform:uppercase;letter-spacing:.8px;margin-bottom:8px">Follow-up (Day 3)</div>
        <label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Subject</label>
        <input id="tpl-fu-subject" value="${(t.followup_subject||'').replace(/"/g,'&quot;')}"
          style="width:100%;background:#0d0d12;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:12px;margin-bottom:10px;font-family:inherit;box-sizing:border-box">
        <label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Body</label>
        <textarea id="tpl-fu-body" rows="10"
          style="width:100%;background:#0d0d12;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:12px;resize:vertical;font-family:inherit;box-sizing:border-box">${t.followup_body||''}</textarea>
      </div>
    </div>
    <div style="margin-top:16px;display:flex;gap:10px;align-items:center">
      <button class="btn btn-green" onclick="saveTemplate()">💾 Save Templates</button>
      <span id="tpl-saved" style="font-size:12px;color:#7ed321;display:none">✓ Saved</span>
    </div>`;
}

function saveTemplate() {
  const t = {
    subject:          document.getElementById('tpl-subject').value,
    body:             document.getElementById('tpl-body').value,
    followup_subject: document.getElementById('tpl-fu-subject').value,
    followup_body:    document.getElementById('tpl-fu-body').value,
  };
  fetch('/action/save-template', {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(t)
  }).then(r=>r.json()).then(() => {
    DATA.email_template = t;
    const s = document.getElementById('tpl-saved');
    if (s) { s.style.display='inline'; setTimeout(()=>s.style.display='none', 2000); }
  });
}

// ── Stripe Payments ────────────────────────────────────────────────────────────

function renderStripePayments() {
  const el = document.getElementById('stripe-payments-section');
  if (!el) return;
  const payments = DATA.stripe_payments || [];
  const prod = payments.filter(p => p.environment !== 'test');
  if (!prod.length) {
    el.innerHTML = '<div style="background:#0d0d10;border:1px solid #1a1a24;border-radius:8px;padding:14px 18px">' +
      '<div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.8px;margin-bottom:6px">💳 Stripe Payments</div>' +
      '<p style="font-size:12px;color:#333;margin:0">No payments yet — payments from webbymaya.com appear here automatically when clients pay.</p></div>';
    return;
  }
  const total = prod.reduce((s,p) => s+p.amount, 0);
  const rows  = prod.slice(0,10).map(p =>
    '<div style="display:flex;justify-content:space-between;align-items:center;padding:8px 0;border-bottom:1px solid #111">' +
      '<div><div style="font-size:13px;color:#ddd">' + (p.customer||p.description||'Payment') + '</div>' +
      '<div style="font-size:11px;color:#444">' + p.date + ' \xb7 ' + (p.kind||'payment') + '</div></div>' +
      '<div style="font-size:14px;font-weight:700;color:#7ed321">$' + p.amount.toLocaleString() + '</div></div>'
  ).join('');
  el.innerHTML = '<div style="background:#0d0d10;border:1px solid #1a1a24;border-radius:8px;padding:14px 18px">' +
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">' +
      '<div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.8px">💳 Stripe Payments</div>' +
      '<div style="font-size:14px;font-weight:700;color:#7ed321">$' + total.toLocaleString() + ' total</div></div>' +
    rows + (prod.length>10?'<div style="font-size:11px;color:#444;margin-top:8px">'+(prod.length-10)+' more</div>':'') + '</div>';
}

// ── AI Copy Writer ──────────────────────────────────────────────────────────────

function renderCopyWriter() {
  const el = document.getElementById('copywriter-content');
  if (!el) return;
  el.innerHTML =
    '<p class="section-title" style="margin-bottom:4px">AI Homepage Copy Writer</p>' +
    '<p style="font-size:12px;color:#444;margin-bottom:20px">Enter a business and get a full homepage draft in seconds \xb7 Powered by Claude Haiku</p>' +
    '<div style="display:grid;grid-template-columns:320px 1fr;gap:24px;align-items:start">' +
      '<div style="background:#0d0d12;border:1px solid #1e1e2a;border-radius:10px;padding:18px">' +
        '<label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Business Name</label>' +
        '<input id="cw-name" placeholder="e.g. Crimson Hair Studio" style="width:100%;background:#111;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:13px;margin-bottom:12px;box-sizing:border-box;font-family:inherit">' +
        '<label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Category</label>' +
        '<input id="cw-cat" placeholder="e.g. hair salon" style="width:100%;background:#111;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:13px;margin-bottom:12px;box-sizing:border-box;font-family:inherit">' +
        '<div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;margin-bottom:12px">' +
          '<div><label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Yelp Rating</label><input id="cw-rating" placeholder="4.5" type="number" step="0.1" min="1" max="5" style="width:100%;background:#111;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:13px;box-sizing:border-box"></div>' +
          '<div><label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Reviews</label><input id="cw-reviews" placeholder="127" type="number" style="width:100%;background:#111;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:13px;box-sizing:border-box"></div>' +
        '</div>' +
        '<label style="font-size:11px;color:#555;display:block;margin-bottom:4px">Extra Notes (optional)</label>' +
        '<textarea id="cw-notes" placeholder="e.g. family-owned since 1985, South Philly" style="width:100%;background:#111;border:1px solid #2a2a3a;color:#ccc;padding:9px;border-radius:6px;font-size:12px;resize:vertical;min-height:60px;margin-bottom:14px;box-sizing:border-box;font-family:inherit"></textarea>' +
        '<button id="cw-btn" class="btn btn-green" style="width:100%" onclick="runCopyWriter()">Generate Copy</button>' +
      '</div>' +
      '<div id="cw-output" style="background:#0d0d12;border:1px solid #1e1e2a;border-radius:10px;padding:20px;min-height:280px">' +
        '<p style="color:#333;font-size:13px;text-align:center;margin-top:80px">Fill in the form and click Generate</p>' +
      '</div></div>';
}

function runCopyWriter() {
  const name=document.getElementById('cw-name').value.trim();
  const cat=document.getElementById('cw-cat').value.trim();
  if(!name||!cat){alert('Enter business name and category');return;}
  const btn=document.getElementById('cw-btn');
  const out=document.getElementById('cw-output');
  btn.textContent='Generating...';btn.disabled=true;
  out.innerHTML='<p style="color:#555;text-align:center;margin-top:80px">Asking Claude to write your copy...</p>';
  fetch('/action/generate-copy',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name,category:cat,
      rating:document.getElementById('cw-rating').value||null,
      reviews:document.getElementById('cw-reviews').value||null,
      description:document.getElementById('cw-notes').value})
  }).then(r=>r.json()).then(d=>{
    btn.textContent='Generate Copy';btn.disabled=false;
    if(d.error==='no_key'){
      out.innerHTML='<div style="background:#1a1a00;border:1px solid #3a3a00;border-radius:8px;padding:16px">'+
        '<div style="color:#f39c12;font-weight:700;margin-bottom:8px">Anthropic API key needed</div>'+
        '<div style="font-size:12px;color:#888">Run in terminal, then restart dashboard:</div>'+
        '<code style="display:block;background:#111;padding:10px;border-radius:6px;margin-top:8px;font-size:12px;color:#7ed321">echo \'export ANTHROPIC_API_KEY="sk-ant-..."\' &gt;&gt; ~/.zshrc &amp;&amp; source ~/.zshrc</code>'+
        '<div style="font-size:11px;color:#555;margin-top:8px">Get a key at console.anthropic.com &rarr; API Keys</div></div>';
      return;
    }
    if(d.error){out.innerHTML='<p style="color:#e74c3c">Error: '+d.error+'</p>';return;}
    const field=(label,val,id)=>
      '<div style="margin-bottom:14px">'+
        '<div style="font-size:10px;color:#C9A96E;text-transform:uppercase;letter-spacing:.8px;margin-bottom:5px">'+label+'</div>'+
        '<div style="background:#111;border:1px solid #1e1e28;border-radius:6px;padding:10px;position:relative">'+
          '<div id="'+id+'" style="font-size:13px;color:#ddd;line-height:1.5" contenteditable="true">'+(val||'')+'</div>'+
          '<button onclick="navigator.clipboard.writeText(document.getElementById(\''+id+'\').innerText)" '+
            'style="position:absolute;top:5px;right:6px;background:none;border:1px solid #2a2a3a;color:#444;font-size:10px;padding:2px 7px;border-radius:4px;cursor:pointer">copy</button>'+
        '</div></div>';
    out.innerHTML=
      '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">'+
        '<div style="font-size:13px;font-weight:700;color:#C9A96E">'+name+'</div>'+
        '<button class="btn btn-sm btn-outline" onclick="copyAllCopy()">Copy All</button></div>'+
      field('H1 Headline',d.headline,'cw-out-h1')+
      field('Tagline',d.tagline,'cw-out-tag')+
      field('About Paragraph',d.about,'cw-out-about')+
      field('CTA Button',d.cta,'cw-out-cta')+
      field('Services Intro',d.services_intro,'cw-out-svc')+
      '<div id="cw-copy-ok" style="display:none;color:#7ed321;font-size:12px;text-align:right;margin-top:4px">Copied!</div>';
  }).catch(e=>{btn.textContent='Generate Copy';btn.disabled=false;out.innerHTML='<p style="color:#e74c3c">Failed: '+e.message+'</p>';});
}

function copyAllCopy(){
  const ids=['cw-out-h1','cw-out-tag','cw-out-about','cw-out-cta','cw-out-svc'];
  const labels=['HEADLINE','TAGLINE','ABOUT','CTA','SERVICES INTRO'];
  const text=ids.map((id,i)=>{const el=document.getElementById(id);return el?('['+labels[i]+']\n'+el.innerText):'';}).filter(Boolean).join('\n\n');
  navigator.clipboard.writeText(text).catch(()=>{});
  const c=document.getElementById('cw-copy-ok');
  if(c){c.style.display='block';setTimeout(()=>c.style.display='none',2000);}
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

  const _sched = DATA.send_schedule || {};
  const _schedSlots = (_sched.schedule || []).map(s =>
    `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #111">
      <span style="color:#C9A96E;font-weight:700;font-size:13px">${s.time}</span>
      <span style="color:#ddd;font-size:12px">up to ${s.limit} emails</span>
      <span style="font-size:11px;color:#444">${s.note}</span>
    </div>`
  ).join('');
  const _schedHtml = _schedSlots ? `
    <div style="background:#0d0d10;border:1px solid #1a1a24;border-radius:8px;padding:14px 16px;margin-bottom:20px">
      <div style="font-size:11px;color:#555;text-transform:uppercase;letter-spacing:.8px;margin-bottom:10px">⏰ Send Schedule (${_sched.daily_max||1500}/day max)</div>
      ${_schedSlots}
    </div>` : '';

  document.getElementById('analytics-rates').innerHTML = _schedHtml + `
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
      <div style="background:#111;border:1px solid #222;border-radius:4px;padding:10px 14px;font-size:11px;color:#666;margin-bottom:16px">
        Local log breakdown: ${(s.email_by_type||{}).outreach||0} cold outreach
        · ${(s.email_by_type||{}).followup||0} follow-ups
        · ${(s.email_by_type||{}).clicker||0} clicker follow-ups
        · ${(s.email_by_type||{}).reengagement||0} re-engagement
        · ${(s.email_by_type||{}).seasonal||0} seasonal
        = <b style="color:#C9A96E">${s.total_email.toLocaleString()} total</b>
        ${sg.requests > 0 ? '(SendGrid API reports '+(sg.requests||0).toLocaleString()+' via SG only)' : ''}
      </div>

      <p style="color:#9b59b6;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">
        ── Re-engagement Campaign ──
      </p>
      ${(() => {
        const reengPhones = new Set(DATA.reengagement_phones||[]);
        const ct = reengPhones.size;
        if (!ct) return '<p style="color:#333;font-size:12px;margin-bottom:16px">No re-engagement emails sent yet. Runs Tue/Wed/Thu targeting leads > 30 days silent.</p>';
        const reengLeads = DATA.leads.filter(l=>reengPhones.has(l.phone));
        const responded  = reengLeads.filter(l=>l.replied||l.clicked);
        const respRate   = ct ? Math.round(responded.length/ct*100) : 0;
        const topRows    = reengLeads.filter(l=>l.replied||l.clicked).slice(0,8).map(l=>
          `<tr class="clickable" onclick="openPanel('${l.phone}')">
            <td><strong>${l.name}</strong></td>
            <td style="color:#666">${l.category}</td>
            <td>${l.clicked?'<span style="color:#7ed321">Clicked</span>':''}${l.replied?' <span style="color:#f39c12">Replied</span>':''}</td>
            <td style="font-size:11px;color:#888">${daysAgo(l.last_contact).replace(/<[^>]+>/g,'')}</td>
          </tr>`
        ).join('');
        return `<div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:12px">
          <div class="card" style="min-width:110px">
            <div class="card-num" style="color:#9b59b6">${ct}</div>
            <div class="card-label">Re-engaged Leads</div>
          </div>
          <div class="card" style="min-width:110px">
            <div class="card-num green">${responded.length}</div>
            <div class="card-label">Responded</div>
            <div style="color:#555;font-size:10px;margin-top:4px">${respRate}% response rate</div>
          </div>
        </div>
        ${topRows ? `<div class="tbl-wrap" style="margin-bottom:16px"><table>
          <thead><tr><th>Name</th><th>Category</th><th>Response</th><th>Last Contact</th></tr></thead>
          <tbody>${topRows}</tbody>
        </table></div>` : '<p style="color:#555;font-size:12px;margin-bottom:16px">None have responded yet. Re-engagement runs Tue–Thu.</p>'}`;
      })()}

      <p style="color:#7ed321;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px">
        ── Who Clicked Your Link (Activity Feed) ──
      </p>
      ${(() => {
        const cd = DATA.clicker_data || {};
        const entries = Object.entries(cd).sort((a,b) => b[1].clicks - a[1].clicks);
        if (!entries.length) return '<p style="color:#333;font-size:12px;margin-bottom:16px">No clicker activity in SendGrid\'s retention window. The 472 all-time aggregate is from the stats API; individual identities are only stored for your plan\'s activity window.</p>';
        const real = entries.filter(([,v])=>!v.likely_bot);
        const bots = entries.filter(([,v])=>v.likely_bot);
        const rows = (arr, label) => arr.length ? arr.map(([email, v]) => {
          const biz = (v.businesses||[]).join(', ') || '—';
          const botTag = v.likely_bot ? ' <span style="color:#e74c3c;font-size:10px">BOT</span>' : '';
          return `<tr class="clickable" onclick="openPanel('${email}')">
            <td style="color:#a8e060">${email}${botTag}</td>
            <td style="color:#888;font-size:11px">${biz}</td>
            <td style="text-align:center;color:#7ed321">${v.clicks}</td>
            <td style="text-align:center;color:#C9A96E">${v.opens}</td>
          </tr>`;
        }).join('') : '';
        return `<div class="tbl-wrap" style="margin-bottom:16px">
          <table>
            <thead><tr><th>Email</th><th>Business (from subject)</th><th style="text-align:center">Clicks</th><th style="text-align:center">Opens</th></tr></thead>
            <tbody>
              ${real.length ? `<tr><td colspan="4" style="color:#555;font-size:10px;padding:4px 8px">── ${real.length} real leads ──</td></tr>${rows(real)}` : ''}
              ${bots.length ? `<tr><td colspan="4" style="color:#333;font-size:10px;padding:4px 8px">── ${bots.length} likely bots / scanners ──</td></tr>${rows(bots)}` : ''}
            </tbody>
          </table>
          <p style="color:#444;font-size:10px;margin-top:8px">
            Showing ${entries.length} identifiable clickers from SendGrid activity window.
            All-time aggregate = ${sg.clicks||0} clicks total (includes older history not stored in feed).
          </p>
        </div>`;
      })()}
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
      const openPct   = d.sent ? Math.round(d.opens  / d.sent * 100) : 0;
      const detail    = (DATA.daily_send_detail||{})[d.date] || [];
      const clickers  = detail.filter(r=>r.clicked&&!r.is_bot).length;
      const clickTag  = clickers > 0
        ? ` <button class="btn btn-sm btn-green" style="padding:1px 7px;font-size:10px"
              onclick="event.stopPropagation();showSendDetail('${d.date}')">🔥 See ${clickers}</button>`
        : '';
      return `<tr class="clickable" onclick="showSendDetail('${d.date}')">
        <td style="color:#C9A96E;font-weight:600">${d.date}</td>
        <td>${d.sent}</td>
        <td>${d.opens} <span style="color:#555;font-size:10px">(${openPct}%)</span></td>
        <td>${d.clicks}${clickTag}</td>
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

  // Weekly digest button at the bottom of analytics
  const digestWrap = document.createElement('div');
  digestWrap.style.cssText = 'margin-top:24px;padding-top:18px;border-top:1px solid #1c1c1c';
  digestWrap.innerHTML = `
    <div style="font-size:11px;color:#555;margin-bottom:8px;text-transform:uppercase;letter-spacing:.6px">Weekly Report</div>
    <button class="btn btn-sm btn-outline" onclick="sendDigest()">📧 Send Weekly Digest Now</button>
    <div style="font-size:11px;color:#333;margin-top:6px">Sends summary to mayasierra1999@gmail.com · also auto-sends every Sunday</div>`;
  const analyticsEl = document.getElementById('page-analytics');
  if (analyticsEl) analyticsEl.appendChild(digestWrap);
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
  document.getElementById('panel-name').textContent = lead.name;
  const score  = lead.score || 0;
  const sClass = score >= 60 ? 'score-3' : score >= 35 ? 'score-2' : score >= 15 ? 'score-1' : 'score-0';
  const stars  = lead.rating ? parseFloat(lead.rating) : 0;
  const starHtml = lead.rating
    ? `<span style="color:#C9A96E;letter-spacing:1px">${'★'.repeat(Math.round(stars))}${'☆'.repeat(5-Math.round(stars))}</span> <span style="color:#888;font-size:11px">${lead.rating} (${lead.reviews||'?'})</span>`
    : '';
  document.getElementById('panel-category').innerHTML =
    `<span style="text-transform:capitalize">${lead.category}</span>
     <span class="score-badge ${sClass}" style="margin-left:8px" title="Lead score (0-100)">Score: ${score}</span>
     ${starHtml ? `<br><span style="font-size:12px;margin-top:3px;display:inline-block">${starHtml}</span>` : ''}`;

  const touchDotColors = {sms_out:'#3498db',email_out:'#C9A96E',sms_in:'#2ecc71',email_in:'#9b59b6'};
  const touchLabels    = {sms_out:'SMS Sent',email_out:'Email Sent',sms_in:'SMS Reply',email_in:'Email Reply'};

  const touchHtml = (lead.touches||[]).map(t => {
    const typeLabel = t.log_type === 'followup' ? 'Follow-up Email'
                    : t.log_type === 'clicker'  ? 'Clicker Email'
                    : t.log_type === 'seasonal'  ? 'Seasonal Email'
                    : touchLabels[t.type] || t.type;
    const subjectLine = t.subject ? `<div style="font-size:12px;color:#888;margin-top:2px;font-style:italic">"${t.subject}"</div>` : '';
    const viewBtn = (t.type === 'email_out' && t.subject)
      ? `<button class="btn btn-sm btn-outline" style="margin-top:5px;font-size:10px;padding:3px 8px"
           onclick="previewEmail('${esc(lead.name)}','${esc(lead.category)}','${esc(lead.email||'')}','${esc(t.subject)}')">
           View Email ↗</button>`
      : '';
    const smsMeta = t.type.includes('sms') ? `<div style="font-size:12px;color:#888;margin-top:2px">${t.note||''}</div>` : '';
    return `<div class="touch-item">
      <div class="touch-dot" style="background:${touchDotColors[t.type]||'#555'}"></div>
      <div style="flex:1">
        <div style="display:flex;align-items:center;gap:8px">
          <span style="font-size:13px;color:#ccc">${typeLabel}</span>
          <span style="font-size:10px;color:#444">${fmtTs(t.ts)}</span>
        </div>
        ${subjectLine}
        ${smsMeta}
        ${viewBtn}
      </div>
    </div>`;
  }).join('') || '<p style="color:#555;font-size:13px">No touchpoints yet.</p>';

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
        <span class="info-val"><a href="tel:${lead.phone}" style="font-weight:600">${lead.phone}</a></span>
        <span class="info-label">Email</span>
        <span class="info-val">${lead.email ? `<a href="mailto:${lead.email}" style="color:#6aafe6">${lead.email}</a>` : '<span style="color:#333">—</span>'}</span>
        <span class="info-label">Address</span>
        <span class="info-val" style="color:#aaa">${lead.address||'—'}</span>
        <span class="info-label">Status</span>
        <span class="info-val">${statusTag(lead.status||'contacted')}</span>
      </div>
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
      <div class="panel-section-title">Mockup & Email Preview</div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button class="btn btn-sm" style="background:#1a1a2e;color:#7eb8f7;border:1px solid #3a5a8a"
          onclick="generateMockupPanel('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.address||'')}')">
          🖥 Generate / View Mockup</button>
        <button class="btn btn-sm btn-outline"
          onclick="previewEmailTemplate('${esc(lead.name)}','${esc(lead.category)}')">
          📧 Preview Email</button>
      </div>
      <div id="panel-mockup-preview" style="margin-top:10px"></div>
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

  // Quick-links bar (fast actions below header)
  let qlEmail = '';
  if (lead.email) {
    const cd = lead.click_data || {};
    qlEmail = lead.clicked
      ? `<button class="pl-btn" style="background:#1a3000;color:#7ed321;border-color:#2a5000" title="Clicked ${cd.clicks||'?'}x · opened ${cd.opens||'?'}x"
           onclick="sendClickerEmail('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.email)}')">🔥 Mockup Offer</button>`
      : `<button class="pl-btn blue"
           onclick="sendFollowupEmail('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.email)}')">📧 Follow-up Email</button>`;
  }
  const qlSms = `<button class="pl-btn green"
    onclick="sendQuickSms('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}')">📱 Quick SMS</button>`;
  const qlMaps = lead.maps_url||lead.address
    ? `<a class="pl-btn" href="${lead.maps_url||'https://maps.google.com?q='+encodeURIComponent(lead.address||'')}" target="_blank">🗺 Maps</a>`
    : '';

  // Quick-links bar goes into a dedicated slot between header and body
  let qlBar = document.getElementById('panel-quicklinks');
  if (!qlBar) {
    qlBar = document.createElement('div');
    qlBar.id = 'panel-quicklinks';
    qlBar.className = 'panel-links';
    document.getElementById('lead-panel').insertBefore(qlBar, document.getElementById('panel-body'));
  }
  qlBar.innerHTML = qlSms + qlEmail + qlMaps +
    `<button class="pl-btn" onclick="previewEmailTemplate('${esc(lead.name)}','${esc(lead.category)}')">👁 Preview Email</button>`;

  document.getElementById('panel-actions').innerHTML = `
    <button class="btn btn-sm btn-green" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','booked')">Booked ✓</button>
    <button class="btn btn-sm btn-green" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','won')">Won 🏆</button>
    <button class="btn btn-sm btn-outline" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','warm')">Warm</button>
    <button class="btn btn-sm btn-danger" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','not_interested')">Not Interested</button>
    <button class="btn btn-sm" style="background:#1a1500;color:#C9A96E;border:1px solid #2a2500"
      onclick="generateProposal('${lead.phone}','${esc(lead.name)}','${esc(lead.category)}','${esc(lead.address||'')}')">📄 Proposal PDF</button>
    ${lead.email ? `<button class="btn btn-sm" style="background:#1a1000;color:#C9A96E;border:1px solid #3a2800"
      onclick="sendProposal('${esc(lead.name)}','${esc(lead.email)}','${esc(lead.category||'')}')">📧 Send Proposal</button>` : ''}
    <a href="tel:${lead.phone}" class="btn btn-sm btn-outline">📞 Call</a>`;

  document.getElementById('panel-overlay').classList.add('open');
  document.getElementById('lead-panel').classList.add('open');
}

function closePanel() {
  document.getElementById('panel-overlay').classList.remove('open');
  document.getElementById('lead-panel').classList.remove('open');
  currentPhone = null;
}

// ── Quick Popover ──────────────────────────────────────────────────────────────

let _qpTarget = null;

function sendQuickSms(phone, name, category) {
  _qpTarget = {phone, name, category, type:'sms'};
  const defaultMsg = `Hi ${name}! This is Maya from WebByMaya. I'd love to help get ${name} online — fill out my quick form: https://webbymaya.com/book`;
  const pop = document.getElementById('quick-popover');
  pop.innerHTML = `
    <div class="qp-title">📱 Quick SMS</div>
    <div class="qp-name">${name}</div>
    <textarea class="qp-input" id="qp-msg" rows="3">${defaultMsg}</textarea>
    <div style="font-size:10px;color:#444;margin-top:4px" id="qp-char">${defaultMsg.length} chars</div>
    <div class="qp-actions">
      <button class="btn btn-sm btn-outline" onclick="closePopover()">Cancel</button>
      <button class="btn btn-sm btn-green" onclick="submitQuickSms()">Send SMS</button>
    </div>`;
  pop.classList.add('open');
  const ta = document.getElementById('qp-msg');
  ta.addEventListener('input', () => { document.getElementById('qp-char').textContent = ta.value.length + ' chars'; });
  setTimeout(()=>ta.focus(), 50);
}

function sendQuickEmail(phone, name, category, email) {
  _qpTarget = {phone, name, category, email, type:'email'};
  const pop = document.getElementById('quick-popover');
  const clickData = (DATA.leads||[]).find(l=>l.phone===phone)?.click_data||{};
  const isHot = (DATA.leads||[]).find(l=>l.phone===phone)?.clicked;
  pop.innerHTML = `
    <div class="qp-title">📧 Quick Email</div>
    <div class="qp-name">${name}</div>
    <div style="font-size:11px;color:#555;margin-bottom:12px">${email}</div>
    <div class="qp-actions">
      <button class="btn btn-sm btn-outline" onclick="closePopover()">Cancel</button>
      <button class="btn btn-sm btn-green" onclick="submitQuickEmail()">Send Follow-up</button>
      ${isHot ? `<button class="btn btn-sm" style="background:#4a8a00;color:#fff" onclick="submitQuickClickerEmail()">🔥 Send Mockup Offer</button>` : ''}
    </div>`;
  pop.classList.add('open');
}

function closePopover() {
  document.getElementById('quick-popover').classList.remove('open');
  _qpTarget = null;
}

document.addEventListener('keydown', e => { if (e.key==='Escape') closePopover(); });

async function submitQuickSms() {
  if (!_qpTarget) return;
  const body = document.getElementById('qp-msg')?.value?.trim();
  if (!body) return;
  const btn = event.target; btn.disabled=true; btn.textContent='Sending…';
  const r = await fetch('/action/send-custom-sms',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone:_qpTarget.phone,name:_qpTarget.name,body})});
  const d = await r.json();
  closePopover();
  if (d.ok) toast('SMS sent to '+_qpTarget.name+'!');
  else toast('Error: '+(d.error||'unknown'),true);
}

async function submitQuickEmail() {
  if (!_qpTarget||!_qpTarget.email) return;
  const btn = event.target; btn.disabled=true; btn.textContent='Sending…';
  const r = await fetch('/action/send-followup-email',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone:_qpTarget.phone,name:_qpTarget.name,category:_qpTarget.category,email:_qpTarget.email})});
  const d = await r.json();
  closePopover();
  if (d.ok) toast('Follow-up email sent to '+_qpTarget.name+'!');
  else toast('Error: '+(d.error||'unknown'),true);
}

async function submitQuickClickerEmail() {
  if (!_qpTarget||!_qpTarget.email) return;
  const btn = event.target; btn.disabled=true; btn.textContent='Sending…';
  const r = await fetch('/action/send-clicker-email',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone:_qpTarget.phone,name:_qpTarget.name,category:_qpTarget.category,email:_qpTarget.email})});
  const d = await r.json();
  closePopover();
  if (d.ok) toast('Mockup offer sent to '+_qpTarget.name+'!');
  else toast('Error: '+(d.error||'unknown'),true);
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

function sendOnboardLink(name, email, category) {
  if (!email) { alert('No email address for this lead'); return; }
  if (!confirm('Send onboarding form link to ' + name + ' at ' + email + '?')) return;
  const btn = event.currentTarget || event.target;
  btn.textContent = 'Sending…'; btn.disabled = true;
  fetch('/action/send-onboard-link', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, email, category})
  }).then(r=>r.json()).then(d => {
    if (d.ok) {
      btn.textContent = '✓ Sent';
      btn.style.background='#0a1a2a'; btn.style.color='#2980b9';
      toast('Onboarding link sent to ' + name);
    } else {
      btn.textContent = '📋 Onboard'; btn.disabled = false;
      toast('Error: '+(d.error||'unknown'), true);
    }
  });
}

function sendProposal(name, email, category) {
  if (!email) { alert('No email address for this lead'); return; }
  if (!confirm('Send proposal to ' + name + ' at ' + email + '?')) return;
  const btn = event.currentTarget || event.target;
  const orig = btn.textContent;
  btn.textContent = 'Sending…'; btn.disabled = true;
  fetch('/action/send-proposal', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body: JSON.stringify({name, email, category})
  }).then(r=>r.json()).then(d => {
    if (d.ok) {
      btn.textContent = '✓ Sent';
      btn.style.background='#1a3a00'; btn.style.color='#7ed321';
      toast('Proposal sent to ' + name);
    } else {
      btn.textContent = orig; btn.disabled = false;
      toast('Error: '+(d.error||'unknown'), true);
    }
  });
}

function sendDigest() {
  if (!confirm('Send weekly digest to mayasierra1999@gmail.com?')) return;
  fetch('/action/send-digest',{method:'POST'})
    .then(r=>r.json())
    .then(()=>toast('Weekly digest sent!'));
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

const _OUTREACH_TABS = ['send-queue','send-detail','email-replies','email','bounces','analytics','zones','subjects','categories','timing','templates','copywriter'];

function showPage(name) {
  if (name === 'outreach') name = 'send-queue';
  document.querySelectorAll('[id^="page-"]').forEach(el => el.style.display = 'none');
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  const pageEl = document.getElementById('page-' + name);
  if (pageEl) pageEl.style.display = 'block';
  const tabBar = document.getElementById('outreach-tabbar');
  if (_OUTREACH_TABS.includes(name)) {
    if (tabBar) tabBar.style.display = '';
    const navEl = document.getElementById('nav-outreach');
    if (navEl) navEl.classList.add('active');
    document.querySelectorAll('.otab').forEach(el => el.classList.remove('active'));
    const otab = document.querySelector(`.otab[data-ot="${name}"]`);
    if (otab) otab.classList.add('active');
  } else {
    if (tabBar) tabBar.style.display = 'none';
    const navEl = document.getElementById('nav-' + name);
    if (navEl) navEl.classList.add('active');
  }
}

// ── Init ───────────────────────────────────────────────────────────────────────
renderHealth();
renderCreditMeter();
renderClickerAlert();
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
    const cards = items.map(p => {
      const today = new Date().toISOString().slice(0,10);
      let deadlineHtml = '';
      if (p.deadline) {
        const daysLeft = Math.round((new Date(p.deadline) - new Date(today)) / 86400000);
        const dlColor  = daysLeft < 0 ? '#e74c3c' : daysLeft <= 2 ? '#f39c12' : '#888';
        const dlLabel  = daysLeft < 0 ? `OVERDUE ${Math.abs(daysLeft)}d`
                       : daysLeft === 0 ? 'DUE TODAY'
                       : `${daysLeft}d left`;
        deadlineHtml = `<div style="color:${dlColor};font-size:11px;font-weight:700;margin-bottom:6px">⏰ ${dlLabel} — ${p.deadline}</div>`;
      }
      const milestones = (p.milestones && p.milestones.length)
        ? p.milestones
        : [{"label":"Intake received","done":false},{"label":"Mockup sent","done":false},{"label":"Site built","done":false},{"label":"Live","done":false}];
      const doneCt = milestones.filter(m=>m.done).length;
      const milPct = Math.round(doneCt / milestones.length * 100);
      const milHtml = milestones.map((m,i) =>
        `<div class="milestone-row" onclick="toggleMilestone('${p.phone}',${i})">
          <input type="checkbox" ${m.done?'checked':''} onchange="toggleMilestone('${p.phone}',${i})" onclick="event.stopPropagation()">
          <span style="font-size:11px;color:${m.done?'#333':'#aaa'}" class="${m.done?'milestone-done':''}">${m.label}</span>
        </div>`
      ).join('');

      return `
      <div style="background:#1a1a1a;border:1px solid ${STAGE_BORDER[stage]};border-radius:6px;padding:12px;margin-bottom:8px">
        <div style="font-weight:700;color:#C9A96E;margin-bottom:2px">${p.name}</div>
        <div style="color:#666;font-size:11px;margin-bottom:6px">${p.category} &nbsp;·&nbsp; started ${p.started||'—'}</div>
        ${deadlineHtml}
        ${p.notes ? `<div style="color:#888;font-size:11px;margin-bottom:6px;font-style:italic">${p.notes.slice(0,80)}</div>` : ''}

        <div style="margin-bottom:8px">
          <div style="display:flex;justify-content:space-between;font-size:10px;color:#555;margin-bottom:4px">
            <span>Progress</span><span>${doneCt}/${milestones.length} · ${milPct}%</span>
          </div>
          <div style="background:#111;border-radius:3px;height:4px;margin-bottom:6px">
            <div style="width:${milPct}%;background:#C9A96E;height:4px;border-radius:3px;transition:width .3s"></div>
          </div>
          ${milHtml}
        </div>

        <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:8px">
          ${STAGES.filter(s=>s!==stage).map(s=>`
            <button class="btn-sm btn-outline" onclick="moveProject('${p.phone}','${s}')" style="font-size:10px;padding:3px 7px">${s==='Live'?'✓ Live':s}</button>
          `).join('')}
          <button class="btn-sm" onclick="generateProposal('${p.phone}','${esc(p.name)}','${esc(p.category)}','')" style="font-size:10px;padding:3px 7px;background:#1a2a00;color:#7ed321;border:1px solid #2a4a00">📄 Proposal</button>
        </div>
      </div>`;
    }).join('') || '<div style="color:#333;font-size:11px;padding:8px 0">Empty</div>';
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

function toggleMilestone(phone, index) {
  const projects = DATA.projects || [];
  const proj = projects.find(p=>p.phone===phone);
  if (!proj) return;
  const mils = proj.milestones || [];
  if (!mils[index]) return;
  mils[index].done = !mils[index].done;
  proj.milestones = mils;
  fetch('/action/update-milestone',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({phone, milestones: mils})
  }).then(()=>renderProjects());
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

// ── Invoices ────────────────────────────────────────────────────────────────────

function showNewInvoiceForm() {
  const form = document.getElementById('invoice-new-form');
  form.style.display = form.style.display === 'none' ? '' : 'none';
  // Populate client datalist
  const dl = document.getElementById('inv-name-list');
  if (dl) dl.innerHTML = (DATA.projects||[]).map(p=>`<option value="${p.name}">`).join('');
  // Default due date 14 days out
  const due = document.getElementById('inv-due');
  if (due && !due.value) {
    const d = new Date(); d.setDate(d.getDate()+14);
    due.value = d.toISOString().slice(0,10);
  }
}

async function createInvoice() {
  const name   = document.getElementById('inv-name').value.trim();
  const amount = parseInt(document.getElementById('inv-amount').value) || 799;
  const due    = document.getElementById('inv-due').value;
  const notes  = document.getElementById('inv-notes').value.trim();
  if (!name) { toast('Enter a client name', true); return; }
  const proj = (DATA.projects||[]).find(p=>p.name.toLowerCase()===name.toLowerCase());
  const r = await fetch('/action/create-invoice',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name, phone: proj?.phone||'', category: proj?.category||'', amount, due_date: due, notes})});
  const d = await r.json();
  if (d.ok) {
    DATA.invoices = d.invoices;
    toast('Invoice created!');
    document.getElementById('invoice-new-form').style.display = 'none';
    renderInvoices();
  } else toast('Error: '+(d.error||'unknown'),true);
}

async function markInvoicePaid(id) {
  const r = await fetch('/action/mark-payment',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({id})});
  const d = await r.json();
  if (d.ok) { DATA.invoices = d.invoices; toast('Marked paid!'); renderInvoices(); }
  else toast('Error: '+(d.error||'unknown'),true);
}

function renderInvoices() {
  const listEl    = document.getElementById('invoice-list');
  const summaryEl = document.getElementById('invoices-summary');
  const badgeEl   = document.getElementById('badge-invoices');
  const invoices  = DATA.invoices || [];
  const unpaid    = invoices.filter(i=>!i.paid);
  const paid      = invoices.filter(i=>i.paid);
  const unpaidAmt = unpaid.reduce((s,i)=>s+(i.amount||0),0);
  const paidAmt   = paid.reduce((s,i)=>s+(i.amount||0),0);

  if (badgeEl) badgeEl.textContent = unpaid.length || '';

  if (summaryEl) summaryEl.innerHTML = `
    <div class="card" style="min-width:130px;text-align:center">
      <div class="card-num" style="color:#C9A96E">$${unpaidAmt.toLocaleString()}</div>
      <div class="card-label">Outstanding</div>
      <div style="font-size:10px;color:#555;margin-top:4px">${unpaid.length} invoice${unpaid.length!==1?'s':''}</div>
    </div>
    <div class="card" style="min-width:130px;text-align:center">
      <div class="card-num green">$${paidAmt.toLocaleString()}</div>
      <div class="card-label">Collected</div>
      <div style="font-size:10px;color:#555;margin-top:4px">${paid.length} paid</div>
    </div>
    <div class="card" style="min-width:130px;text-align:center">
      <div class="card-num">${invoices.length}</div>
      <div class="card-label">Total Invoices</div>
    </div>`;

  if (!invoices.length) {
    listEl.innerHTML = '<p class="empty">No invoices yet. Create one for each client you book.</p>'; return;
  }

  const today = new Date().toISOString().slice(0,10);
  listEl.innerHTML = [...unpaid, ...paid].map(inv => {
    const overdue = !inv.paid && inv.due_date && inv.due_date < today;
    const dueLabel = inv.due_date
      ? (overdue ? `<span style="color:#e74c3c;font-weight:700">OVERDUE — ${inv.due_date}</span>`
                 : `Due: ${inv.due_date}`)
      : 'No due date';
    return `<div class="inv-card ${inv.paid?'inv-paid':'inv-unpaid'}">
      <div>
        <div style="font-size:14px;font-weight:700;color:#C9A96E;margin-bottom:3px">${inv.name}</div>
        <div style="font-size:12px;color:#666">${inv.notes||''}</div>
        <div style="font-size:11px;color:#555;margin-top:4px">${dueLabel}</div>
        ${inv.paid ? `<div style="font-size:11px;color:#27ae60;margin-top:2px">✓ Paid ${inv.paid_date||''}</div>` : ''}
      </div>
      <div style="display:flex;flex-direction:column;align-items:flex-end;gap:8px">
        <div style="font-size:22px;font-weight:700;color:${inv.paid?'#27ae60':'#C9A96E'}">$${(inv.amount||0).toLocaleString()}</div>
        ${!inv.paid ? `<button class="btn btn-sm btn-green" onclick="markInvoicePaid('${inv.id}')">Mark Paid ✓</button>` : ''}
      </div>
    </div>`;
  }).join('');
}

// ── Proposal Generator ──────────────────────────────────────────────────────────

async function generateProposal(phone, name, category, address) {
  const btn = event.target;
  btn.disabled = true; btn.textContent = 'Generating…';
  const proj = (DATA.projects||[]).find(p=>p.phone===phone);
  const mockupNote = (proj?.notes||'').match(/mockup:\s*(https?:\/\/\S+)/i);
  const mockupUrl  = mockupNote ? mockupNote[1] : '';
  const lead = DATA.leads.find(l=>l.phone===phone);
  const r = await fetch('/action/generate-proposal',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name, category, mockup_url: mockupUrl, rating: lead?.rating||'', review_count: lead?.reviews||''})});
  const d = await r.json();
  btn.disabled = false; btn.textContent = '📄 Generate Proposal PDF';
  if (d.ok) {
    toast('Proposal ready!');
    const a = document.createElement('a');
    a.href = d.url; a.download = d.filename; a.click();
  } else toast('Error: '+(d.error||'unknown'),true);
}

// ── Send History / Daily Detail ────────────────────────────────────────────────

function showSendDetail(date) {
  showPage('send-detail');
  if (date) renderSendDetail(date);
  else      renderSendHistory();
}

function renderSendHistory() {
  const detail  = DATA.daily_send_detail || {};
  const dates   = Object.keys(detail).sort().reverse();
  const el      = document.getElementById('send-detail-content');
  if (!dates.length) {
    el.innerHTML = '<p class="empty">No send history yet.</p>';
    return;
  }
  // Build lookup from Stats API (accurate opens/clicks for all dates)
  const sgStats = {};
  (DATA.sg_daily || []).forEach(d => { sgStats[d.date] = d; });

  const rows = dates.map(date => {
    const entries  = detail[date];
    const sent     = entries.length;
    // Activity Feed: unique clickers (deduplicated by email — same lead may appear in multiple log types)
    const _seen = new Set();
    const clickers = entries.filter(r => r.clicked && !r.is_bot && !_seen.has(r.email) && (_seen.add(r.email)||true)).length;
    // Stats API: aggregate opens/clicks (45-day window, accurate totals)
    const sg       = sgStats[date] || {};
    const sgOpens  = sg.opens  || 0;
    const sgClicks = sg.clicks || 0;
    const sgSent   = sg.sent   || sent;
    const openPct  = sgSent ? Math.round(sgOpens  / sgSent * 100) : 0;
    const clickPct = sgSent ? Math.round(sgClicks / sgSent * 100) : 0;
    const hasClickers = clickers > 0;
    return `<tr class="clickable" onclick="renderSendDetail('${date}')">
      <td style="color:#C9A96E;font-weight:700">${date}</td>
      <td style="text-align:center">${sent}</td>
      <td style="text-align:center;color:${openPct>=20?'#f39c12':'#888'}">${sgOpens} <span style="color:#555;font-size:11px">(${openPct}%)</span></td>
      <td style="text-align:center;color:${clickPct>=2?'#7ed321':'#888'}">${sgClicks} <span style="color:#555;font-size:11px">(${clickPct}%)</span></td>
      <td>
        <button class="btn btn-sm ${hasClickers?'btn-green':'btn-outline'}" onclick="event.stopPropagation();renderSendDetail('${date}')">
          ${hasClickers ? `🔥 ${clickers} named` : 'View all →'}
        </button>
      </td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <p class="section-title" style="margin-bottom:12px">Email Send History — opens &amp; clicks from SendGrid Stats API · click any date to see who clicked</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Date</th><th style="text-align:center">Sent</th><th style="text-align:center">Opened</th><th style="text-align:center">Clicked</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function renderSendDetail(date) {
  const all = (DATA.daily_send_detail || {})[date] || [];
  const el  = document.getElementById('send-detail-content');
  if (!all.length) {
    el.innerHTML = `<p class="empty">No send data for ${date}.</p>
      <button class="btn btn-sm btn-outline" onclick="renderSendHistory()" style="margin-top:12px">← Back to History</button>`;
    return;
  }
  // Deduplicate by email — same email can appear in outreach + followup + re-engagement logs
  const seenEmails = new Set();
  const clickers = all.filter(r => r.clicked && !r.is_bot && !seenEmails.has(r.email) && (seenEmails.add(r.email) || true));
  const openers  = all.filter(r => r.opens > 0 && !r.clicked && !r.is_bot && !seenEmails.has(r.email) && (seenEmails.add(r.email) || true));
  const bots     = all.filter(r => r.is_bot);

  const clickerRows = clickers.map(r => {
    const lead  = DATA.leads.find(l => l.email === r.email) || {};
    const phone = lead.phone || '';
    return `<tr class="clickable" onclick="openPanel('${phone||r.email}')">
      <td><strong>${r.name}</strong>${phone?'':' <span style="color:#555;font-size:10px">no phone</span>'}</td>
      <td style="color:#888;font-size:12px">${r.category}</td>
      <td style="font-size:12px;color:#555">${r.email}</td>
      <td style="font-size:12px;color:#aaa">${r.subject}</td>
      <td style="text-align:center;color:#f39c12">${r.opens}</td>
      <td style="text-align:center;color:#7ed321;font-weight:700">${r.clicks}</td>
      <td>
        ${phone
          ? `<div style="display:flex;gap:6px">
              <button class="btn btn-sm btn-green" onclick="event.stopPropagation();sendQuickSms('${phone}','${esc(r.name)}','${esc(r.category)}')">📱 SMS</button>
              <button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${phone}')">View →</button>
            </div>`
          : '<span style="color:#444;font-size:11px">no phone on file</span>'}
      </td>
    </tr>`;
  }).join('');

  const allRows = all.filter(r => !r.is_bot).map(r => {
    const statusCls = r.clicked ? 'color:#7ed321' : r.opens > 0 ? 'color:#f39c12' : 'color:#333';
    const statusLbl = r.clicked ? '🔥 CLICKED' : r.opens > 0 ? '👁 OPENED' : '— sent';
    return `<tr>
      <td><strong>${r.name}</strong></td>
      <td style="color:#888;font-size:12px">${r.category}</td>
      <td style="font-size:12px;color:#555">${r.email}</td>
      <td style="font-size:12px;color:#666">${r.subject}</td>
      <td style="text-align:center;color:#666">${r.opens||'—'}</td>
      <td style="text-align:center;${statusCls};font-weight:700;font-size:11px">${statusLbl}</td>
    </tr>`;
  }).join('');

  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap">
      <h2 style="color:#C9A96E;margin:0;font-size:18px">${date}</h2>
      <span style="color:#555;font-size:13px">${all.length} sent</span>
      <span style="color:#f39c12;font-size:13px">· ${openers.length + clickers.length} opened</span>
      <span style="color:#7ed321;font-size:13px;font-weight:700">· ${clickers.length} clicked 🔥</span>
      ${bots.length ? `<span style="color:#e74c3c;font-size:11px">· ${bots.length} bot click${bots.length!==1?'s':''} filtered</span>` : ''}
      <button class="btn btn-sm btn-outline" onclick="renderSendHistory()" style="margin-left:auto">← All Dates</button>
    </div>

    ${clickers.length ? `
    <p class="section-title">🔥 Clicked Your Link — Follow Up NOW (${clickers.length})</p>
    <div class="tbl-wrap" style="margin-bottom:28px"><table>
      <thead><tr><th>Business</th><th>Category</th><th>Email</th><th>Subject Sent</th><th>Opens</th><th>Clicks</th><th>Action</th></tr></thead>
      <tbody>${clickerRows}</tbody>
    </table></div>`
    : `<div class="notice" style="margin-bottom:20px">No identifiable clickers for ${date} — SendGrid Activity Feed retains individual identity for ~7 days. Click data may have expired for older dates.</div>`}

    <p class="section-title">All ${all.filter(r=>!r.is_bot).length} Emails Sent on ${date}</p>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Business</th><th>Category</th><th>Email</th><th>Subject</th><th>Opens</th><th>Status</th></tr></thead>
      <tbody>${allRows}</tbody>
    </table></div>`;
}

// ── Send Queue (pre-send approval) ────────────────────────────────────────────

function renderSendQueue() {
  const queue  = DATA.pending_queue || [];
  const date   = DATA.queue_date || '';
  const csv    = DATA.queue_csv  || '';
  const el     = document.getElementById('send-queue-content');
  const badge  = document.getElementById('badge-send-queue');
  if (badge) badge.textContent = queue.length || '';
  if (!queue.length) {
    el.innerHTML = `
      <div class="notice">No send queue found yet. Tomorrow's outreach is staged each morning when the cron pipeline runs (9AM). To stage manually tonight: run <code>python3 build_unsent_csv.py</code> then <code>python3 enrich_emails.py</code>, then refresh.</div>`;
    return;
  }
  const todayIso = new Date().toISOString().slice(0,10);
  const isToday  = date === todayIso;
  const label    = isToday ? "Today's Outreach Queue" : `Staged for ${date}`;
  const rows = queue.map((r, i) => {
    const stars   = r.rating ? ('★'.repeat(Math.min(5,Math.round(parseFloat(r.rating||0)))) + '☆'.repeat(Math.max(0,5-Math.round(parseFloat(r.rating||0))))) : '';
    const siteTag = r.has_website && r.has_website !== 'No'
      ? `<span style="color:#e74c3c;font-size:10px;margin-left:4px">HAS SITE</span>` : '';
    return `<tr id="qrow-${i}">
      <td>
        <strong>${r.name}</strong>${siteTag}<br>
        <span style="color:#555;font-size:11px">${r.address||r.city||''}</span>
      </td>
      <td style="color:#888;font-size:12px">${r.category}</td>
      <td style="font-size:12px;color:#555">${r.email}</td>
      <td style="color:#C9A96E;font-size:13px">${stars}<span style="color:#555;font-size:11px;margin-left:4px">${r.rating||''}</span></td>
      <td>
        <div style="display:flex;gap:6px">
          <button class="btn btn-sm btn-outline" onclick="previewQueueEmail(${i})">👁 Preview</button>
          <button class="btn btn-sm" style="background:#2a0a0a;color:#e74c3c;border:1px solid #e74c3c"
            onclick="skipQueued(${i},'${esc(r.email)}','${esc(date)}')">Skip</button>
        </div>
      </td>
    </tr>`;
  }).join('');
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px;flex-wrap:wrap">
      <div>
        <h2 style="color:#C9A96E;margin:0 0 4px;font-size:18px">📋 ${label}</h2>
        <div style="color:#555;font-size:12px">Source: ${csv} · ${queue.length} leads queued · Skip any you don't want sent</div>
      </div>
      <button class="btn btn-sm btn-green" style="margin-left:auto;padding:8px 20px;font-size:13px"
        onclick="sendQueueNow()">
        🚀 Send ${queue.length} Emails Now
      </button>
    </div>
    <div class="tbl-wrap"><table>
      <thead><tr><th>Business</th><th>Category</th><th>Email</th><th>Rating</th><th>Actions</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>`;
}

function skipQueued(idx, email, date) {
  const row = document.getElementById('qrow-'+idx);
  fetch('/action/skip-queued', {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({email, date})})
    .then(r=>r.json())
    .then(d => {
      if (d.ok && row) {
        row.style.opacity = '0.3';
        row.style.textDecoration = 'line-through';
        toast('Skipped — will not be sent');
      }
    });
}

function previewQueueEmail(idx) {
  const lead = (DATA.pending_queue||[])[idx];
  if (!lead) return;
  fetch('/action/preview-email', {method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({name:lead.name, category:lead.category, phone:lead.phone,
      city:lead.city, rating:lead.rating, review_count:lead.reviews})})
    .then(r=>r.json())
    .then(d => {
      if (!d.ok) { toast('Preview error: '+(d.error||'unknown'), true); return; }
      const w = window.open('','_blank','width=700,height=800,scrollbars=yes');
      if (w) { w.document.write(d.html); w.document.close(); }
    });
}

function sendQueueNow() {
  if (!confirm('Send emails to ALL non-skipped leads in the queue? This will start the outreach pipeline.')) return;
  fetch('/action/send-queue-now', {method:'POST',headers:{'Content-Type':'application/json'},body:'{}'})
    .then(r=>r.json())
    .then(d => toast(d.ok ? '🚀 Send job started — check Email Log in a few minutes' : 'Error: '+(d.error||'unknown'), !d.ok));
}

function showGoalEditor() {
  const current = (DATA.revenue_goal||{}).monthly || 3000;
  const val = prompt('Monthly revenue goal ($):', current);
  if (!val || isNaN(val) || parseInt(val) <= 0) return;
  fetch('/action/set-goal', {
    method: 'POST',
    headers: {'Content-Type':'application/json'},
    body: JSON.stringify({monthly: parseInt(val)})
  }).then(r=>r.json()).then(d => {
    if (d.ok) {
      if (!DATA.revenue_goal) DATA.revenue_goal = {};
      DATA.revenue_goal.monthly = parseInt(val);
      renderToday();
      toast('Goal updated!');
    }
  });
}

const _errBox = document.createElement('div');
_errBox.id = 'js-errors';
_errBox.style.cssText = 'display:none;position:fixed;bottom:12px;left:12px;background:#300;color:#f88;font-size:11px;padding:10px 14px;border-radius:6px;z-index:9999;max-width:480px;white-space:pre-wrap;border:1px solid #600';
document.body.appendChild(_errBox);

function _run(name, fn) {
  try { fn(); }
  catch(e) {
    console.error(name + ':', e);
    _errBox.style.display = 'block';
    _errBox.textContent += name + ': ' + e.message + '\n';
  }
}

_run('Nudge',       renderNudge);
_run('Stats',       renderStats);
_run('Today',       renderToday);
_run('Warm',        renderWarm);
_run('SmsReplies',  renderSmsReplies);
_run('EmailReplies',renderEmailReplies);
_run('Queue',       renderQueue);
_run('AllLeads',    () => renderAllLeads(DATA.leads));
_run('SmsLog',      renderSmsLog);
_run('EmailLog',    renderEmailLog);
_run('Bounces',     renderBounces);
_run('Forecast',    renderForecast);
_run('Funnel',      renderFunnel);
_run('Zones',         renderZones);
_run('SubjectStats',  renderSubjectStats);
_run('Analytics',     renderAnalytics);
_run('Intakes',     renderIntakes);
_run('Projects',    renderProjects);
_run('Invoices',    renderInvoices);
_run('Revenue',       renderRevenue);
_run('HotAlert',      () => _checkHotAlert((DATA.clicker_leads||[]).length));
_run('SendHistory',   renderSendHistory);
_run('SendQueue',     renderSendQueue);
_run('Categories',    renderCategoryStats);
_run('Timing',        renderTimingStats);
_run('Templates',     renderTemplateEditor);
_run('CopyWriter',    renderCopyWriter);
_run('StripePayments', renderStripePayments);

// ── Auto-refresh every 5 minutes ───────────────────────────────────────────────
(function() {
  function _updateRefreshStamp() {
    const el = document.getElementById('last-refresh');
    if (el) el.textContent = 'Live · ' + new Date().toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'});
  }
  _updateRefreshStamp();
  setInterval(async () => {
    try {
      const resp = await fetch('/api/data');
      if (!resp.ok) return;
      const fresh = await resp.json();
      Object.assign(DATA, fresh);
      // Re-render whatever page is active
      const active = document.querySelector('.nav-item.active, .otab.active');
      if (active) { const fn = active.getAttribute('onclick'); if (fn) new Function(fn)(); }
      _run('Stats',   renderStats);
      _run('Today',   renderToday);
      _updateRefreshStamp();
    } catch(e) {}
  }, 5 * 60 * 1000);
})();
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
        # Serve proposal PDFs
        if self.path.startswith("/proposals/"):
            filename = self.path[len("/proposals/"):]
            if filename and ".." not in filename:
                pdf_path = SCRIPT_DIR / "proposals" / filename
                if pdf_path.exists() and pdf_path.suffix == ".pdf":
                    self.send_response(200)
                    self.send_header("Content-Type", "application/pdf")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.end_headers()
                    self.wfile.write(pdf_path.read_bytes())
                    return
            self._respond(404, "text/plain", b"Proposal not found")
            return
        if self.path in ("/data.json", "/api/data"):
            # Trigger background refresh, return current cache immediately
            threading.Thread(target=_refresh_cache, daemon=True).start()
            data = get_cached_data()
            if data is None:
                self._respond(503, "application/json", b'{"error":"loading"}')
            else:
                self._respond(200, "application/json", json.dumps(data, default=str).encode("utf-8"))
            return
        # Serve onboarding form (public-facing client intake)
        if self.path.startswith("/onboard"):
            onboard_tmpl = SCRIPT_DIR / "onboard_template.html"
            if onboard_tmpl.exists():
                self._respond(200, "text/html; charset=utf-8", onboard_tmpl.read_bytes())
            else:
                self._respond(404, "text/plain", b"Onboarding template not found")
            return
        # Main dashboard — serve from cache; show loading page if cache not ready
        data = get_cached_data()
        if data is None:
            loading = b"""<!DOCTYPE html><html><head><meta charset=UTF-8>
<meta http-equiv="refresh" content="3">
<style>body{background:#0a0a0e;color:#C9A96E;font-family:-apple-system,sans-serif;
display:flex;align-items:center;justify-content:center;height:100vh;margin:0;flex-direction:column;gap:16px}
.dot{animation:pulse 1.2s infinite}.dot:nth-child(2){animation-delay:.4s}.dot:nth-child(3){animation-delay:.8s}
@keyframes pulse{0%,80%,100%{opacity:.2}40%{opacity:1}}</style></head>
<body><h2 style="margin:0">WebByMaya</h2>
<div style="display:flex;gap:8px"><div class=dot style="width:10px;height:10px;background:#C9A96E;border-radius:50%"></div>
<div class=dot style="width:10px;height:10px;background:#C9A96E;border-radius:50%"></div>
<div class=dot style="width:10px;height:10px;background:#C9A96E;border-radius:50%"></div></div>
<p style="color:#444;font-size:14px;margin:0">Loading your data...</p></body></html>"""
            self._respond(200, "text/html; charset=utf-8", loading)
            return
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

        elif self.path == "/action/preview-email":
            name     = body.get("name","").strip()
            category = body.get("category","").strip()
            try:
                import sys as _sys
                _sys.path.insert(0, str(SCRIPT_DIR))
                from batch_send_outreach import build_email_body
                _, html = build_email_body(name, category)
                self._respond(200,"application/json",json.dumps({"ok":True,"html":html}).encode())
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

        elif self.path == "/action/generate-proposal":
            name     = body.get("name","").strip()
            category = body.get("category","").strip()
            mockup_url = body.get("mockup_url","").strip()
            rating   = body.get("rating","")
            reviews  = body.get("review_count","")
            if not name:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"No name."}).encode())
                return
            try:
                import sys as _sys
                _sys.path.insert(0, str(SCRIPT_DIR))
                from generate_proposal import make_proposal
                out_path = make_proposal(name, category=category, mockup_url=mockup_url,
                                         rating=str(rating), review_count=str(reviews))
                url = f"/proposals/{out_path.name}"
                self._respond(200,"application/json",json.dumps({"ok":True,"url":url,"filename":out_path.name}).encode())
            except Exception as e:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":str(e)}).encode())

        elif self.path == "/action/update-milestone":
            phone      = body.get("phone","")
            milestones = body.get("milestones",[])
            projects   = _load_projects()
            for p in projects:
                if p.get("phone") == phone:
                    p["milestones"] = milestones
                    break
            _save_projects(projects)
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/create-invoice":
            invoices = _load_invoices()
            inv_id   = f"inv_{body.get('phone','x')}_{int(datetime.now().timestamp())}"
            invoices.append({
                "id":       inv_id,
                "phone":    body.get("phone",""),
                "name":     body.get("name",""),
                "category": body.get("category",""),
                "amount":   int(body.get("amount",799)),
                "due_date": body.get("due_date",""),
                "notes":    body.get("notes",""),
                "paid":     False,
                "paid_date":"",
                "created":  datetime.now().strftime("%Y-%m-%d"),
            })
            _save_invoices(invoices)
            self._respond(200,"application/json",json.dumps({"ok":True,"invoices":invoices}).encode())

        elif self.path == "/action/mark-payment":
            inv_id   = body.get("id","")
            invoices = _load_invoices()
            for inv in invoices:
                if inv.get("id") == inv_id:
                    inv["paid"]      = True
                    inv["paid_date"] = datetime.now().strftime("%Y-%m-%d")
                    break
            _save_invoices(invoices)
            self._respond(200,"application/json",json.dumps({"ok":True,"invoices":invoices}).encode())

        elif self.path == "/action/skip-queued":
            email  = body.get("email","").lower().strip()
            qdate  = body.get("date", datetime.now().strftime("%Y-%m-%d"))
            skip_f = SCRIPT_DIR / f"send_skips_{qdate}.json"
            skips  = json.loads(skip_f.read_text()) if skip_f.exists() else []
            if email and email not in skips:
                skips.append(email)
            skip_f.write_text(json.dumps(skips))
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/send-queue-now":
            import subprocess as _sp
            _env = dict(os.environ)
            _sp.Popen([sys.executable, str(SCRIPT_DIR/"scheduled_send.py"),
                       "--sms-limit","0","--email-limit","1500"],
                      env=_env, cwd=str(SCRIPT_DIR))
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/set-goal":
            goal_path = SCRIPT_DIR / "revenue_goal.json"
            existing  = json.loads(goal_path.read_text()) if goal_path.exists() else {}
            existing.update(body)
            goal_path.write_text(json.dumps(existing))
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/send-proposal":
            result = send_proposal_email(body.get("name",""), body.get("email",""), body.get("category",""))
            self._respond(200,"application/json",json.dumps(result).encode())

        elif self.path == "/action/send-onboard-link":
            name  = body.get("name","")
            email = body.get("email","")
            import hashlib
            token = hashlib.md5(f"{name}{email}".encode()).hexdigest()[:12]
            link  = f"https://webbymaya.com/onboard?token={token}"
            # For now serve from localhost (update URL when hosted publicly)
            local_link = f"http://localhost:8787/onboard?token={token}"
            if not SG:
                self._respond(200,"application/json",json.dumps({"ok":False,"error":"No SendGrid key"}).encode())
            else:
                try:
                    html_body = f"""<div style="font-family:sans-serif;max-width:560px;margin:auto;color:#222;line-height:1.6">
<p>Hi there,</p>
<p>Great news — I'm ready to start building your website! To get started, I just need a few details from you.</p>
<p>Please fill out this quick form (takes about 5 minutes):</p>
<p style="text-align:center;margin:24px 0">
  <a href="{local_link}" style="background:#C9A96E;color:#fff;padding:14px 28px;border-radius:8px;text-decoration:none;font-weight:700;font-size:16px">
    Fill Out My Content Form →
  </a>
</p>
<p>You can upload your logo, photos, and tell me all about your business. The more you share, the better I can make your site!</p>
<p>Any questions? Just reply to this email.</p>
<p>Best,<br><b>Maya</b><br>WebByMaya | webbymaya.com</p>
</div>"""
                    payload = json.dumps({
                        "personalizations": [{"to":[{"email":email}]}],
                        "from": {"email":"maya@webbymaya.com","name":"Maya — WebByMaya"},
                        "subject": f"Your website is next — fill out this quick form, {name}",
                        "content": [{"type":"text/html","value":html_body}]
                    }).encode()
                    req = urllib.request.Request(
                        "https://api.sendgrid.com/v3/mail/send",
                        data=payload,
                        headers={"Authorization":f"Bearer {SG}","Content-Type":"application/json"},
                        method="POST")
                    urllib.request.urlopen(req, timeout=10)
                    self._respond(200,"application/json",json.dumps({"ok":True,"token":token,"link":local_link}).encode())
                except Exception as ex:
                    self._respond(200,"application/json",json.dumps({"ok":False,"error":str(ex)}).encode())

        elif self.path == "/action/send-digest":
            send_weekly_digest()
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/save-template":
            p = SCRIPT_DIR / "email_template.json"
            json.dump(body, open(p,"w"), indent=2)
            self._respond(200,"application/json",json.dumps({"ok":True}).encode())

        elif self.path == "/action/generate-copy":
            result = generate_homepage_copy(
                body.get("name",""), body.get("category",""),
                body.get("rating"), body.get("reviews"), body.get("description",""))
            self._respond(200,"application/json",json.dumps(result).encode())

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
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass

if __name__ == "__main__":
    os.chdir(SCRIPT_DIR)
    print(f"\n  WebByMaya Outreach Console v3")
    print(f"  Open: http://localhost:{PORT}")
    print(f"  Building data in background — dashboard loads instantly, data ready in ~20s\n")
    # Start background cache thread before accepting requests
    threading.Thread(target=_cache_loop, daemon=True).start()
    HTTPServer(("", PORT), Handler).serve_forever()
