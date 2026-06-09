#!/usr/bin/env python3
"""
dashboard.py — WebByMaya Outreach Console v2
Run:  python3 dashboard.py
Open: http://localhost:8787
"""
import base64, csv, json, os, urllib.request, urllib.parse, urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from sb import set_lead_status, queue_followup, log_sms

SCRIPT_DIR = Path(__file__).parent
PORT = 8787
SID   = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN = os.environ.get("TWILIO_AUTH_TOKEN","")
PHONE = os.environ.get("TWILIO_PHONE_NUMBER","")
SG    = os.environ.get("SENDGRID_API_KEY","")

FOLLOWUP_MSG = (
    "Hi {name}! This is Maya from WebByMaya following up on my earlier message. "
    "I'd love to chat about getting {name} online — I have a quick slot open this week. "
    "Free 20-min call: https://webbymaya.com/book"
)

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

def load_statuses():
    rows = load_csv(SCRIPT_DIR / "lead_status.csv")
    return {r["phone"]: r for r in rows}

def save_status(phone, name, category, status, note=""):
    set_lead_status(phone, name, category, status, note)
    path = SCRIPT_DIR / "lead_status.csv"
    rows = load_csv(path)
    existing = next((r for r in rows if r["phone"] == phone), None)
    if existing:
        existing["status"] = status
        existing["note"]   = note
        existing["updated"] = datetime.now().isoformat(timespec="seconds")
    else:
        rows.append({"phone": phone, "name": name, "category": category,
                     "status": status, "note": note,
                     "updated": datetime.now().isoformat(timespec="seconds")})
    save_csv(path, rows, ["phone","name","category","status","note","updated"])

def load_followup_queue():
    return load_csv(SCRIPT_DIR / "followup_queue.csv")

def add_to_queue(phone, name, category, send_after, reason):
    queue_followup(phone, name, category, send_after, reason)
    path = SCRIPT_DIR / "followup_queue.csv"
    rows = load_csv(path)
    if any(r["phone"] == phone and r["sent"] == "no" for r in rows):
        return False  # already queued
    rows.append({"phone": phone, "name": name, "category": category,
                 "send_after": send_after, "reason": reason,
                 "sent": "no", "queued_at": datetime.now().isoformat(timespec="seconds")})
    save_csv(path, rows, ["phone","name","category","send_after","reason","sent","queued_at"])
    return True

# ── Twilio / SendGrid helpers ──────────────────────────────────────────────────

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

# ── Build dataset ──────────────────────────────────────────────────────────────

STOP_WORDS = {"stop","stopall","unsubscribe","cancel","end","quit"}
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
    send_logs  = all_logs("send_log_*.csv")
    bounces    = load_csv(SCRIPT_DIR / "bounce_log.csv")
    inbound    = fetch_inbound()
    sg_stats   = fetch_sg_stats()
    suppressed = fetch_suppressed()
    statuses   = load_statuses()
    queue      = load_followup_queue()

    real_replies, opt_outs, auto_replies = categorize(inbound)
    replied_phones = {m["from"] for m in real_replies}
    opted_out_phones = {m["from"] for m in opt_outs}

    # Build per-phone lead records
    leads = {}
    for row in sms_logs:
        p = row.get("phone","").strip()
        if not p: continue
        if p not in leads:
            leads[p] = {
                "phone": p, "name": row.get("name",""), "category": row.get("category",""),
                "address": row.get("address",""), "maps_url": row.get("maps_url",""),
                "sms_sent": 0, "email_sent": 0, "replied": False, "opted_out": False,
                "last_contact": "", "touches": [], "status": "contacted",
                "rating": row.get("rating",""), "reviews": row.get("reviews",""),
            }
        if row.get("status") == "sent":
            leads[p]["sms_sent"] += 1
            leads[p]["last_contact"] = row.get("timestamp","")
        leads[p]["touches"].append({
            "type":"sms_out","ts":row.get("timestamp",""),
            "note": "SMS sent" if row.get("status")=="sent" else row.get("status","")
        })

    for row in send_logs:
        if row.get("status") != "sent": continue
        name = row.get("name","").strip()
        email = row.get("email_sent_to","").strip()
        matched = next((v for v in leads.values() if v["name"].lower()==name.lower()), None)
        if matched:
            matched["email_sent"] += 1
            matched["touches"].append({"type":"email_out","ts":row.get("timestamp",""),"note":email})

    for m in inbound:
        frm  = m.get("from","")
        body = m.get("body","")
        ts   = m.get("date_sent","")
        if frm not in leads: continue
        if frm in replied_phones:
            leads[frm]["replied"] = True
            leads[frm]["status"]  = "warm"
        if frm in opted_out_phones:
            leads[frm]["opted_out"] = True
            leads[frm]["status"]    = "opted_out"
        leads[frm]["touches"].append({"type":"sms_in","ts":ts,"note":body[:100]})

    # Apply manual status overrides
    for phone, s in statuses.items():
        if phone in leads:
            leads[phone]["status"] = s["status"]
            leads[phone]["status_note"] = s.get("note","")

    # Sort touches by timestamp
    for l in leads.values():
        l["touches"].sort(key=lambda x: x.get("ts",""))

    warm  = [l for l in leads.values() if l["replied"] and not l["opted_out"]]
    total_sms   = sum(1 for r in sms_logs if r.get("status")=="sent")
    total_email = sum(1 for r in send_logs if r.get("status")=="sent")

    return {
        "leads": list(leads.values()),
        "sms_logs": sms_logs,
        "send_logs": send_logs,
        "bounces": bounces,
        "inbound": inbound,
        "real_replies": real_replies,
        "opt_outs": opt_outs,
        "auto_replies": auto_replies,
        "warm": warm,
        "sg_stats": sg_stats,
        "suppressed": list(suppressed),
        "queue": queue,
        "stats": {
            "total_sms": total_sms,
            "total_email": total_email,
            "warm": len(warm),
            "replies": len(real_replies),
            "opt_outs": len(opt_outs),
            "bounces": len(bounces),
            "opens": sg_stats.get("opens",0),
            "clicks": sg_stats.get("clicks",0),
        }
    }

# ── HTML ───────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>WebByMaya Console</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#0d0d0d;color:#e0e0e0;font-family:Arial,sans-serif;font-size:14px;display:flex;flex-direction:column;height:100vh;overflow:hidden}
a{color:#C9A96E;text-decoration:none}
header{background:#111;border-bottom:2px solid #C9A96E;padding:14px 28px;display:flex;align-items:center;justify-content:space-between;flex-shrink:0}
header h1{font-family:Georgia,serif;color:#C9A96E;font-size:20px;letter-spacing:1px}
.hdr-right{display:flex;align-items:center;gap:14px}
.hdr-right span{color:#666;font-size:12px}
.btn{background:#C9A96E;color:#111;border:none;padding:7px 16px;border-radius:3px;cursor:pointer;font-weight:bold;font-size:12px;letter-spacing:.3px}
.btn:hover{background:#d4b47a}
.btn-sm{padding:5px 12px;font-size:11px}
.btn-outline{background:transparent;border:1px solid #C9A96E;color:#C9A96E}
.btn-outline:hover{background:#C9A96E;color:#111}
.btn-danger{background:#c0392b}
.btn-danger:hover{background:#e74c3c}
.btn-green{background:#27ae60}
.btn-green:hover{background:#2ecc71}

/* Layout */
.main{display:flex;flex:1;overflow:hidden}
.sidebar{width:220px;background:#111;border-right:1px solid #1e1e1e;display:flex;flex-direction:column;flex-shrink:0}
.nav-item{padding:13px 20px;cursor:pointer;color:#888;font-size:13px;font-weight:bold;text-transform:uppercase;letter-spacing:.5px;border-left:3px solid transparent;display:flex;align-items:center;justify-content:space-between}
.nav-item:hover{color:#ccc;background:#161616}
.nav-item.active{color:#C9A96E;border-left-color:#C9A96E;background:#161616}
.badge-count{background:#C9A96E;color:#111;border-radius:10px;padding:1px 7px;font-size:11px}
.badge-count.red{background:#e74c3c;color:#fff}
.content{flex:1;overflow-y:auto;padding:24px 28px}

/* Cards */
.cards{display:flex;flex-wrap:wrap;gap:14px;margin-bottom:24px}
.card{background:#171717;border:1px solid #222;border-radius:6px;padding:18px 22px;min-width:120px;flex:1}
.card-num{font-size:28px;font-weight:bold;color:#C9A96E}
.card-num.green{color:#2ecc71}
.card-num.red{color:#e74c3c}
.card-num.orange{color:#f39c12}
.card-label{color:#777;font-size:11px;margin-top:3px;text-transform:uppercase;letter-spacing:.5px}

/* Tables */
.section-title{color:#C9A96E;font-size:11px;text-transform:uppercase;letter-spacing:1px;margin-bottom:14px}
table{width:100%;border-collapse:collapse}
th{background:#171717;color:#666;font-size:11px;text-transform:uppercase;letter-spacing:.4px;padding:9px 12px;text-align:left;border-bottom:1px solid #222;position:sticky;top:0}
td{padding:10px 12px;border-bottom:1px solid #181818;vertical-align:middle}
tr.clickable{cursor:pointer}
tr.clickable:hover td{background:#161616}
.tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:11px;font-weight:bold;color:#fff;text-transform:uppercase}
.empty{color:#444;text-align:center;padding:48px;font-size:13px}
.notice{background:#171717;border:1px solid #2a2a2a;border-left:3px solid #C9A96E;padding:12px 16px;border-radius:4px;margin-bottom:18px;font-size:13px;color:#999;line-height:1.6}

/* Lead Panel (right slide-out) */
#panel-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100}
#panel-overlay.open{display:block}
#lead-panel{position:fixed;right:-480px;top:0;bottom:0;width:480px;background:#141414;border-left:1px solid #2a2a2a;z-index:101;transition:right .25s ease;display:flex;flex-direction:column;overflow:hidden}
#lead-panel.open{right:0}
#panel-header{background:#111;border-bottom:1px solid #222;padding:18px 20px;display:flex;align-items:flex-start;justify-content:space-between}
#panel-close{background:none;border:none;color:#888;font-size:22px;cursor:pointer;line-height:1}
#panel-close:hover{color:#fff}
#panel-body{flex:1;overflow-y:auto;padding:20px}
.panel-section{margin-bottom:20px}
.panel-section-title{color:#666;font-size:11px;text-transform:uppercase;letter-spacing:.5px;margin-bottom:8px;padding-bottom:6px;border-bottom:1px solid #1e1e1e}
.info-grid{display:grid;grid-template-columns:100px 1fr;gap:6px 12px}
.info-label{color:#666;font-size:12px}
.info-val{color:#ddd;font-size:12px}
.touch-item{display:flex;gap:10px;padding:8px 0;border-bottom:1px solid #1a1a1a}
.touch-dot{width:8px;height:8px;border-radius:50%;margin-top:4px;flex-shrink:0}
.touch-meta{font-size:11px;color:#666;margin-top:2px}
.action-bar{padding:16px 20px;border-top:1px solid #1e1e1e;display:flex;flex-wrap:wrap;gap:8px;background:#111}

/* Follow-up queue */
.queue-item{background:#171717;border:1px solid #222;border-radius:5px;padding:12px 16px;margin-bottom:10px;display:flex;align-items:center;justify-content:space-between}
.queue-info h4{font-size:14px;color:#ddd;margin-bottom:3px}
.queue-info span{font-size:12px;color:#666}

/* Toast */
#toast{position:fixed;bottom:24px;right:24px;background:#C9A96E;color:#111;padding:12px 20px;border-radius:4px;font-weight:bold;font-size:13px;display:none;z-index:200}
</style>
</head>
<body>

<header>
  <h1>WebByMaya — Outreach Console</h1>
  <div class="hdr-right">
    <span id="last-updated"></span>
    <button class="btn" onclick="location.reload()">↻ Refresh</button>
  </div>
</header>

<div class="main">
  <!-- Sidebar nav -->
  <div class="sidebar">
    <div class="nav-item active" onclick="showPage('warm')" id="nav-warm">
      Warm Leads <span class="badge-count red" id="badge-warm">0</span>
    </div>
    <div class="nav-item" onclick="showPage('responses')" id="nav-responses">
      Responses <span class="badge-count" id="badge-responses">0</span>
    </div>
    <div class="nav-item" onclick="showPage('queue')" id="nav-queue">
      Follow-up Queue <span class="badge-count" id="badge-queue">0</span>
    </div>
    <div class="nav-item" onclick="showPage('all-leads')" id="nav-all-leads">All Leads</div>
    <div class="nav-item" onclick="showPage('sms')" id="nav-sms">SMS Log</div>
    <div class="nav-item" onclick="showPage('email')" id="nav-email">Email Log</div>
    <div class="nav-item" onclick="showPage('bounces')" id="nav-bounces">Bounces</div>
  </div>

  <!-- Main content -->
  <div class="content" id="main-content">

    <!-- Stats cards (always visible) -->
    <div class="cards" id="stats-cards"></div>

    <!-- Warm Leads page -->
    <div id="page-warm">
      <p class="section-title">Warm Leads — took an action or replied</p>
      <div id="warm-list"></div>
    </div>

    <!-- Responses page -->
    <div id="page-responses" style="display:none">
      <p class="section-title">All Inbound Messages</p>
      <table>
        <thead><tr><th>Time</th><th>Type</th><th>Business</th><th>From</th><th>Message</th><th></th></tr></thead>
        <tbody id="responses-body"></tbody>
      </table>
    </div>

    <!-- Follow-up Queue page -->
    <div id="page-queue" style="display:none">
      <p class="section-title">Scheduled Follow-ups</p>
      <div id="queue-list"></div>
    </div>

    <!-- All Leads page -->
    <div id="page-all-leads" style="display:none">
      <div style="display:flex;align-items:center;gap:12px;margin-bottom:16px">
        <p class="section-title" style="margin:0">All Contacts</p>
        <input id="lead-search" type="text" placeholder="Search by name or category..."
          oninput="filterLeads()"
          style="background:#1a1a1a;border:1px solid #2a2a2a;color:#ddd;padding:6px 12px;border-radius:3px;font-size:13px;width:280px">
      </div>
      <table>
        <thead><tr><th>Business</th><th>Category</th><th>Status</th><th>SMS</th><th>Email</th><th>Replied</th><th>Last Contact</th><th></th></tr></thead>
        <tbody id="all-leads-body"></tbody>
      </table>
    </div>

    <!-- SMS Log page -->
    <div id="page-sms" style="display:none">
      <p class="section-title">SMS Send Log (most recent first)</p>
      <table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Phone</th><th>Status</th></tr></thead>
        <tbody id="sms-body"></tbody>
      </table>
    </div>

    <!-- Email Log page -->
    <div id="page-email" style="display:none">
      <div class="notice">
        Email replies go to <strong>mayas.worldwide.web@gmail.com</strong>.
        <a href="https://mail.google.com" target="_blank">Open Gmail →</a>
      </div>
      <p class="section-title">Email Send Log (most recent first)</p>
      <table>
        <thead><tr><th>Time</th><th>Business</th><th>Category</th><th>Email</th><th>Status</th></tr></thead>
        <tbody id="email-body"></tbody>
      </table>
    </div>

    <!-- Bounces page -->
    <div id="page-bounces" style="display:none">
      <p class="section-title">Bounce & Suppression List</p>
      <table>
        <thead><tr><th>Time</th><th>Email</th><th>Type</th><th>Reason</th></tr></thead>
        <tbody id="bounces-body"></tbody>
      </table>
    </div>

  </div><!-- /content -->
</div><!-- /main -->

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
let allLeadsData  = [];

function fmtTs(ts) {
  if (!ts) return '—';
  try {
    const d = new Date(ts);
    return d.toLocaleString('en-US', {month:'short',day:'numeric',hour:'numeric',minute:'2-digit',hour12:true});
  } catch { return ts.slice(0,16); }
}

function tag(text, color) {
  return `<span class="tag" style="background:${color}">${text}</span>`;
}

function statusTag(s) {
  const map = {warm:'#f39c12',booked:'#27ae60',contacted:'#3498db',opted_out:'#888',not_interested:'#c0392b'};
  return tag(s.replace('_',' '), map[s]||'#555');
}

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg; el.style.display = 'block';
  setTimeout(() => el.style.display = 'none', 3000);
}

// ── Stats cards ───────────────────────────────────────────────────────────────
function renderStats() {
  const s = DATA.stats;
  document.getElementById('stats-cards').innerHTML = `
    <div class="card"><div class="card-num orange">${s.warm}</div><div class="card-label">Warm Leads</div></div>
    <div class="card"><div class="card-num">${s.total_sms}</div><div class="card-label">SMS Sent</div></div>
    <div class="card"><div class="card-num">${s.total_email}</div><div class="card-label">Emails Sent</div></div>
    <div class="card"><div class="card-num green">${s.replies}</div><div class="card-label">Replies</div></div>
    <div class="card"><div class="card-num">${s.opens}</div><div class="card-label">Email Opens</div></div>
    <div class="card"><div class="card-num">${s.clicks}</div><div class="card-label">Link Clicks</div></div>
    <div class="card"><div class="card-num red">${s.opt_outs}</div><div class="card-label">Opt-Outs</div></div>
    <div class="card"><div class="card-num red">${s.bounces}</div><div class="card-label">Bounces</div></div>
  `;
  document.getElementById('badge-warm').textContent = s.warm;
  document.getElementById('badge-responses').textContent = DATA.real_replies.length + DATA.opt_outs.length + DATA.auto_replies.length;
  document.getElementById('badge-queue').textContent = DATA.queue.filter(q=>q.sent==='no').length;
  document.getElementById('last-updated').textContent = 'Updated ' + new Date().toLocaleTimeString('en-US',{hour:'numeric',minute:'2-digit'});
}

// ── Warm Leads ─────────────────────────────────────────────────────────────────
function renderWarm() {
  const el = document.getElementById('warm-list');
  if (!DATA.warm.length) { el.innerHTML = '<p class="empty">No warm leads yet. Keep sending!</p>'; return; }
  el.innerHTML = DATA.warm.map(l => `
    <div class="queue-item" onclick="openPanel('${l.phone}')" style="cursor:pointer">
      <div class="queue-info">
        <h4>${l.name} <span style="font-weight:normal;color:#888;font-size:12px">${l.category}</span></h4>
        <span>${l.phone} &nbsp;·&nbsp; ${l.sms_sent} SMS · ${l.email_sent} emails · ${l.touches.length} total touches</span>
      </div>
      <div style="display:flex;gap:8px;flex-shrink:0">
        <button class="btn btn-sm btn-green" onclick="event.stopPropagation();sendFollowup('${l.phone}','${esc(l.name)}')">Follow-up SMS</button>
        <button class="btn btn-sm" onclick="event.stopPropagation();openPanel('${l.phone}')">View →</button>
      </div>
    </div>`).join('');
}

// ── Responses ─────────────────────────────────────────────────────────────────
function renderResponses() {
  const tbody = document.getElementById('responses-body');
  const all = [
    ...DATA.real_replies.map(m=>({...m,kind:'real'})),
    ...DATA.opt_outs.map(m=>({...m,kind:'stop'})),
    ...DATA.auto_replies.map(m=>({...m,kind:'auto'})),
  ];
  if (!all.length) { tbody.innerHTML = '<tr><td colspan="6" class="empty">No responses yet.</td></tr>'; return; }
  tbody.innerHTML = all.map(m => {
    const lead = DATA.leads.find(l=>l.phone===m.from)||{};
    const color = m.kind==='real'?'#f39c12':m.kind==='stop'?'#888':'#555';
    return `<tr class="clickable" onclick="openPanel('${m.from}')">
      <td style="white-space:nowrap">${fmtTs(m.date_sent)}</td>
      <td>${tag(m.kind.toUpperCase(),color)}</td>
      <td><strong>${lead.name||'Unknown'}</strong><br><span style="color:#666;font-size:11px">${lead.category||''}</span></td>
      <td style="color:#888;font-size:12px">${m.from}</td>
      <td style="font-size:13px">${(m.body||'').slice(0,100)}</td>
      <td><button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${m.from}')">View</button></td>
    </tr>`;
  }).join('');
}

// ── Follow-up Queue ────────────────────────────────────────────────────────────
function renderQueue() {
  const el = document.getElementById('queue-list');
  const pending = DATA.queue.filter(q=>q.sent==='no');
  if (!pending.length) { el.innerHTML = '<p class="empty">No follow-ups queued. Reply contacts will appear here.</p>'; return; }
  el.innerHTML = pending.map(q => `
    <div class="queue-item">
      <div class="queue-info">
        <h4 style="cursor:pointer" onclick="openPanel('${q.phone}')">${q.name} <span style="font-weight:normal;color:#888;font-size:12px">${q.category}</span></h4>
        <span>Send after: ${q.send_after} &nbsp;·&nbsp; ${q.reason}</span>
      </div>
      <div style="display:flex;gap:8px">
        <button class="btn btn-sm btn-green" onclick="sendFollowupNow('${q.phone}','${esc(q.name)}')">Send Now</button>
      </div>
    </div>`).join('');
}

// ── All Leads ──────────────────────────────────────────────────────────────────
function renderAllLeads(leads) {
  leads = leads || DATA.leads;
  allLeadsData = leads;
  const tbody = document.getElementById('all-leads-body');
  if (!leads.length) { tbody.innerHTML = '<tr><td colspan="8" class="empty">No leads yet.</td></tr>'; return; }
  const sorted = [...leads].sort((a,b)=>(b.sms_sent+b.email_sent)-(a.sms_sent+a.email_sent));
  tbody.innerHTML = sorted.slice(0,200).map(l => `
    <tr class="clickable" onclick="openPanel('${l.phone}')">
      <td><strong>${l.name}</strong></td>
      <td style="color:#888">${l.category}</td>
      <td>${statusTag(l.status||'contacted')}</td>
      <td style="text-align:center">${l.sms_sent}</td>
      <td style="text-align:center">${l.email_sent}</td>
      <td>${l.replied?'<span style="color:#2ecc71">✓</span>':'—'}</td>
      <td style="color:#888;font-size:12px">${fmtTs(l.last_contact)}</td>
      <td><button class="btn btn-sm btn-outline" onclick="event.stopPropagation();openPanel('${l.phone}')">View</button></td>
    </tr>`).join('');
}

function filterLeads() {
  const q = document.getElementById('lead-search').value.toLowerCase();
  const filtered = DATA.leads.filter(l=>
    l.name.toLowerCase().includes(q) || (l.category||'').toLowerCase().includes(q)
  );
  renderAllLeads(filtered);
}

// ── SMS / Email / Bounces logs ─────────────────────────────────────────────────
function renderSmsLog() {
  const tbody = document.getElementById('sms-body');
  const rows = [...DATA.sms_logs].reverse().slice(0,300);
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
  const tbody = document.getElementById('email-body');
  const rows = [...DATA.send_logs].reverse().slice(0,300);
  const suppressed = new Set(DATA.suppressed);
  if (!rows.length) { tbody.innerHTML = '<tr><td colspan="5" class="empty">No email logs.</td></tr>'; return; }
  tbody.innerHTML = rows.map(r => {
    const bc = r.status==='sent'?'#2ecc71':r.status==='bounced'||r.status==='failed'?'#e74c3c':'#888';
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
  const lead = DATA.leads.find(l=>l.phone===phone);
  if (!lead) return;
  currentPhone = phone;
  _renderPanel(lead);
}

function openPanelByName(name) {
  const lead = DATA.leads.find(l=>l.name.toLowerCase()===name.toLowerCase());
  if (!lead) return;
  currentPhone = lead.phone;
  _renderPanel(lead);
}

function _renderPanel(lead) {
  document.getElementById('panel-name').textContent     = lead.name;
  document.getElementById('panel-category').textContent = lead.category + (lead.rating ? '  ★ '+lead.rating : '');

  const touchDotColors = {sms_out:'#3498db',email_out:'#C9A96E',sms_in:'#2ecc71'};
  const touchLabels    = {sms_out:'SMS Sent',email_out:'Email Sent',sms_in:'SMS Reply'};

  const touchHtml = (lead.touches||[]).map(t => `
    <div class="touch-item">
      <div class="touch-dot" style="background:${touchDotColors[t.type]||'#555'}"></div>
      <div>
        <div style="font-size:13px;color:#ccc">${touchLabels[t.type]||t.type}</div>
        <div class="touch-meta">${fmtTs(t.ts)} &nbsp;·&nbsp; ${t.note||''}</div>
      </div>
    </div>`).join('') || '<p style="color:#555;font-size:13px">No touchpoints yet.</p>';

  const mapsLink = lead.maps_url
    ? `<a href="${lead.maps_url}" target="_blank" style="font-size:12px">Open in Google Maps →</a>`
    : (lead.address ? `<a href="https://maps.google.com?q=${encodeURIComponent(lead.address)}" target="_blank" style="font-size:12px">Open in Google Maps →</a>` : '');

  document.getElementById('panel-body').innerHTML = `
    <div class="panel-section">
      <div class="panel-section-title">Contact Info</div>
      <div class="info-grid">
        <span class="info-label">Phone</span>
        <span class="info-val"><a href="tel:${lead.phone}">${lead.phone}</a></span>
        <span class="info-label">Category</span>
        <span class="info-val">${lead.category||'—'}</span>
        <span class="info-label">Address</span>
        <span class="info-val">${lead.address||'—'}</span>
        ${lead.rating ? `<span class="info-label">Rating</span><span class="info-val">★ ${lead.rating} (${lead.reviews||'?'} reviews)</span>` : ''}
        <span class="info-label">Status</span>
        <span class="info-val">${statusTag(lead.status||'contacted')}</span>
      </div>
      ${mapsLink ? '<div style="margin-top:10px">'+mapsLink+'</div>' : ''}
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Outreach Summary</div>
      <div class="info-grid">
        <span class="info-label">SMS Sent</span><span class="info-val">${lead.sms_sent}</span>
        <span class="info-label">Emails Sent</span><span class="info-val">${lead.email_sent}</span>
        <span class="info-label">Replied</span><span class="info-val">${lead.replied?'<span style="color:#2ecc71">Yes</span>':'No'}</span>
        <span class="info-label">Last Contact</span><span class="info-val">${fmtTs(lead.last_contact)}</span>
      </div>
    </div>
    <div class="panel-section">
      <div class="panel-section-title">Activity Timeline</div>
      ${touchHtml}
    </div>`;

  document.getElementById('panel-actions').innerHTML = `
    <button class="btn btn-sm btn-green" onclick="sendFollowup('${lead.phone}','${esc(lead.name)}')">Send Follow-up SMS</button>
    <button class="btn btn-sm btn-green" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${lead.category}','booked')">Mark Booked ✓</button>
    <button class="btn btn-sm btn-outline" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${lead.category}','warm')">Mark Warm</button>
    <button class="btn btn-sm btn-danger" onclick="markStatus('${lead.phone}','${esc(lead.name)}','${lead.category}','not_interested')">Not Interested</button>
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
  fetch('/action/send-followup', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone, name})
  }).then(r=>r.json()).then(d => {
    if (d.ok) toast('Follow-up sent to ' + name + '!');
    else toast('Error: ' + (d.error||'unknown'));
  });
}

function sendFollowupNow(phone, name) { sendFollowup(phone, name); }

function markStatus(phone, name, category, status) {
  fetch('/action/mark-status', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body: JSON.stringify({phone, name, category, status})
  }).then(r=>r.json()).then(d => {
    if (d.ok) { toast('Marked as ' + status.replace('_',' ')); setTimeout(()=>location.reload(),1500); }
    else toast('Error: ' + (d.error||'unknown'));
  });
}

// ── Nav ────────────────────────────────────────────────────────────────────────
function showPage(name) {
  document.querySelectorAll('[id^="page-"]').forEach(el=>el.style.display='none');
  document.querySelectorAll('.nav-item').forEach(el=>el.classList.remove('active'));
  document.getElementById('page-'+name).style.display='block';
  document.getElementById('nav-'+name).classList.add('active');
}

function esc(s) { return (s||'').replace(/'/g,"\\'").replace(/"/g,'&quot;'); }

// ── Init ───────────────────────────────────────────────────────────────────────
renderStats();
renderWarm();
renderResponses();
renderQueue();
renderAllLeads();
renderSmsLog();
renderEmailLog();
renderBounces();
</script>
</body></html>"""

# ── HTTP handlers ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        os.chdir(SCRIPT_DIR)
        data = build_dataset()
        data_json = json.dumps(data, default=str)
        html = HTML.replace('__DATA__', data_json)
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
                # Log to sms log
                today = datetime.now().strftime("%Y-%m-%d")
                log_path = SCRIPT_DIR / f"sms_log_{today}.csv"
                exists = log_path.exists()
                with open(log_path, "a", newline="") as f:
                    w = csv.DictWriter(f, fieldnames=["timestamp","name","phone","category","carrier_type","status","notes"])
                    if not exists: w.writeheader()
                    w.writerow({"timestamp": datetime.now().isoformat(timespec="seconds"),
                                "name": name, "phone": phone, "category": "follow-up",
                                "carrier_type": "", "status": "sent", "notes": "manual follow-up"})
                self._respond(200,"application/json", json.dumps({"ok":True,"sid":sid}).encode())
            else:
                self._respond(200,"application/json", json.dumps({"ok":False,"error":err}).encode())

        elif self.path == "/action/mark-status":
            phone    = body.get("phone","")
            name     = body.get("name","")
            category = body.get("category","")
            status   = body.get("status","")
            save_status(phone, name, category, status)
            self._respond(200,"application/json", json.dumps({"ok":True}).encode())

        else:
            self._respond(404,"text/plain", b"Not found")

    def _respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass

if __name__ == "__main__":
    os.chdir(SCRIPT_DIR)
    print(f"\n  WebByMaya Outreach Console")
    print(f"  Open: http://localhost:{PORT}\n")
    HTTPServer(("", PORT), Handler).serve_forever()
