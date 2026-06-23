#!/usr/bin/env python3
"""Re-authorize Gmail with full label + filter permissions."""
from pathlib import Path
from google_auth_oauthlib.flow import InstalledAppFlow

CREDS = Path.home() / ".webbymaaya/gmail_credentials.json"
TOKEN = Path.home() / ".webbymaaya/gmail_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.labels",
    "https://www.googleapis.com/auth/gmail.settings.basic",
    "https://www.googleapis.com/auth/gmail.modify",
]

TOKEN.unlink(missing_ok=True)
flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), scopes=SCOPES)
creds = flow.run_local_server(port=0)
TOKEN.write_text(creds.to_json())
print("Done — Gmail authorized with full permissions.")
