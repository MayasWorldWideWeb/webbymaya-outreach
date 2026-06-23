"""
One-time Instagram session setup using a real browser.
Logs in via Playwright (real Chromium), saves the sessionid cookie,
then instagram_poster.py uses that cookie forever — no password needed again.

Run: python3 ig_login.py
"""
import json, os, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

USERNAME     = os.environ.get("INSTAGRAM_USERNAME", "webbymaya").lower()
PASSWORD     = os.environ.get("INSTAGRAM_PASSWORD", "")
SESSION_FILE = Path.home() / ".webbymaaya/ig_session.json"
COOKIE_FILE  = Path.home() / ".webbymaaya/ig_cookie.txt"

SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

print("Opening Instagram in a real browser...")
print("If a verification code is needed, enter it in the browser window.\n")

with sync_playwright() as p:
    # Use real installed Chrome — better fingerprint, Instagram trusts it
    try:
        browser = p.chromium.launch(headless=False, slow_mo=400, channel="chrome")
    except Exception:
        browser = p.chromium.launch(headless=False, slow_mo=400)
    ctx = browser.new_context(viewport={"width": 1080, "height": 900})
    page = ctx.new_page()
    page.goto("https://www.instagram.com/accounts/login/", wait_until="networkidle", timeout=30000)
    time.sleep(3)

    def _logged_in(url: str) -> bool:
        blocked = ("login", "challenge", "recaptcha", "auth_platform", "two_factor", "checkpoint")
        return url.startswith("https://www.instagram.com/") and not any(b in url for b in blocked)

    # Dismiss any cookie / consent dialogs
    for label in ["Allow all cookies", "Accept all", "Allow essential and optional cookies",
                  "Only allow essential cookies", "Decline optional cookies"]:
        try:
            page.get_by_role("button", name=label).click(timeout=2000)
            time.sleep(1)
            break
        except Exception:
            pass

    # Wait for the login form — try multiple selectors Instagram has used
    email_sel = None
    for sel in ['input[name="email"]', 'input[name="username"]',
                'input[aria-label="Phone number, username, or email"]',
                'input[type="text"]']:
        try:
            page.wait_for_selector(sel, timeout=5000)
            email_sel = sel
            break
        except Exception:
            pass

    if not email_sel:
        # Already logged in or page changed — check if we're on the home feed
        if _logged_in(page.url):
            print("Already logged in — skipping credential entry.")
        else:
            page.screenshot(path="/tmp/ig_login_state.png")
            print("Could not find login form. Screenshot: /tmp/ig_login_state.png")
            print("Current URL:", page.url)
            browser.close()
            sys.exit(1)
    else:
        time.sleep(1)
        page.locator(email_sel).fill(USERNAME)
        time.sleep(0.5)
        # password field
        pass_sel = 'input[name="pass"]' if page.locator('input[name="pass"]').count() else 'input[type="password"]'
        page.locator(pass_sel).fill(PASSWORD)
        time.sleep(0.5)
        page.keyboard.press("Enter")

    print("Logging in... (if a verification or CAPTCHA window appears, complete it in the browser)")

    # Poll for stable clean URL
    print("Waiting for login to complete...")
    warned    = False
    deadline  = time.time() + 150  # 2.5 min total
    logged_in = False
    while time.time() < deadline:
        time.sleep(1)
        cur = page.url
        if _logged_in(cur):
            time.sleep(2)           # let any redirect finish
            if _logged_in(page.url):
                logged_in = True
                break
        else:
            if not warned and any(b in cur for b in ("recaptcha", "auth_platform", "challenge", "checkpoint")):
                print("\n⚠️  Instagram wants verification (CAPTCHA or code).")
                print("   Complete it in the browser window — the script will continue automatically.\n")
                warned = True

    if not logged_in:
        print("Timed out waiting for login.")
        browser.close()
        sys.exit(1)

    # Dismiss "Save login info?" or "Turn on notifications?"
    for label in ["Save info", "Not now", "Skip", "Not Now"]:
        try:
            page.get_by_role("button", name=label).click(timeout=3000)
            time.sleep(1)
        except Exception:
            pass

    # Extract sessionid from cookies
    cookies = ctx.cookies()
    sessionid = next((c["value"] for c in cookies if c["name"] == "sessionid"), None)
    csrftoken  = next((c["value"] for c in cookies if c["name"] == "csrftoken"),  "")

    if not sessionid:
        page.screenshot(path="/tmp/ig_login_state.png")
        print("Could not find sessionid. Screenshot saved to /tmp/ig_login_state.png")
        print("Current URL:", page.url)
        browser.close()
        sys.exit(1)

    COOKIE_FILE.write_text(sessionid)
    print(f"\nSession saved → {COOKIE_FILE}")

    # Also write a minimal instagrapi-compatible settings file
    settings = {"cookies": {"sessionid": sessionid, "csrftoken": csrftoken}}
    SESSION_FILE.write_text(json.dumps(settings, indent=2))
    print(f"Settings saved → {SESSION_FILE}")

    browser.close()

print("\nDone. Instagram is connected — run instagram_poster.py anytime.")
