#!/usr/bin/env python3
"""
Scan mayas.worldwide.web Gmail, build label hierarchy, and set up filters.
Labels:
  WebbymMaya / Social Media / Client Responses / Receipts & Invoices
  ClassArena  / Social Media / Receipts & Invoices
  CadEX       / Social Media / Client Responses / Receipts & Invoices
  General     / Receipts & Invoices / Newsletters
"""
import json
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN = Path.home() / ".webbymaaya/gmail_token.json"
creds = Credentials.from_authorized_user_file(str(TOKEN))
svc = build("gmail", "v1", credentials=creds)

# ── LABEL STRUCTURE ──────────────────────────────────────────────────────────

LABELS = [
    "WebbymMaya",
    "WebbymMaya/Social Media",
    "WebbymMaya/Client Responses",
    "WebbymMaya/Receipts & Invoices",
    "ClassArena",
    "ClassArena/Social Media",
    "ClassArena/Receipts & Invoices",
    "CadEX",
    "CadEX/Social Media",
    "CadEX/Client Responses",
    "CadEX/Receipts & Invoices",
    "General",
    "General/Receipts & Invoices",
    "General/Newsletters",
]

COLORS = {
    "WebbymMaya":   {"backgroundColor": "#4986e7", "textColor": "#ffffff"},
    "ClassArena":   {"backgroundColor": "#16a766", "textColor": "#ffffff"},
    "CadEX":        {"backgroundColor": "#e07798", "textColor": "#ffffff"},
    "General":      {"backgroundColor": "#8e63ce", "textColor": "#ffffff"},
}

def get_or_create_label(name):
    existing = svc.users().labels().list(userId="me").execute().get("labels", [])
    for l in existing:
        if l["name"] == name:
            return l["id"]
    body = {"name": name, "labelListVisibility": "labelShow", "messageListVisibility": "show"}
    parent = name.split("/")[0]
    if parent in COLORS:
        body["color"] = COLORS[parent]
    result = svc.users().labels().create(userId="me", body=body).execute()
    print(f"  Created: {name}")
    return result["id"]

print("Creating labels...")
label_ids = {name: get_or_create_label(name) for name in LABELS}
print(f"Done — {len(label_ids)} labels ready.\n")

# ── FILTERS ──────────────────────────────────────────────────────────────────

FILTERS = [
    # WebbymMaya — emails from/about webbymaya
    {
        "criteria": {"query": "from:webbymaya.com OR subject:(webbymaya OR web design OR web dev)"},
        "action":   {"addLabelIds": [label_ids["WebbymMaya"]]},
    },
    # WebbymMaya client responses
    {
        "criteria": {"query": "from:webbymaya.com subject:(proposal OR project OR client OR quote)"},
        "action":   {"addLabelIds": [label_ids["WebbymMaya/Client Responses"]]},
    },
    # WebbymMaya social media notifications
    {
        "criteria": {"query": "subject:(webbymaya) from:(facebook.com OR instagram.com OR linkedin.com)"},
        "action":   {"addLabelIds": [label_ids["WebbymMaya/Social Media"]]},
    },
    # WebbymMaya receipts
    {
        "criteria": {"query": "subject:(invoice OR receipt OR payment) from:(stripe.com OR paypal.com OR square.com) subject:webbymaya"},
        "action":   {"addLabelIds": [label_ids["WebbymMaya/Receipts & Invoices"]]},
    },
    # ClassArena — all emails
    {
        "criteria": {"query": "from:classarena.org OR to:hello@classarena.org OR subject:classarena"},
        "action":   {"addLabelIds": [label_ids["ClassArena"]]},
    },
    # ClassArena social (PH, Reddit notifications)
    {
        "criteria": {"query": "from:producthunt.com OR from:reddit.com OR from:alternativeto.net subject:classarena"},
        "action":   {"addLabelIds": [label_ids["ClassArena/Social Media"]]},
    },
    # ClassArena receipts
    {
        "criteria": {"query": "from:stripe.com subject:classarena"},
        "action":   {"addLabelIds": [label_ids["ClassArena/Receipts & Invoices"]]},
    },
    # CadEX — all emails
    {
        "criteria": {"query": "subject:(cadex OR cad exchange)"},
        "action":   {"addLabelIds": [label_ids["CadEX"]]},
    },
    # CadEX client responses
    {
        "criteria": {"query": "subject:(cadex OR cad exchange) subject:(proposal OR client OR quote OR project)"},
        "action":   {"addLabelIds": [label_ids["CadEX/Client Responses"]]},
    },
    # General receipts — big platforms
    {
        "criteria": {"query": "from:(amazon.com OR apple.com OR google.com OR microsoft.com OR cloudflare.com OR vercel.com OR stripe.com OR namecheap.com) subject:(receipt OR invoice OR order confirmation OR your order OR charge)"},
        "action":   {"addLabelIds": [label_ids["General/Receipts & Invoices"]]},
    },
    # General newsletters
    {
        "criteria": {"query": "subject:(newsletter OR unsubscribe OR weekly digest OR monthly roundup)"},
        "action":   {"addLabelIds": [label_ids["General/Newsletters"]]},
    },
]

print("Creating filters...")
existing_filters = svc.users().settings().filters().list(userId="me").execute().get("filter", [])
print(f"  (existing filters: {len(existing_filters)})")

created = 0
for f in FILTERS:
    try:
        svc.users().settings().filters().create(userId="me", body=f).execute()
        created += 1
    except Exception as e:
        print(f"  Filter skip: {e}")

print(f"  Created {created} filters.\n")

# ── SCAN & REPORT ─────────────────────────────────────────────────────────────

print("Scanning inbox for summary...")
result = svc.users().messages().list(userId="me", labelIds=["INBOX"], maxResults=100).execute()
messages = result.get("messages", [])
print(f"  {len(messages)} messages in inbox (showing first 100)")
print("\nAll done. Your inbox labels and filters are live.")
