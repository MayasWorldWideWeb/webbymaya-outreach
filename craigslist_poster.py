#!/usr/bin/env python3
"""
craigslist_poster.py — WebByMaya Auto Craigslist Poster
========================================================
Posts a weekly ad to Philadelphia Craigslist > Services > Computer.
Rotates through 4 ad variations to avoid duplicate-flagging.

SETUP (one time):
    export CRAIGSLIST_EMAIL="your@email.com"
    export CRAIGSLIST_PASSWORD="yourpassword"
    Add both to ~/.zshrc

    pip install playwright
    playwright install chromium

USAGE:
    python3 craigslist_poster.py             # post this week's ad
    python3 craigslist_poster.py --dry-run   # preview without posting
"""

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
STATE_FILE  = SCRIPT_DIR / ".craigslist_state.json"

CL_EMAIL    = os.environ.get("CRAIGSLIST_EMAIL", "")
CL_PASSWORD = os.environ.get("CRAIGSLIST_PASSWORD", "")

# ---------------------------------------------------------------------------
# Ad rotation — 4 variations, cycles weekly
# ---------------------------------------------------------------------------

ADS = [
    {
        "title": "Affordable Websites for Philly Small Businesses — $799, Live in 7 Days",
        "body": """Does your business show up when someone Googles you?

If not, you're losing customers to competitors who do.

I'm Maya, a web designer based in Philadelphia. I build clean, fast, mobile-ready websites for local businesses — salons, restaurants, auto shops, photographers, and more.

✅ Starting at $499
✅ Live in 7 days
✅ Mobile-friendly
✅ Google-ready (basic SEO included)
✅ No calls needed — fill out my form online

See examples and packages at webbymaya.com

Fill out my intake form at webbymaya.com/book — I'll take it from there""",
    },
    {
        "title": "Get Your Philly Business Online — Websites from $799",
        "body": """Your next customer is searching Google right now. Can they find you?

Hi, I'm Maya — a Philadelphia-based web designer helping local businesses get found online. I specialize in small business websites that look great, load fast, and actually bring in customers.

What you get:
→ Custom website built for your business
→ Works perfectly on phones
→ Shows up on Google
→ Done in 7 days
→ Starts at $799

Perfect for: salons, restaurants, mechanics, photographers, gyms, cleaning services, and more.

Check out webbymaya.com or reply here to get started.""",
    },
    {
        "title": "Philadelphia Web Designer — $799 Websites, 7-Day Turnaround",
        "body": """Small businesses in Philly deserve a great website without a huge price tag.

I'm Maya, a local web designer with experience building sites for salons, restaurants, auto shops, fitness studios, and more. Every site I build is:

• Mobile-first (most of your customers are on their phones)
• Fast-loading
• Easy for customers to find on Google
• Priced at $799 — no hidden fees

I've worked with businesses in Philadelphia, South Jersey, and Delaware.

Ready to get online? Fill out my quick intake form at webbymaya.com/book — I'll handle the rest.""",
    },
    {
        "title": "No Website Yet? I'll Build One for Your Philly Business — $799 Flat",
        "body": """If your business doesn't have a website, you're invisible to anyone searching online.

I help Philadelphia small businesses fix that — fast, affordable, and without the tech headache.

Here's how it works:
1. Fill out my short form at webbymaya.com/book
2. I build your site in 7 days
3. You go live — customers can find you, book you, call you

Starting at $799. No monthly fees to me. No surprises.

I work with: nail salons, hair salons, restaurants, cafes, auto repair, landscaping, photography, cleaning services, gyms, and more.

Visit webbymaya.com or reply here — I check messages daily.""",
    },
]

# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"rotation_index": 0, "last_posted": None, "post_count": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def already_posted_this_week(state: dict) -> bool:
    last = state.get("last_posted")
    if not last:
        return False
    last_date = date.fromisoformat(last)
    today = date.today()
    # Same ISO week
    return last_date.isocalendar()[:2] == today.isocalendar()[:2]


def post_to_craigslist(title: str, body: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"\n  [DRY RUN] Would post:\n")
        print(f"  Title: {title}")
        print(f"\n  Body:\n")
        for line in body.splitlines():
            print(f"    {line}")
        return True

    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
    except ImportError:
        sys.exit(
            "Playwright not installed. Run:\n"
            "  pip install playwright && playwright install chromium"
        )

    if not CL_EMAIL or not CL_PASSWORD:
        sys.exit(
            "Craigslist credentials not set. Add to ~/.zshrc:\n"
            "  export CRAIGSLIST_EMAIL='your@email.com'\n"
            "  export CRAIGSLIST_PASSWORD='yourpassword'"
        )

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        try:
            # Log in
            print("  Logging in to Craigslist...")
            page.goto("https://accounts.craigslist.org/login/home", timeout=20000)
            page.wait_for_load_state("networkidle")
            page.fill("input[name='inputEmailHandle']", CL_EMAIL)
            page.fill("input[name='inputPassword']", CL_PASSWORD)
            # Click the "Log in" button (not "E-mail a login link")
            page.locator("button", has_text="Log in").last.click()
            page.wait_for_load_state("networkidle", timeout=15000)

            # Check login succeeded — failed login stays on the login URL
            if "login" in page.url and "rp=" in page.url:
                # Still on login page — check for error message
                err_el = page.query_selector(".error, .alert, #loginError")
                err_msg = err_el.inner_text() if err_el else "Login failed (bad credentials or account doesn't exist)"
                raise Exception(f"Login failed: {err_msg}")
            print("  Logged in.")

            # Start a new post
            page.goto("https://post.craigslist.org/", timeout=20000)

            # Choose posting type: service offered
            page.click("input[value='so']")  # "service offered"
            page.click("button#go")
            page.wait_for_load_state("networkidle")

            # Select Philadelphia
            philly = page.query_selector("a[href*='philadelphia']")
            if philly:
                philly.click()
                page.wait_for_load_state("networkidle")

            # Category: computer
            page.click("text=computer")
            page.wait_for_load_state("networkidle")

            # Fill in the form
            page.fill("input[name='PostingTitle']", title)
            page.fill("textarea[name='PostingBody']", body)

            # Price
            price_field = page.query_selector("input[name='ask']")
            if price_field:
                price_field.fill("799")

            # Continue
            page.click("button#go")
            page.wait_for_load_state("networkidle")

            # Confirm / publish
            confirm = page.query_selector("button#go, input[value='publish']")
            if confirm:
                confirm.click()
                page.wait_for_load_state("networkidle")

            print("  Posted successfully.")
            browser.close()
            return True

        except PWTimeout:
            shot = SCRIPT_DIR / "craigslist_debug.png"
            try:
                page.screenshot(path=str(shot))
                print(f"  [ERROR] Timed out. Screenshot saved: {shot}")
                print(f"  Current URL: {page.url}")
            except Exception:
                print("  [ERROR] Timed out — could not capture screenshot.")
            browser.close()
            return False
        except Exception as e:
            print(f"  [ERROR] {e}")
            browser.close()
            return False


def main():
    parser = argparse.ArgumentParser(description="WebByMaya — post to Craigslist Philadelphia")
    parser.add_argument("--dry-run", action="store_true", help="Preview the ad, don't post")
    parser.add_argument("--force",   action="store_true", help="Post even if already posted this week")
    args = parser.parse_args()

    state = load_state()

    if not args.dry_run and not args.force and already_posted_this_week(state):
        print(f"Already posted this week ({state['last_posted']}). Use --force to post again.")
        return

    idx = state.get("rotation_index", 0) % len(ADS)
    ad  = ADS[idx]

    print(f"\n  WebByMaya — Craigslist Poster")
    print(f"  Ad #{idx + 1} of {len(ADS)}")
    print(f"  Title: {ad['title'][:60]}...")

    success = post_to_craigslist(ad["title"], ad["body"], args.dry_run)

    if success and not args.dry_run:
        state["rotation_index"] = (idx + 1) % len(ADS)
        state["last_posted"]    = date.today().isoformat()
        state["post_count"]     = state.get("post_count", 0) + 1
        save_state(state)
        print(f"  Total posts so far: {state['post_count']}")


if __name__ == "__main__":
    main()
