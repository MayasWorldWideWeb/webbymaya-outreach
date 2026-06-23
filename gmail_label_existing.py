#!/usr/bin/env python3
"""Scan all existing emails and apply labels based on sender/subject."""
from pathlib import Path
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import time

TOKEN = Path.home() / ".webbymaaya/gmail_token.json"
creds = Credentials.from_authorized_user_file(str(TOKEN))
svc = build("gmail", "v1", credentials=creds)

# Get all label IDs
all_labels = {l["name"]: l["id"] for l in svc.users().labels().list(userId="me").execute().get("labels", [])}

def label_id(name):
    return all_labels.get(name)

# Rules: (gmail search query, [label names to apply])
RULES = [
    # Newsletters / marketing / notifications — most common junk
    (
        "from:(facebook.com OR facebookmail.com OR instagram.com OR twitter.com OR x.com OR linkedin.com OR pinterest.com OR tiktok.com OR youtube.com OR reddit.com)",
        ["General/Newsletters"]
    ),
    (
        "subject:(newsletter OR unsubscribe OR weekly digest OR monthly digest OR digest OR roundup OR update from)",
        ["General/Newsletters"]
    ),
    # App/SaaS receipts and billing
    (
        "from:(stripe.com OR paypal.com OR apple.com OR amazon.com OR google.com OR microsoft.com OR cloudflare.com OR vercel.com OR namecheap.com OR godaddy.com OR notion.so OR supabase.io OR figma.com OR canva.com OR dropbox.com OR zoom.us OR slack.com OR shopify.com) subject:(receipt OR invoice OR order OR charge OR billing OR payment OR subscription OR renewal)",
        ["General/Receipts & Invoices"]
    ),
    # App notifications (not billing)
    (
        "from:(github.com OR vercel.com OR netlify.com OR render.com OR heroku.com OR supabase.io OR notion.so OR figma.com OR canva.com OR trello.com OR asana.com OR airtable.com OR zapier.com OR monday.com)",
        ["General/Newsletters"]
    ),
    # ClassArena
    (
        "from:classarena.org OR to:hello@classarena.org OR subject:classarena",
        ["ClassArena"]
    ),
    (
        "from:stripe.com subject:classarena",
        ["ClassArena/Receipts & Invoices", "General/Receipts & Invoices"]
    ),
    (
        "from:producthunt.com OR from:reddit.com OR from:alternativeto.net",
        ["ClassArena/Social Media", "ClassArena"]
    ),
    # WebbymMaya
    (
        "from:webbymaya.com OR subject:(webbymaya OR web design OR web development)",
        ["WebbymMaya"]
    ),
    (
        "from:webbymaya.com subject:(invoice OR receipt OR payment)",
        ["WebbymMaya/Receipts & Invoices"]
    ),
    # CadEX
    (
        "subject:(cadex OR cad exchange)",
        ["CadEX"]
    ),
]

def apply_rule(query, label_names):
    ids = [label_id(n) for n in label_names if label_id(n)]
    if not ids:
        return 0

    page_token = None
    total = 0
    while True:
        params = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            params["pageToken"] = page_token
        result = svc.users().messages().list(**params).execute()
        messages = result.get("messages", [])
        if messages:
            # Batch modify
            svc.users().messages().batchModify(
                userId="me",
                body={"ids": [m["id"] for m in messages], "addLabelIds": ids}
            ).execute()
            total += len(messages)
        page_token = result.get("nextPageToken")
        if not page_token:
            break
        time.sleep(0.2)
    return total

print("Labeling existing emails...\n")
for query, labels in RULES:
    count = apply_rule(query, labels)
    if count:
        print(f"  {count:>4} emails → {', '.join(labels)}")
    time.sleep(0.3)

print("\nDone. Refresh your Gmail to see the labels applied.")
