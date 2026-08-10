#!/usr/bin/env python3
"""
form_responder.py — Instant auto-response to webbymaya.com/book form submissions.

Polls Supabase `contact_messages` for new rows where replied_at IS NULL.
For each unanswered submission:
  1. Generates a personalized mockup and uploads it to Supabase storage
  2. Sends a reply email with the mockup preview + pricing
  3. Marks the row replied_at = now() so it's never re-sent

Requires a service-role key for the site's CURRENT project (see SITE_ENV); the
anon key is subject to RLS and will silently return zero pending submissions.

Designed to run every 15 minutes via launchd (see setup at bottom of file).
Also called once per daily run from run_daily.sh as a safety net.

USAGE
    python3 form_responder.py              # process all pending submissions
    python3 form_responder.py --dry-run    # preview without sending or marking
"""

import argparse
import base64
import datetime
import email.mime.multipart
import email.mime.text
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

SCRIPT_DIR   = Path(__file__).parent
TOKEN_PATH   = Path.home() / ".webbymaaya/gmail_token.json"
SENDER_EMAIL = "maya@webbymaya.com"
SENDER_NAME  = "Maya Sierra"

# The live site's Supabase project. Read from the site's own .env so this can
# never drift out of sync with what the website actually writes to — it already
# did once: this script polled the retired project `ycsauzlqsjjbusugshpz` (and a
# table that no longer exists there) while the site wrote to the current one.
SITE_ENV = Path.home() / "Projects/maya-studio-shine/.env"

# Inbound submissions land here. `mockup_inquiries` was the old project's table.
INQUIRY_TABLE = "contact_messages"


def _read_site_env() -> dict:
    vals = {}
    if SITE_ENV.exists():
        for line in SITE_ENV.read_text().splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    return vals


def _jwt_ref(token: str) -> str:
    """Project ref a Supabase JWT belongs to ('' if it isn't one)."""
    import base64 as _b64
    import json as _json
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return _json.loads(_b64.urlsafe_b64decode(payload)).get("ref", "")
    except Exception:
        return ""


_env = _read_site_env()
SUPABASE_PROJECT = _env.get("VITE_SUPABASE_PROJECT_ID") or _env.get("SUPABASE_PROJECT_ID", "")
SUPABASE_URL     = _env.get("VITE_SUPABASE_URL") or _env.get("SUPABASE_URL", "")
SUPABASE_ANON    = _env.get("VITE_SUPABASE_PUBLISHABLE_KEY") or _env.get("SUPABASE_PUBLISHABLE_KEY", "")
SUPABASE_SERVICE = os.environ.get("SUPABASE_SERVICE_KEY", "") or _env.get("SUPABASE_SERVICE_ROLE_KEY", "")

# A key for a different project authenticates fine and then 403s on every table,
# which reads like a permissions problem and sends you hunting for GRANTs. Check
# the ref instead of guessing.
if SUPABASE_SERVICE and SUPABASE_PROJECT and _jwt_ref(SUPABASE_SERVICE) != SUPABASE_PROJECT:
    print(f"[warn] SUPABASE_SERVICE_ROLE_KEY belongs to project "
          f"'{_jwt_ref(SUPABASE_SERVICE)}' but the site is on '{SUPABASE_PROJECT}' — ignoring it.")
    SUPABASE_SERVICE = ""

# Reads need to see every submission, so they need the service role; the anon key
# is subject to RLS and will quietly return an empty list.
_READ_KEY  = SUPABASE_SERVICE or SUPABASE_ANON
_WRITE_KEY = SUPABASE_SERVICE or SUPABASE_ANON


# ── Supabase helpers ──────────────────────────────────────────────────────────

def _sb_get(path: str, params: dict = None) -> list[dict]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url,
        headers={
            "apikey":        _READ_KEY,
            "Authorization": f"Bearer {_READ_KEY}",
            "Content-Type":  "application/json",
        },
    )
    try:
        resp = urllib.request.urlopen(req, timeout=10).read()
        return json.loads(resp)
    except Exception as e:
        print(f"[Supabase GET error] {e}")
        return []


def _sb_patch(path: str, row_id: str, data: dict) -> bool:
    url = f"{SUPABASE_URL}/rest/v1/{path}?id=eq.{row_id}"
    payload = json.dumps(data).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "apikey":        _WRITE_KEY,
            "Authorization": f"Bearer {_WRITE_KEY}",
            "Content-Type":  "application/json",
            "Prefer":        "return=minimal",
        },
        method="PATCH",
    )
    try:
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        print(f"[Supabase PATCH error] {e.code}: {e.read().decode()[:200]}")
        return False
    except Exception as e:
        print(f"[Supabase PATCH error] {e}")
        return False


# ── Gmail send ────────────────────────────────────────────────────────────────

def _gmail_token() -> str:
    if not TOKEN_PATH.exists():
        return ""
    tok = json.loads(TOKEN_PATH.read_text())
    access = tok.get("token", "")
    try:
        exp = datetime.datetime.fromisoformat(tok["expiry"].replace("Z", "+00:00"))
        from datetime import timezone, timedelta
        if datetime.datetime.now(timezone.utc) >= exp - timedelta(seconds=60):
            data = urllib.parse.urlencode({
                "client_id":     tok["client_id"],
                "client_secret": tok["client_secret"],
                "refresh_token": tok["refresh_token"],
                "grant_type":    "refresh_token",
            }).encode()
            resp = json.loads(urllib.request.urlopen(
                urllib.request.Request("https://oauth2.googleapis.com/token", data=data),
                timeout=10).read())
            access = resp["access_token"]
            tok["token"]  = access
            from datetime import timezone, timedelta
            tok["expiry"] = (datetime.datetime.now(timezone.utc) +
                             timedelta(seconds=resp.get("expires_in", 3600))
                             ).strftime("%Y-%m-%dT%H:%M:%SZ")
            TOKEN_PATH.write_text(json.dumps(tok))
    except Exception:
        pass
    return access


def send_email(to: str, subject: str, plain: str, html: str) -> bool:
    access = _gmail_token()
    if not access:
        print("  [ERROR] No Gmail token")
        return False
    try:
        msg = email.mime.multipart.MIMEMultipart("alternative")
        msg["To"]      = to
        msg["From"]    = f"{SENDER_NAME} <{SENDER_EMAIL}>"
        msg["Subject"] = subject
        msg.attach(email.mime.text.MIMEText(plain, "plain"))
        msg.attach(email.mime.text.MIMEText(html,  "html"))
        raw     = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        payload = json.dumps({"raw": raw}).encode()
        req = urllib.request.Request(
            "https://gmail.googleapis.com/gmail/v1/users/me/messages/send",
            data=payload,
            headers={"Authorization": f"Bearer {access}", "Content-Type": "application/json"},
            method="POST",
        )
        urllib.request.urlopen(req, timeout=10)
        return True
    except urllib.error.HTTPError as e:
        print(f"  [GMAIL ERROR] {e.code}: {e.read().decode()[:200]}")
    except Exception as exc:
        print(f"  [GMAIL ERROR] {exc}")
    return False


# ── Email content ─────────────────────────────────────────────────────────────

def _build_response(submitter_name: str, business_name: str, mockup_url: str) -> tuple[str, str]:
    display = business_name or "your business"
    greet   = f"Hi {submitter_name}," if submitter_name else "Hi there,"

    plain = f"""\
{greet}

Thank you for filling out my intake form — I'm already on it!
"""

    if mockup_url:
        plain += f"""
I put together a free website preview for {display}. Take a look:

{mockup_url}

"""
    plain += f"""\
Here's a quick breakdown of my packages:

LITE  — $499
• 1 page (all your key info, clean and professional)
• Mobile-ready
• Live in 1 week
• Payment plan: $150 now, $349 on launch

STARTER  — $799  ← most popular
• 5 pages (Home, About, Services, Gallery, Contact)
• Mobile-ready design
• Google Analytics & Search Console setup
• Live in 2 weeks
• Payment plan: $200 now, $599 on launch

STANDARD  — $1,299
• 8 pages + contact/quote form
• On-page SEO
• Online booking integration
• Live in 3 weeks
• Payment plan: $300 now, $999 on launch

CUSTOM  — Starting at $1,999
• Fully custom design matched to your brand
• E-commerce, menus, memberships — anything you need

All packages include 1 year free hosting, SSL, domain setup, and 30-day support.

────────────────────────────────────────
WHAT TO GATHER (only takes 10 minutes):

1. Your logo — any format works (JPG, PNG, PDF)
   No logo? No problem — I can create a simple wordmark.

2. Photos of your work / business / team
   Even phone photos are fine. More = better.

3. Business info — hours, address, phone, services + prices

4. 1–3 sentences about what makes your business special
   (what you'd tell a new customer)

That's it. Reply with these or just say "go for it" and I'll
work with what I already know about {display}.
────────────────────────────────────────

I'll follow up shortly. Reply here with any questions — I check email daily.
No calls needed. Everything by email.

— Maya
Web Designer · WebByMaya.com
maya@webbymaya.com
"""

    mockup_block = ""
    if mockup_url:
        mockup_block = f"""
  <table width="100%" cellpadding="0" cellspacing="0" style="margin:0 0 28px;">
    <tr>
      <td style="background:#0d0d0d;border-radius:8px;padding:24px;text-align:center;">
        <div style="font-family:Arial,sans-serif;font-size:11px;text-transform:uppercase;
          letter-spacing:2px;color:#C9A96E;margin-bottom:10px;">Your free website preview</div>
        <a href="{mockup_url}"
          style="display:inline-block;background:#C9A96E;color:#0d0d0d;padding:14px 32px;
          border-radius:6px;font-weight:800;font-size:15px;font-family:Arial,sans-serif;
          text-decoration:none;letter-spacing:0.3px;">
          &#128064;&nbsp; View Your Preview &rarr;
        </a>
        <div style="font-family:Arial,sans-serif;font-size:12px;color:#666;margin-top:10px;">
          Built just for {display}</div>
      </td>
    </tr>
  </table>"""

    html = f"""<!DOCTYPE html><html><body style="font-family:Arial,sans-serif;background:#f4f4f4;margin:0;padding:24px">
<div style="max-width:580px;margin:0 auto;background:#fff;border-radius:12px;overflow:hidden;
  box-shadow:0 2px 12px rgba(0,0,0,.08)">

  <div style="background:#0d0d0d;padding:28px 36px">
    <div style="font-size:22px;font-weight:800;color:#fff">WebBy<span style="color:#C9A96E">Maya</span></div>
    <div style="font-size:13px;color:#888;margin-top:4px">Philadelphia Web Design · Starting at $499 · Payment plans available</div>
  </div>

  <div style="padding:32px 36px">
    <p style="font-size:15px;color:#333;margin-bottom:20px">{greet}</p>
    <p style="font-size:15px;color:#333;margin-bottom:24px">
      Thank you for filling out my intake form — I'm already on it!
    </p>
    {mockup_block}

    <p style="font-size:15px;color:#333;margin-bottom:20px">
      Here's a quick breakdown of my packages:
    </p>

    <!-- LITE -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:18px 22px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:16px;font-weight:800">Lite</div>
        <div style="font-size:18px;font-weight:900;color:#C9A96E">$499</div>
      </div>
      <ul style="color:#555;font-size:13px;line-height:1.9;padding-left:16px;margin:0 0 8px 0">
        <li>1 page — all your key info, clean &amp; professional</li>
        <li>Mobile-ready &amp; fast loading</li>
        <li style="color:#C9A96E;font-weight:600">Live in 1 week</li>
      </ul>
      <div style="font-size:11px;color:#888;background:#f9f9f9;border-radius:5px;padding:7px 10px">
        Payment plan: <strong style="color:#555">$150 now · $349 on launch</strong>
      </div>
    </div>

    <!-- STARTER -->
    <div style="border:2px solid #C9A96E;border-radius:10px;padding:18px 22px;margin-bottom:12px;position:relative">
      <div style="position:absolute;top:-11px;left:18px;background:#C9A96E;color:#0d0d0d;
        font-size:10px;font-weight:800;padding:3px 10px;border-radius:20px;letter-spacing:.05em">MOST POPULAR</div>
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:16px;font-weight:800">Starter</div>
        <div style="font-size:18px;font-weight:900;color:#C9A96E">$799</div>
      </div>
      <ul style="color:#555;font-size:13px;line-height:1.9;padding-left:16px;margin:0 0 8px 0">
        <li>5 pages — Home, About, Services, Gallery, Contact</li>
        <li>Mobile-ready &amp; fast loading</li>
        <li>Google Analytics setup</li>
        <li style="color:#C9A96E;font-weight:600">Live in 2 weeks</li>
      </ul>
      <div style="font-size:11px;color:#888;background:#fdf8f0;border-radius:5px;padding:7px 10px">
        Payment plan: <strong style="color:#555">$200 now · $599 on launch</strong>
      </div>
    </div>

    <!-- STANDARD -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:18px 22px;margin-bottom:12px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:16px;font-weight:800">Standard</div>
        <div style="font-size:18px;font-weight:900;color:#C9A96E">$1,299</div>
      </div>
      <ul style="color:#555;font-size:13px;line-height:1.9;padding-left:16px;margin:0 0 8px 0">
        <li>8 pages + contact/quote form</li>
        <li>On-page SEO — show up on Google</li>
        <li>Online booking or reservation integration</li>
        <li style="color:#C9A96E;font-weight:600">Live in 3 weeks</li>
      </ul>
      <div style="font-size:11px;color:#888;background:#f9f9f9;border-radius:5px;padding:7px 10px">
        Payment plan: <strong style="color:#555">$300 now · $999 on launch</strong>
      </div>
    </div>

    <!-- CUSTOM -->
    <div style="border:1.5px solid #e8e8e8;border-radius:10px;padding:18px 22px;margin-bottom:24px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
        <div style="font-size:16px;font-weight:800">Custom</div>
        <div style="font-size:18px;font-weight:900;color:#C9A96E">$1,999+</div>
      </div>
      <ul style="color:#555;font-size:13px;line-height:1.9;padding-left:16px;margin:0">
        <li>Fully custom design matched to your brand</li>
        <li>E-commerce, menus, memberships — anything you need</li>
        <li>Timeline based on scope</li>
      </ul>
    </div>

    <div style="background:#f5f5f5;border-radius:8px;padding:14px 18px;margin-bottom:24px;
      font-size:12px;color:#555">
      <strong style="color:#333">All packages include:</strong>
      &nbsp;&#10003; 1 year free hosting &nbsp;&#10003; SSL &nbsp;&#10003; Domain setup &nbsp;&#10003; 30-day support
    </div>

    <!-- WHAT TO PREPARE -->
    <div style="border:1.5px solid #C9A96E;border-radius:10px;padding:18px 22px;margin-bottom:24px">
      <div style="font-size:14px;font-weight:700;color:#C9A96E;margin-bottom:12px">
        What to gather — takes about 10 minutes
      </div>
      <table style="width:100%;border-collapse:collapse;font-size:13px;color:#555">
        <tr>
          <td style="padding:5px 0;vertical-align:top;width:28px;color:#C9A96E;font-weight:700">1.</td>
          <td style="padding:5px 0"><strong style="color:#333">Logo</strong> — any format (JPG, PNG, PDF).
            No logo? I can make a simple wordmark.</td>
        </tr>
        <tr>
          <td style="padding:5px 0;vertical-align:top;color:#C9A96E;font-weight:700">2.</td>
          <td style="padding:5px 0"><strong style="color:#333">Photos</strong> — your work, space, or team.
            Phone photos are totally fine.</td>
        </tr>
        <tr>
          <td style="padding:5px 0;vertical-align:top;color:#C9A96E;font-weight:700">3.</td>
          <td style="padding:5px 0"><strong style="color:#333">Basic info</strong> — hours, address, phone,
            services &amp; prices.</td>
        </tr>
        <tr>
          <td style="padding:5px 0;vertical-align:top;color:#C9A96E;font-weight:700">4.</td>
          <td style="padding:5px 0"><strong style="color:#333">One sentence</strong> — what makes
            {display} special. I'll write the rest.</td>
        </tr>
      </table>
      <p style="font-size:12px;color:#888;margin:12px 0 0">
        Just reply with these when ready — or say <strong>"go for it"</strong>
        and I'll start from what I already know.
      </p>
    </div>

    <p style="font-size:14px;color:#555;margin-bottom:20px">
      I'll follow up shortly. Reply here with any questions — I check email daily.<br>
      <strong>No calls needed. Everything by email.</strong>
    </p>

    <div style="border-top:1px solid #eee;padding-top:20px;font-size:13px;color:#888">
      Maya Sierra &nbsp;·&nbsp; Web Designer &nbsp;·&nbsp;
      <a href="https://webbymaya.com" style="color:#C9A96E;text-decoration:none;">WebByMaya.com</a>
      &nbsp;·&nbsp; Philadelphia, PA
    </div>
  </div>
</div>
</body></html>"""

    return plain, html


# ── Mockup generator ──────────────────────────────────────────────────────────

def _try_build_mockup(business_name: str, message: str) -> str:
    try:
        sys.path.insert(0, str(SCRIPT_DIR))
        from mockup_uploader import upload_mockup
        category = ""
        city     = "Philadelphia, PA"
        # Guess category from message keywords
        msg_lower = (message or "").lower()
        for kw, cat in [
            ("salon","hair salon"), ("nail","nail salon"), ("spa","spa"),
            ("restaurant","restaurant"), ("cafe","cafe"), ("bakery","bakery"),
            ("auto","auto repair"), ("mechanic","auto repair"),
            ("clean","cleaning service"), ("massage","massage"),
        ]:
            if kw in msg_lower or kw in (business_name or "").lower():
                category = cat
                break
        url = upload_mockup(business_name, category, "", city)
        return url or ""
    except Exception as e:
        print(f"  [mockup] failed: {e}")
        return ""


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    rows = _sb_get(
        INQUIRY_TABLE,
        {"replied_at": "is.null",
         "select": "id,created_at,name,email,message,project_type"},
    )

    pending = [r for r in rows if r.get("email")]
    print(f"\nForm responder — {datetime.date.today()}")
    print(f"Pending form submissions: {len(pending)}")
    if args.dry_run:
        print("MODE: DRY RUN\n")

    for i, row in enumerate(pending):
        row_id        = row["id"]
        email_addr    = row["email"].strip().lower()
        # contact_messages has no business_name column — the submitter's name is
        # the only thing to personalise the preview with.
        submitter     = (row.get("name") or "").strip()
        business_name = submitter
        message       = (row.get("message") or "").strip()
        created       = row.get("created_at", "")[:16]

        print(f"\n[{i+1}/{len(pending)}] {email_addr}  (submitted {created})")
        if business_name:
            print(f"  Business : {business_name}")
        if submitter:
            print(f"  Name     : {submitter}")

        mockup_url = ""
        if business_name and not args.dry_run:
            print("  Generating mockup...")
            mockup_url = _try_build_mockup(business_name, message)
            if mockup_url:
                print(f"  Mockup   : {mockup_url}")

        subject = (f"Re: {business_name} — your free website preview is ready!"
                   if (business_name and mockup_url)
                   else "Re: WebByMaya — thanks for reaching out!")

        plain, html = _build_response(submitter, business_name, mockup_url)

        print(f"  Subject  : {subject}")

        if args.dry_run:
            print("  [DRY RUN] Would send ↑ and mark responded")
            continue

        ok = send_email(email_addr, subject, plain, html)
        if ok:
            print("  Sent.")
            _sb_patch(INQUIRY_TABLE, row_id, {
                "replied_at": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
                "replied_by": "form_responder",
            })
        else:
            print("  Failed to send.")

    print(f"\nDone — {len(pending)} processed.")


if __name__ == "__main__":
    main()
