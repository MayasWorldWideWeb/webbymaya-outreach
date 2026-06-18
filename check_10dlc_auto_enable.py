#!/usr/bin/env python3
"""
check_10dlc_auto_enable.py — Watches toll-free verification; enables SMS when approved.

Polls the toll-free verification status every morning.
When TWILIO approves it (usually 5–10 business days), this script:
  1. Switches the outreach sender to the toll-free number (+18338383313)
  2. Enables SMS in run_daily.sh (removes --sms-limit 0)
  3. Fires a Mac notification + self-text so you know immediately
"""
import base64, json, os, subprocess, urllib.request, urllib.parse
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
RUN_DAILY   = SCRIPT_DIR / "run_daily.sh"

SID          = os.environ.get("TWILIO_ACCOUNT_SID", "")
TOKEN        = os.environ.get("TWILIO_AUTH_TOKEN", "")
MY_NUMBER    = "+12154602084"

TF_NUMBER    = "+18338383313"
TF_VERIFY_SID = "HH6c4e4cc29c8e87a8d14eef69c21df282"

if not SID or not TOKEN:
    print("[tf-check] No Twilio creds — skipping"); exit(0)

content = RUN_DAILY.read_text()
if "--sms-limit 0" not in content:
    print("[tf-check] SMS already enabled in run_daily.sh — nothing to do"); exit(0)

# ── Check toll-free verification status ──────────────────────────────────────
creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
req   = urllib.request.Request(
    f"https://messaging.twilio.com/v1/Tollfree/Verifications/{TF_VERIFY_SID}",
    headers={"Authorization": f"Basic {creds}"})

try:
    data   = json.loads(urllib.request.urlopen(req, timeout=10).read())
    status = data.get("status", "UNKNOWN")
except Exception as e:
    print(f"[tf-check] API error: {e}"); exit(0)

print(f"[tf-check] Toll-free verification status: {status}")

if status not in ("APPROVED", "TWILIO_APPROVED"):
    print(f"[tf-check] Not approved yet ({status}) — SMS stays disabled."); exit(0)

# ── APPROVED — switch sender to toll-free and enable SMS ─────────────────────
print(f"[tf-check] TOLL-FREE APPROVED! Enabling SMS in run_daily.sh...")

new_content = content.replace("--sms-limit 0", "--sms-limit 50")
if new_content == content:
    print("[tf-check] Could not find --sms-limit 0 to replace"); exit(1)

# Point the cron export at the toll-free number
new_content = new_content.replace(
    'export TWILIO_PHONE_NUMBER="$(grep TWILIO_PHONE_NUMBER',
    'export TWILIO_PHONE_NUMBER="$(grep TWILIO_TF_NUMBER',
)

RUN_DAILY.write_text(new_content)
print(f"[tf-check] run_daily.sh updated — SMS via {TF_NUMBER} enabled.")

# ── Mac notification ──────────────────────────────────────────────────────────
try:
    subprocess.run(["osascript", "-e",
        f'display notification "Toll-free {TF_NUMBER} approved — SMS outreach is LIVE!" '
        'with title "WebByMaya" sound name "Glass"'], timeout=5)
except Exception:
    pass

# ── Self-text ─────────────────────────────────────────────────────────────────
try:
    body = urllib.parse.urlencode({
        "To": MY_NUMBER, "From": TF_NUMBER,
        "Body": f"WebByMaya: Your toll-free number {TF_NUMBER} was APPROVED. SMS outreach is now live!"
    }).encode()
    req2 = urllib.request.Request(
        f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json",
        data=body, method="POST",
        headers={"Authorization": f"Basic {creds}",
                 "Content-Type": "application/x-www-form-urlencoded"})
    urllib.request.urlopen(req2, timeout=8)
    print("[tf-check] Self-text sent.")
except Exception as e:
    print(f"[tf-check] Self-text failed (number not yet active): {e}")
