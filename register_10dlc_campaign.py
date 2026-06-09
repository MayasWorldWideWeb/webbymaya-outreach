#!/usr/bin/env python3
"""
register_10dlc_campaign.py — Register the outreach campaign after brand is APPROVED.
Run this after register_10dlc.py and once brand status = APPROVED.
"""
import base64, json, os, sys, urllib.request, urllib.parse

SID   = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN = os.environ.get("TWILIO_AUTH_TOKEN","")
creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
auth  = {"Authorization": f"Basic {creds}", "Content-Type": "application/x-www-form-urlencoded"}

def post(url, data):
    body = urllib.parse.urlencode(data).encode()
    req  = urllib.request.Request(url, data=body, headers=auth, method="POST")
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return json.loads(resp.read()), None
    except urllib.error.HTTPError as e:
        return None, json.loads(e.read().decode())

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {creds}"})
    return json.loads(urllib.request.urlopen(req, timeout=10).read())

# Load saved SIDs
brand_sid_file = "/tmp/webbymaya_brand_sid.txt"
svc_sid_file   = "/tmp/webbymaya_svc_sid.txt"

if not os.path.exists(brand_sid_file):
    sys.exit("Run register_10dlc.py first to get your Brand SID.")

brand_sid = open(brand_sid_file).read().strip()
svc_sid   = open(svc_sid_file).read().strip() if os.path.exists(svc_sid_file) else ""

# Check brand status
print(f"Checking brand {brand_sid} status...")
brand = get(f"https://messaging.twilio.com/v1/a2p/BrandRegistrations/{brand_sid}")
status = brand.get("status","")
print(f"Brand status: {status}")

if status != "APPROVED":
    print(f"\nBrand not yet approved (status: {status}).")
    print("Check back in a few hours. Re-run this script when status = APPROVED.")
    sys.exit(0)

# Register campaign
print("\nRegistering campaign...")
campaign_data = {
    "BrandRegistrationSid": brand_sid,
    "MessagingServiceSid":  svc_sid,
    "Description": (
        "WebByMaya sends outreach messages to local businesses that don't have "
        "a website, offering affordable web design services. Recipients can reply "
        "STOP to opt out at any time."
    ),
    "MessageSamples": json.dumps([
        "Hi! I noticed [Business Name] doesn't have a website yet. I'm Maya, a web designer "
        "based in Philly. I build affordable sites for local businesses. Free 20-min call: "
        "https://webbymaya.com/book Reply STOP to opt out.",
        "Hi! This is Maya from WebByMaya following up. I'd love to chat about getting "
        "[Business Name] online this week. Free call: https://webbymaya.com/book "
        "Reply STOP to opt out."
    ]),
    "UsAppToPersonUsecase": "MIXED",
    "HasEmbeddedLinks":     True,
    "HasEmbeddedPhone":     False,
    "OptInMessage": (
        "You are now opted in to receive messages from WebByMaya. "
        "Reply STOP to opt out at any time."
    ),
    "OptOutMessage": (
        "You have been unsubscribed from WebByMaya messages. "
        "You will receive no more messages."
    ),
    "HelpMessage": (
        "WebByMaya — web design for local businesses. "
        "Reply STOP to opt out. Contact: mayas.worldwide.web@gmail.com"
    ),
    "OptInKeywords":  "START",
    "OptOutKeywords": "STOP STOPALL UNSUBSCRIBE CANCEL END QUIT",
    "HelpKeywords":   "HELP INFO",
}
resp, err = post("https://messaging.twilio.com/v1/a2p/UsAppToPerson", campaign_data)
if err:
    print(f"Campaign error: {err}")
    sys.exit(1)

campaign_sid = resp["sid"]
print(f"Campaign SID: {campaign_sid}")
print(f"Status: {resp.get('campaign_status','')}")
print("\n10DLC registration complete. Your messages will now bypass carrier filtering.")
print("Full throughput active within 24-48 hours of campaign approval.")
