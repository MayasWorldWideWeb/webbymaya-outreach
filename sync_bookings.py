#!/usr/bin/env python3
"""
sync_bookings.py — Pulls new bookings from Supabase client_meetings
and marks matching leads as 'booked' in lead_status.csv.

Runs daily via run_daily.sh. Safe to re-run — skips already-booked leads.
"""
import csv, json, os, subprocess, urllib.request, urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
STATUS_CSV  = SCRIPT_DIR / "lead_status.csv"
MY_NUMBER   = "+12154602084"
TWILIO_PHONE = os.environ.get("TWILIO_PHONE_NUMBER","")
SID          = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN        = os.environ.get("TWILIO_AUTH_TOKEN","")

SUPA_URL     = "https://pvzwngrgymjezkcevkce.supabase.co"
SUPA_KEY     = os.environ.get("SUPABASE_WBM_SERVICE_KEY", "")


def supa_get(table, params=""):
    if not SUPA_KEY:
        print("[sync_bookings] SUPABASE_WBM_SERVICE_KEY not set — skipping.")
        print("  Get it from: supabase.com/dashboard/project/pvzwngrgymjezkcevkce/settings/api")
        print("  Then: echo 'export SUPABASE_WBM_SERVICE_KEY=\"your_key\"' >> ~/.zshrc")
        return []
    url = f"{SUPA_URL}/rest/v1/{table}?{params}"
    req = urllib.request.Request(url, headers={
        "apikey": SUPA_KEY,
        "Authorization": f"Bearer {SUPA_KEY}",
        "Accept": "application/json",
    })
    try:
        return json.loads(urllib.request.urlopen(req, timeout=10).read())
    except Exception as e:
        print(f"[sync_bookings] Supabase error: {e}")
        return []


def load_status() -> list[dict]:
    if not STATUS_CSV.exists():
        return []
    with open(STATUS_CSV, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save_status(rows: list[dict]):
    if not rows:
        return
    fields = list(rows[0].keys())
    with open(STATUS_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def load_send_logs() -> dict[str, str]:
    """email → name map from send logs."""
    out = {}
    for p in sorted(SCRIPT_DIR.glob("send_log_*.csv")):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                e = row.get("email_sent_to","").strip().lower()
                n = row.get("name","").strip()
                if e and n and e not in out:
                    out[e] = n
    return out


def mac_notify(title, body):
    try:
        subprocess.run(["osascript", "-e",
            f'display notification "{body}" with title "{title}" sound name "Glass"'],
            timeout=5)
    except Exception:
        pass


def sms_self(msg):
    if not SID or not TOKEN or not TWILIO_PHONE:
        return
    import base64
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    data  = urllib.parse.urlencode({"To": MY_NUMBER, "From": TWILIO_PHONE, "Body": msg}).encode()
    req   = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
        data=data,
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"},
        method="POST")
    try:
        urllib.request.urlopen(req, timeout=8)
    except Exception:
        pass


def main():
    # Fetch bookings from last 30 days
    since = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    bookings = supa_get("client_meetings",
        f"status=neq.cancelled&starts_at=gte.{urllib.parse.quote(since)}"
        "&select=client_name,client_email,starts_at,status,notes"
        "&order=starts_at.asc")

    if not bookings:
        print("[sync_bookings] No bookings found.")
        return

    print(f"[sync_bookings] Found {len(bookings)} booking(s) in Supabase.")

    email_to_name = load_send_logs()
    rows          = load_status()
    email_index   = {r.get("name","").strip().lower(): i for i, r in enumerate(rows)}
    phone_index   = {r.get("phone","").strip(): i for i, r in enumerate(rows)}

    updated = 0
    for b in bookings:
        email = (b.get("client_email","") or "").strip().lower()
        name  = (b.get("client_name","") or email_to_name.get(email,"")).strip()
        if not email and not name:
            continue

        starts = b.get("starts_at","")[:16].replace("T"," ")
        note   = f"Booked call: {starts}"

        # Try to find the lead by name (most reliable since we have name from send logs)
        idx = email_index.get(name.lower())
        if idx is None and email in email_to_name:
            idx = email_index.get(email_to_name[email].lower())

        if idx is not None:
            lead = rows[idx]
            if lead.get("status") not in ("booked","won"):
                rows[idx]["status"]  = "booked"
                rows[idx]["note"]    = note
                rows[idx]["updated"] = datetime.now().isoformat(timespec="seconds")
                print(f"  Marked booked: {lead['name']} ({email}) — {starts}")
                updated += 1
                mac_notify("WebByMaya — New Booking!", f"{name} booked a call for {starts}")
                sms_self(f"New booking: {name} ({email})\nCall: {starts}\nCheck dashboard.")
        else:
            # Lead not in status CSV yet — add them
            if name or email:
                rows.append({
                    "phone":    email,
                    "name":     name,
                    "category": "booking",
                    "status":   "booked",
                    "note":     note,
                    "updated":  datetime.now().isoformat(timespec="seconds"),
                })
                print(f"  New lead from booking: {name} ({email}) — {starts}")
                updated += 1
                mac_notify("WebByMaya — New Booking!", f"{name} booked a call for {starts}")
                sms_self(f"New booking: {name} ({email})\nCall: {starts}\nCheck dashboard.")

    if updated:
        save_status(rows)
        print(f"[sync_bookings] {updated} lead(s) updated.")
    else:
        print(f"[sync_bookings] All bookings already synced.")


if __name__ == "__main__":
    main()
