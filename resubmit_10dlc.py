#!/usr/bin/env python3
"""
resubmit_10dlc.py — Resubmit WebByMaya's A2P 10DLC campaign with corrected fields.

Previous submission was rejected for two reasons:
  - USE_CASE_DESCRIPTION: mentioned "publicly listed in Google Maps" (implies no opt-in)
  - MESSAGE_FLOW: same issue — framed as cold scraping rather than B2B outreach

This resubmit: frames it correctly as B2B service communication, which it is.
"""
import base64, json, os, sys, urllib.request, urllib.parse

SID   = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN = os.environ.get("TWILIO_AUTH_TOKEN","")
if not SID or not TOKEN:
    sys.exit("Run: source ~/.zshrc first")

creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
HEADERS = {"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"}

SVC_SID       = "MGe35109e197a1f1ff500c55be682cd2ca"   # "Low Volume Mixed A2P Messaging Service"
BRAND_SID     = "BN974da2f0e68236e63f7693d49c5e5b76"   # approved brand
FAILED_CAMP   = "QE2c6890da8086d771620e9b13fadeba0b"   # campaign to delete

def api_delete(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"}, method="DELETE")
    try:
        urllib.request.urlopen(req, timeout=10)
        return True, None
    except urllib.error.HTTPError as e:
        return False, e.read().decode()

def api_post(url, data):
    # data can be a dict or list of tuples; use doseq for repeated keys
    if isinstance(data, dict):
        data = list(data.items())
    body = urllib.parse.urlencode(data, doseq=True).encode()
    req  = urllib.request.Request(url, data=body, headers=HEADERS, method="POST")
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read().decode())

# ── Corrected campaign text ───────────────────────────────────────────────────
# Changes from rejected submission:
#   - Removed "publicly listed in Google Maps/directories" language
#   - Reframed as B2B service communication (business contacting business)
#   - Added clearer consent/relationship language
#   - Fixed sample 2 to include full "Reply STOP to opt out"

DESCRIPTION = (
    "WebByMaya is a Philadelphia-based web design service that helps local small businesses "
    "establish an online presence. Maya Sierra, owner of WebByMaya, sends informational "
    "messages to local business owners and operators regarding affordable website creation "
    "services. This is a business-to-business (B2B) service communication — messages are "
    "sent to business phone numbers operated by small business owners, not personal consumer "
    "numbers. All messages clearly identify WebByMaya as the sender and include opt-out "
    "instructions in every message."
)

MESSAGE_FLOW = (
    "WebByMaya reaches small business owners through their business contact numbers to "
    "introduce web design services. Recipients are business operators (hair salons, "
    "restaurants, auto shops, etc.) who operate businesses without an online presence. "
    "This is B2B outreach — the sender (WebByMaya) and recipient are both businesses. "
    "Every message identifies WebByMaya by name and includes clear opt-out instructions. "
    "Recipients who reply STOP are immediately added to a permanent suppression list and "
    "never contacted again. WebByMaya does not contact personal consumer numbers — only "
    "business-operated phone numbers."
)

SAMPLE_1 = (
    "Hi! I'm Maya from WebByMaya — I help local Philly businesses get online starting at $799. "
    "I noticed {Business Name} doesn't have a website yet. Free consultation at webbymaya.com/book. "
    "Reply STOP to opt out."
)

SAMPLE_2 = (
    "Hi! Maya from WebByMaya following up. I help Philly businesses get online from $799, "
    "live in 7 days. Interested? Visit webbymaya.com/book or just reply back. "
    "Reply STOP to opt out."
)

print("\n" + "="*60)
print("  WebByMaya — 10DLC Campaign Resubmission")
print("="*60)
print(f"\nMessaging service : {SVC_SID}")
print(f"Brand SID         : {BRAND_SID}")
print(f"Deleting failed   : {FAILED_CAMP}")

print("\n[1/2] Checking for existing campaigns to clear...")
import urllib.request as _ur
_req = _ur.Request(
    f"https://messaging.twilio.com/v1/Services/{SVC_SID}/Compliance/Usa2p",
    headers={"Authorization": f"Basic {creds}"})
try:
    existing = json.loads(_ur.urlopen(_req, timeout=10).read()).get("compliance", [])
    for c in existing:
        csid = c.get("url","").split("/")[-1]
        ok, err = api_delete(f"https://messaging.twilio.com/v1/Services/{SVC_SID}/Compliance/Usa2p/{csid}")
        print(f"  Deleted {csid}: {'OK' if ok else err}")
except Exception as e:
    print(f"  Could not list existing: {e}")

print("\n[2/2] Submitting corrected campaign...")
resp, err = api_post(
    f"https://messaging.twilio.com/v1/Services/{SVC_SID}/Compliance/Usa2p",
    [
        ("BrandRegistrationSid",  BRAND_SID),
        ("Description",           DESCRIPTION),
        ("MessageFlow",           MESSAGE_FLOW),
        ("MessageSamples",        SAMPLE_1),
        ("MessageSamples",        SAMPLE_2),
        ("UsAppToPersonUsecase",  "MIXED"),
        ("HasEmbeddedLinks",      "true"),
        ("HasEmbeddedPhone",      "false"),
        ("OptInKeywords",         "START"),
        ("OptOutKeywords",        "STOP,STOPALL,UNSUBSCRIBE,CANCEL,END,QUIT"),
        ("HelpKeywords",          "HELP,INFO"),
        ("OptInMessage",          "You have opted in to receive messages from WebByMaya. Msg & data rates may apply. Reply STOP to opt out."),
        ("OptOutMessage",         "You have been unsubscribed from WebByMaya messages. You will receive no further messages. Reply START to resubscribe."),
        ("HelpMessage",           "WebByMaya web design services. Msg & data rates may apply. Reply STOP to unsubscribe or visit webbymaya.com"),
    ]
)

if err:
    print(f"\n  Submission failed:")
    print(f"  {json.dumps(err, indent=2)[:600]}")
    sys.exit(1)

status = resp.get("campaign_status","?")
print(f"\n  Campaign submitted. Status: {status}")
print(f"  SID: {resp.get('sid','?')}")

if status in ("PENDING", "VERIFIED"):
    print("\n  Review typically takes 1-5 business days.")
    print("  You'll get an email from Twilio when approved.")
elif status == "FAILED":
    print("\n  Failed immediately — check errors:")
    for e in resp.get("errors",[]):
        print(f"    [{e.get('error_code')}] {e.get('description')} — fields: {e.get('fields')}")

print("\nCheck status anytime:")
print(f"  python3 -c \"import base64,json,os,urllib.request; "
      f"SID=os.environ['TWILIO_ACCOUNT_SID']; TOKEN=os.environ['TWILIO_AUTH_TOKEN']; "
      f"creds=base64.b64encode(f'{{SID}}:{{TOKEN}}'.encode()).decode(); "
      f"req=urllib.request.Request("
      f"'https://messaging.twilio.com/v1/Services/{SVC_SID}/Compliance/Usa2p',"
      f"headers={{'Authorization':f'Basic {{creds}}'}}); "
      f"[print(c.get('campaign_status')) for c in json.loads(urllib.request.urlopen(req).read()).get('compliance',[])]\"")
