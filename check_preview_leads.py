#!/usr/bin/env python3
"""
check_preview_leads.py — alert Maya when someone fills in a preview page.

Why this exists: the preview form posts to `contact_messages` in the website's
Lovable project, whose anon key can INSERT but not SELECT. So a captured lead
was invisible — no notification, no dashboard, no way to even look. On 08-14 a
count that had been reporting 0 turned out to be 6. Nothing was lost that time
(all six were tests or spam), but the next one would have been a real customer
saying "our hours are wrong" into a void.

So every preview now writes a second copy to `preview_leads` in Maya's own
project, and this reads that copy and alerts her. Rows are marked notified so
she is told exactly once.

Usage:
    python3 check_preview_leads.py            # alert on anything new
    python3 check_preview_leads.py --list     # show everything, change nothing
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
ANON_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1"
    "emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5"
    "NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
)
HEADERS = {"apikey": ANON_KEY, "Authorization": f"Bearer {ANON_KEY}",
           "Content-Type": "application/json"}


def _get(path: str):
    req = urllib.request.Request(f"{SUPABASE_URL}/rest/v1/{path}", headers=HEADERS)
    return json.loads(urllib.request.urlopen(req, timeout=20).read())


def _mark_notified(row_id: str) -> None:
    req = urllib.request.Request(
        f"{SUPABASE_URL}/rest/v1/preview_leads?id=eq.{row_id}",
        data=json.dumps({"notified": True}).encode(),
        headers={**HEADERS, "Prefer": "return=minimal"}, method="PATCH")
    try:
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"  [warn] could not mark {row_id} notified: {e}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="show all, mark nothing")
    a = ap.parse_args()

    if a.list:
        rows = _get("preview_leads?select=*&order=created_at.desc&limit=50")
        print(f"{len(rows)} preview lead(s) on file")
        for r in rows:
            flag = "" if r.get("notified") else "  ← NOT YET NOTIFIED"
            print(f"\n  {r.get('created_at','')[:16]}  {r.get('business','')}{flag}")
            print(f"    contact: {r.get('contact','')}")
            print(f"    says   : {(r.get('message') or '').strip()[:200]}")
            print(f"    preview: {r.get('preview_url','')}")
        return

    try:
        new = _get("preview_leads?select=*&notified=is.false&order=created_at.asc")
    except Exception as e:
        print(f"[preview-leads] could not read: {e}")
        return

    if not new:
        print("[preview-leads] none new.")
        return

    print(f"[preview-leads] {len(new)} NEW preview lead(s):")
    for r in new:
        biz = r.get("business") or "a business"
        contact = (r.get("contact") or "").strip()
        says = (r.get("message") or "").strip()
        print(f"\n  {biz} — {contact}")
        print(f"  \"{says[:300]}\"")
        print(f"  {r.get('preview_url','')}")

        # This is the highest-value event in the whole pipeline: somebody looked
        # at their preview and asked for a change. Use every channel available.
        body = (f"{biz} replied on their preview page.\n\n"
                f"Contact: {contact}\n\n"
                f"They said:\n{says}\n\n"
                f"Preview: {r.get('preview_url','')}\n\n"
                f"Make the change and send it back — they are already engaged.")
        try:
            subprocess.run([sys.executable, str(SCRIPT_DIR / "notify.py"),
                            f"PREVIEW LEAD — {biz}: {says[:80]}"],
                           timeout=60, capture_output=True)
        except Exception as e:
            print(f"  [warn] desktop/SMS notify failed: {e}")
        try:
            from batch_send_outreach import send_email
            ok = send_email("mayasierra1999@gmail.com",
                            f"Preview lead — {biz}",
                            body, f"<pre>{body}</pre>")
            print(f"  emailed Maya: {ok}")
        except Exception as e:
            print(f"  [warn] email alert failed: {e}")

        _mark_notified(r["id"])


if __name__ == "__main__":
    main()
