"""
sb.py — Supabase writer for WebByMaya scripts
Import this in any script: from sb import sb_insert, sb_upsert
Fails silently so CSV writes always remain the fallback.
"""
import json, os, urllib.request, urllib.parse, urllib.error
from datetime import datetime

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
ANON_KEY     = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"

_HEADERS = {
    "apikey":        ANON_KEY,
    "Authorization": f"Bearer {ANON_KEY}",
    "Content-Type":  "application/json",
    "Prefer":        "resolution=ignore-duplicates,return=minimal",
}

def _post(table, rows, upsert=False):
    if not rows: return
    headers = dict(_HEADERS)
    if upsert:
        headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
    url  = f"{SUPABASE_URL}/rest/v1/{table}"
    data = json.dumps(rows if isinstance(rows, list) else [rows]).encode()
    req  = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        urllib.request.urlopen(req, timeout=10)
    except Exception:
        pass  # never crash the caller

def sb_insert(table, rows):
    _post(table, rows, upsert=False)

def sb_upsert(table, rows):
    _post(table, rows, upsert=True)

# ── Convenience helpers used by each script ──────────────────────────────────

def log_sms(rows):
    """rows: list of dicts from sms_log CSV"""
    records = []
    for r in rows:
        records.append({
            "sent_at":      r.get("timestamp") or None,
            "name":         r.get("name") or None,
            "phone":        r.get("phone") or None,
            "category":     r.get("category") or None,
            "carrier_type": r.get("carrier_type") or None,
            "status":       r.get("status") or None,
            "notes":        r.get("notes") or None,
        })
    sb_insert("sms_log", records)

def log_email(rows):
    """rows: list of dicts from send_log CSV"""
    records = []
    for r in rows:
        records.append({
            "sent_at":       r.get("timestamp") or None,
            "name":          r.get("name") or None,
            "category":      r.get("category") or None,
            "email_sent_to": r.get("email_sent_to") or None,
            "subject":       r.get("subject") or None,
            "status":        r.get("status") or None,
            "notes":         r.get("notes") or None,
        })
    sb_insert("email_log", records)

def log_prospects(rows):
    """rows: list of prospect dicts from find_prospects CSV"""
    records = []
    for r in rows:
        records.append({
            "name":           (r.get("name") or "").strip() or None,
            "phone":          (r.get("phone") or "").strip() or None,
            "email":          (r.get("email") or "").strip() or None,
            "address":        (r.get("address") or "").strip() or None,
            "city":           (r.get("city") or "").strip() or None,
            "category":       (r.get("category") or "").strip() or None,
            "place_id":       (r.get("place_id") or "").strip() or None,
            "maps_url":       (r.get("maps_url") or "").strip() or None,
            "website":        (r.get("website") or "").strip() or None,
            "website_status": (r.get("website_status") or "").strip() or None,
            "has_website":    (r.get("has_website") or "").strip() or None,
            "rating":         float(r["rating"]) if str(r.get("rating","")).strip() else None,
            "review_count":   int(r["review_count"]) if str(r.get("review_count","")).strip() else None,
            "notes":          (r.get("notes") or "").strip() or None,
            "sms_status":     (r.get("sms_status") or "").strip() or None,
        })
    sb_upsert("prospects", records)

def log_bounce(email, bounce_type, reason):
    sb_upsert("bounce_log", [{
        "email":       email.lower().strip(),
        "type":        bounce_type,
        "reason":      (reason or "")[:500],
        "bounced_at":  datetime.utcnow().isoformat() + "Z",
    }])

def set_lead_status(phone, name, category, status, note=""):
    sb_upsert("lead_status", [{
        "phone":      phone,
        "name":       name,
        "category":   category,
        "status":     status,
        "note":       note,
        "updated_at": datetime.utcnow().isoformat() + "Z",
    }])

def queue_followup(phone, name, category, send_after, reason):
    sb_insert("followup_queue", [{
        "phone":      phone,
        "name":       name,
        "category":   category,
        "send_after": send_after,
        "reason":     reason,
        "sent":       False,
        "queued_at":  datetime.utcnow().isoformat() + "Z",
    }])

def log_inbound(twilio_sid, from_number, body, received_at, kind):
    sb_upsert("inbound_sms", [{
        "twilio_sid":   twilio_sid,
        "from_number":  from_number,
        "body":         body,
        "received_at":  received_at,
        "kind":         kind,
        "notified":     False,
    }])
