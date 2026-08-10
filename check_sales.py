#!/usr/bin/env python3
"""
check_sales.py — WebByMaya post-payment automation.

Polls Stripe for NEW paid checkouts on the $499 website Payment Link, then:
  1. Alerts Maya (email + best-effort macOS notification) that a sale closed.
  2. Emails the buyer a welcome + their intake form so the build starts itself.

Runs like the other pollers (auto_reply, notify) — safe to call every few
minutes from cron/launchd. State is de-duped in .seen_sales.json so each sale
is only ever processed once.

    python3 check_sales.py            # process new sales
    python3 check_sales.py --dry-run  # show what would happen, send nothing
"""
import argparse, json, urllib.request, urllib.parse
from pathlib import Path

import offer
from auto_reply import _send_email   # reuse the SendGrid sender

SCRIPT_DIR   = Path(__file__).parent
STATE_FILE   = SCRIPT_DIR / ".seen_sales.json"
ENV_FILE     = Path.home() / "Projects/jarvis/.env.local"

# The $499 WebByMaya website Payment Link (isolates our sales from ClassArena/JARVIS
# on the same Stripe account).
PAYMENT_LINK_ID = "plink_1TxulxAJ84QZjwZkz9kFD8iz"

# Where sale alerts go.
ALERT_EMAILS = ["maya@webbymaya.com", "mayasierra1999@gmail.com"]


def _stripe_key() -> str:
    if not ENV_FILE.exists():
        return ""
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("STRIPE_SECRET_KEY="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return ""


def _stripe_get(path: str, key: str, params: dict) -> dict:
    url = f"https://api.stripe.com/v1/{path}?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=15).read())
    except Exception as e:
        print(f"  [stripe] error: {e}")
        return {}


def _load_state() -> dict:
    return json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _mac_notify(title: str, body: str):
    try:
        import subprocess
        subprocess.run(["osascript", "-e",
                        f'display notification "{body}" with title "{title}" sound name "Glass"'],
                       timeout=5)
    except Exception:
        pass


# ---- Email bodies --------------------------------------------------------

def _alert_maya(buyer_email: str, buyer_name: str, amount: str, dry_run: bool):
    subj  = f"💰 NEW SALE — {amount} from {buyer_name or buyer_email}"
    plain = (f"You made a sale!\n\n"
             f"Amount:  {amount}\n"
             f"Buyer:   {buyer_name or '(no name)'}\n"
             f"Email:   {buyer_email}\n\n"
             f"They've been auto-sent the intake form ({offer.BOOKING_URL}).\n"
             f"Next step: build their site and get it live in 7 days.\n\n"
             f"— WebByMaya automation")
    html  = (f'<div style="font-family:Arial,sans-serif;color:#333;max-width:520px">'
             f'<h2 style="color:#1a7f37">💰 New sale — {amount}</h2>'
             f'<p><strong>Buyer:</strong> {buyer_name or "(no name)"}<br>'
             f'<strong>Email:</strong> {buyer_email}</p>'
             f'<p>They\'ve been auto-sent the intake form. Next step: build their site '
             f'and get it live in 7 days.</p></div>')
    for to in ALERT_EMAILS:
        _send_email(to, subj, plain, html, dry_run)
    _mac_notify("WebByMaya — NEW SALE 💰", f"{amount} from {buyer_email}")


def _welcome_buyer(buyer_email: str, buyer_name: str, dry_run: bool):
    hi    = f"Hi {buyer_name.split()[0]}," if buyer_name else "Hi there,"
    subj  = "You're in! Let's build your website 🎉"
    plain = (f"{hi}\n\n"
             f"Thank you — payment received and I'm excited to build your site!\n\n"
             f"One quick step: fill out my short intake form so I have everything I need "
             f"(your business info, photos, colors). Takes about 5 minutes, no calls needed:\n\n"
             f"{offer.BOOKING_URL}\n\n"
             f"Here's what's included: a free domain + your first year of hosting, SSL, and full "
             f"setup — live within 7 days. After year one, hosting & maintenance is just "
             f"{offer.MONTHLY}.\n\n"
             f"As soon as you send the form, I'll get started and have a preview to you fast.\n\n"
             f"— Maya\nWebByMaya.com")
    html  = (f'<div style="font-family:Arial,sans-serif;color:#333;max-width:600px;line-height:1.6">'
             f'<p>{hi}</p>'
             f'<p>Thank you — payment received and I\'m excited to build your site! 🎉</p>'
             f'<p>One quick step: fill out my short intake form so I have everything I need '
             f'(business info, photos, colors). About 5 minutes, no calls needed:</p>'
             f'<p><a href="{offer.BOOKING_URL}" style="background:#C9A96E;color:#0d0d0d;padding:12px 24px;'
             f'text-decoration:none;border-radius:6px;font-weight:bold;display:inline-block">'
             f'Start my website &rarr;</a></p>'
             f'<p>Included: a <strong>free domain + your first year of hosting</strong>, SSL &amp; full '
             f'setup — live within 7 days. After year one, hosting &amp; maintenance is just {offer.MONTHLY}.</p>'
             f'<p>As soon as you send the form, I\'ll get started and have a preview to you fast.</p>'
             f'<p>— Maya<br><a href="https://webbymaya.com">WebByMaya.com</a></p></div>')
    _send_email(buyer_email, subj, plain, html, dry_run)


# ---- Main ----------------------------------------------------------------

def process_sales(dry_run: bool = False) -> int:
    key = _stripe_key()
    if not key:
        print("  [check_sales] no Stripe key found in", ENV_FILE)
        return 0

    seen = _load_state()
    data = _stripe_get("checkout/sessions", key,
                       {"payment_link": PAYMENT_LINK_ID, "limit": 50})
    sessions = data.get("data", [])
    new_count = 0

    for s in sessions:
        sid = s.get("id", "")
        if not sid or sid in seen:
            continue
        if s.get("payment_status") != "paid":
            continue  # skip abandoned / unpaid sessions

        details    = s.get("customer_details") or {}
        buyer_email = (details.get("email") or "").strip()
        buyer_name  = (details.get("name") or "").strip()
        amount      = f"${(s.get('amount_total') or 0) / 100:.0f}"

        if not buyer_email:
            continue

        tag = "[DRY RUN] " if dry_run else ""
        print(f"  {tag}NEW SALE: {amount} from {buyer_name or '(no name)'} <{buyer_email}>")

        _alert_maya(buyer_email, buyer_name, amount, dry_run)
        _welcome_buyer(buyer_email, buyer_name, dry_run)

        if not dry_run:
            seen[sid] = {"email": buyer_email, "name": buyer_name, "amount": amount}
        new_count += 1

    if not dry_run:
        _save_state(seen)
    print(f"  Done — {new_count} new sale(s) processed.")
    return new_count


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="WebByMaya — process new Stripe website sales")
    ap.add_argument("--dry-run", action="store_true", help="preview without sending")
    args = ap.parse_args()
    print(f"\n{'[DRY RUN] ' if args.dry_run else ''}WebByMaya Sales Check")
    process_sales(dry_run=args.dry_run)
