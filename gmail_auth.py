#!/usr/bin/env python3
"""Run this once to authorize Gmail access. Opens a browser window."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

CREDS = Path.home() / ".webbymaaya/gmail_credentials.json"
TOKEN = Path.home() / ".webbymaaya/gmail_token.json"

if TOKEN.exists():
    print("Already authorized. Nothing to do.")
else:
    flow = InstalledAppFlow.from_client_secrets_file(
        str(CREDS), scopes=["https://www.googleapis.com/auth/gmail.readonly"])
    creds = flow.run_local_server(port=0)
    TOKEN.write_text(creds.to_json())
    print("Gmail authorized. Token saved.")
