#!/usr/bin/env python3
"""
register_10dlc.py — WebByMaya 10DLC Brand + Campaign Registration
Run this once to register with The Campaign Registry via Twilio.

You'll be prompted for sensitive info (EIN or SSN last 4).
Nothing is stored — it's sent directly to Twilio's API.

Cost: ~$4 one-time brand fee + $10/month campaign fee (billed by Twilio).
"""
import base64, json, os, sys, urllib.request, urllib.parse

SID   = os.environ.get("TWILIO_ACCOUNT_SID","")
TOKEN = os.environ.get("TWILIO_AUTH_TOKEN","")

if not SID or not TOKEN:
    sys.exit("Run: source ~/.zshrc first")

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

print("\n" + "="*60)
print("  WebByMaya — 10DLC Registration")
print("="*60)
print("\nThis registers your business with carriers so your SMS")
print("messages are delivered instead of filtered.")
print("\nCost: ~$4 brand fee + $10/month campaign (billed by Twilio)")
print("\nPress Ctrl+C to cancel.\n")

# ── Collect info ──────────────────────────────────────────────────────────────
print("Business info (pre-filled where known):")
biz_name    = input("Business name [WebByMaya]: ").strip() or "WebByMaya"
website     = input("Website [https://webbymaya.com]: ").strip() or "https://webbymaya.com"
street      = input("Street address: ").strip()
city        = input("City [Philadelphia]: ").strip() or "Philadelphia"
state       = input("State [PA]: ").strip() or "PA"
postal      = input("ZIP code [19100]: ").strip() or "19100"
first_name  = input("Your first name [Maya]: ").strip() or "Maya"
last_name   = input("Your last name [Sierra]: ").strip() or "Sierra"
email       = input("Contact email [mayas.worldwide.web@gmail.com]: ").strip() or "mayas.worldwide.web@gmail.com"
phone       = input("Contact phone [+12154602084]: ").strip() or "+12154602084"

print("\nBusiness registration:")
print("  1. Sole Proprietor (use last 4 of SSN — lower daily limits)")
print("  2. LLC / Corporation (use EIN — higher limits, recommended)")
biz_type_choice = input("Business type [1]: ").strip() or "1"

if biz_type_choice == "2":
    biz_type  = "LLC"
    reg_id    = "EIN"
    reg_num   = input("EIN (XX-XXXXXXX): ").strip()
else:
    biz_type  = "SOLE_PROPRIETOR"
    reg_id    = "SSN_LAST_4"
    reg_num   = input("Last 4 digits of SSN: ").strip()

# ── Step 1: Create Customer Profile ──────────────────────────────────────────
print("\n[1/4] Creating customer profile...")
profile_url = f"https://trusthub.twilio.com/v1/CustomerProfiles"
profile_data = {
    "FriendlyName": biz_name,
    "Email":        email,
    "PolicySid":    "RNdfbf3fae0e1107f8aded0e7cead80bf5",  # A2P 10DLC policy
}
resp, err = post(profile_url, profile_data)
if err:
    print(f"  Profile error: {err}")
    # Might already exist — continue anyway
    profiles = get(profile_url)
    profile_sid = profiles.get("results",[{}])[0].get("sid","")
else:
    profile_sid = resp.get("sid","")
print(f"  Profile SID: {profile_sid or 'existing'}")

# ── Step 2: Register Brand ────────────────────────────────────────────────────
print("\n[2/4] Registering brand with The Campaign Registry...")
brand_url  = "https://messaging.twilio.com/v1/a2p/BrandRegistrations"
brand_data = {
    "CustomerProfileBundleSid": profile_sid,
    "FriendlyName":        biz_name,
    "BusinessName":        biz_name,
    "DisplayName":         biz_name,
    "WebsiteURL":          website,
    "BusinessType":        biz_type,
    "BusinessIndustry":    "PROFESSIONAL_SERVICES",
    "BusinessRegistrationIdentifier": reg_id,
    "BusinessRegistrationNumber":     reg_num,
    "BusinessContactFirstName":  first_name,
    "BusinessContactLastName":   last_name,
    "BusinessContactEmail":      email,
    "BusinessContactPhone":      phone,
    "BusinessStreet":    street,
    "BusinessCity":      city,
    "BusinessStateProvinceRegion": state,
    "BusinessPostalCode": postal,
    "BusinessCountry":   "US",
}
resp, err = post(brand_url, brand_data)
if err:
    print(f"  Brand error: {err}")
    sys.exit("Brand registration failed. Check info and retry.")
brand_sid    = resp["sid"]
brand_status = resp.get("status","")
print(f"  Brand SID: {brand_sid}  |  Status: {brand_status}")
print("  (Brand verification usually takes a few minutes to a few hours)")

# Save brand SID for campaign step
open("/tmp/webbymaya_brand_sid.txt","w").write(brand_sid)

# ── Step 3: Create Messaging Service ─────────────────────────────────────────
print("\n[3/4] Creating messaging service...")
svc_url  = "https://messaging.twilio.com/v1/Services"
svc_data = {
    "FriendlyName":         "WebByMaya Outreach",
    "UseInboundWebhookOnNumber": False,
    "InboundRequestUrl":    "https://webbymaya-auto-reply-2191-prod.twil.io/auto-reply",
}
resp, err = post(svc_url, svc_data)
if err:
    print(f"  Service error: {err}")
else:
    svc_sid = resp["sid"]
    print(f"  Service SID: {svc_sid}")

    # Add phone number to messaging service
    num_url  = f"https://messaging.twilio.com/v1/Services/{svc_sid}/PhoneNumbers"
    twilio_number = os.environ.get("TWILIO_PHONE_NUMBER","")
    # Get phone number SID
    nums = get(f"https://api.twilio.com/2010-04-01/Accounts/{SID}/IncomingPhoneNumbers.json?PhoneNumber={urllib.parse.quote(twilio_number)}")
    num_sid = nums["incoming_phone_numbers"][0]["sid"]
    post(num_url, {"PhoneNumberSid": num_sid})
    print(f"  Phone {twilio_number} added to messaging service")
    open("/tmp/webbymaya_svc_sid.txt","w").write(svc_sid)

print("\n[4/4] Campaign registration requires brand approval first.")
print("      Once your brand shows APPROVED status, run:")
print("      python3 register_10dlc_campaign.py")
print(f"\nBrand SID saved: {brand_sid}")
print("\nCheck status anytime:")
print(f"  python3 -c \"import base64,json,os,urllib.request; creds=base64.b64encode(f\\\"{os.environ['TWILIO_ACCOUNT_SID']}:{os.environ['TWILIO_AUTH_TOKEN']}\\\".encode()).decode(); req=urllib.request.Request('https://messaging.twilio.com/v1/a2p/BrandRegistrations/{brand_sid}',headers={{'Authorization':f'Basic {{creds}}'}}); print(json.loads(urllib.request.urlopen(req).read()).get('status'))\"")
