#!/usr/bin/env python3
"""
follow_prospects.py — WebByMaya Instagram Prospect Follower
============================================================
Searches Instagram for businesses from your prospect CSVs and follows
them. Capped at 30/day so Instagram doesn't flag the account.

Businesses that follow back will see your bio and $799 offer —
free passive prospecting on top of the email/SMS outreach.

USAGE:
    python3 follow_prospects.py              # follow up to 30 today
    python3 follow_prospects.py --limit 20   # custom limit
    python3 follow_prospects.py --dry-run    # preview, don't follow
"""

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
STATE_FILE  = SCRIPT_DIR / ".ig_follow_state.json"
SESSION_FILE = Path.home() / ".webbymaaya/ig_session.json"

DEFAULT_LIMIT    = 30   # Instagram safe daily limit for new accounts
DELAY_MIN        = 20   # seconds between follows (min)
DELAY_MAX        = 45   # seconds between follows (max)

BOLD = "\033[1m"
G    = "\033[32m"
Y    = "\033[33m"
DIM  = "\033[2m"
R    = "\033[0m"

import os
IG_USERNAME = os.environ.get("INSTAGRAM_USERNAME", "")
IG_PASSWORD = os.environ.get("INSTAGRAM_PASSWORD", "")


# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"followed": [], "follow_count": 0, "last_run": None}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def load_prospects() -> list:
    """Load all unique businesses from every prospect CSV."""
    seen  = set()
    bizes = []
    for p in sorted(SCRIPT_DIR.glob("prospects_*_enriched.csv"), reverse=True):
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("name", "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                bizes.append({
                    "name":     name,
                    "category": row.get("category", "").strip(),
                    "city":     row.get("city", "Philadelphia, PA").strip(),
                })
    # Also load un-enriched CSVs for any extras
    for p in sorted(SCRIPT_DIR.glob("prospects_*.csv"), reverse=True):
        if "_enriched" in p.name:
            continue
        with open(p, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                name = row.get("name", "").strip()
                if not name or name in seen:
                    continue
                seen.add(name)
                bizes.append({
                    "name":     name,
                    "category": row.get("category", "").strip(),
                    "city":     row.get("city", "Philadelphia, PA").strip(),
                })
    return bizes


COOKIE_FILE = Path.home() / ".webbymaaya/ig_cookie.txt"

def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        sys.exit("instagrapi not installed. Run: pip3 install instagrapi")
    if not COOKIE_FILE.exists():
        sys.exit("No session cookie found. Grab sessionid from Chrome DevTools on instagram.com and save to ~/.webbymaaya/ig_cookie.txt")
    cl = Client()
    cl.login_by_sessionid(COOKIE_FILE.read_text().strip())
    cl.account_info()
    return cl


def find_instagram_account(cl, name: str, city: str):
    """Search Instagram for a business. Returns user_id if found, else None."""
    # Strip city/state clutter from city string for a cleaner search
    city_clean = city.split(",")[0].strip()  # "Philadelphia, PA" → "Philadelphia"
    query = f"{name} {city_clean}"

    try:
        results = cl.search_users(query, count=3)
        if not results:
            return None

        # Score results — prefer accounts whose username or full_name
        # contains words from the business name
        name_words = set(name.lower().split())
        best = None
        best_score = 0

        for user in results:
            uname  = (user.username or "").lower()
            fname  = (user.full_name or "").lower()
            combined = uname + " " + fname

            score = sum(1 for w in name_words if len(w) > 3 and w in combined)

            # Penalise huge accounts — local businesses have < 50k followers
            if user.follower_count and user.follower_count > 50000:
                score -= 2

            if score > best_score:
                best_score = score
                best = user

        # Only follow if at least one name word matched
        if best and best_score >= 1:
            # Skip accounts that already have a website URL in their bio
            # — they have a site and don't need ours
            if getattr(best, "external_url", None):
                return None
            return str(best.pk)

    except Exception:
        pass

    return None


def main():
    parser = argparse.ArgumentParser(description="WebByMaya — follow Philly businesses on Instagram")
    parser.add_argument("--limit",   type=int, default=DEFAULT_LIMIT,
                        help=f"Max follows per run (default: {DEFAULT_LIMIT})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Search and preview, don't actually follow")
    args = parser.parse_args()

    state     = load_state()
    followed  = set(state.get("followed", []))
    prospects = load_prospects()

    # Filter out already-followed
    to_process = [b for b in prospects if b["name"] not in followed]

    print(f"\n  {BOLD}WebByMaya — Instagram Prospect Follower{R}")
    print(f"  {DIM}Prospects loaded: {len(prospects)}  |  Already followed: {len(followed)}  |  Remaining: {len(to_process)}{R}\n")

    if not to_process:
        print(f"  {Y}All prospects already followed. Run after next outreach batch.{R}")
        return

    if args.dry_run:
        print(f"  {DIM}DRY RUN — showing first {args.limit} searches, nothing will be followed{R}\n")

    cl = None if args.dry_run else get_client()

    followed_today = 0
    skipped        = 0
    not_found      = 0

    for biz in to_process:
        if followed_today >= args.limit:
            break

        name     = biz["name"]
        category = biz["category"]
        city     = biz["city"]

        print(f"  [{followed_today + 1}/{args.limit}] {name}  ({category})")

        if args.dry_run:
            print(f"  {DIM}Would search: \"{name} {city.split(',')[0]}\"{R}")
            followed_today += 1
            continue

        user_id = find_instagram_account(cl, name, city)

        if not user_id:
            print(f"  {DIM}Not found on Instagram — skipped{R}")
            not_found += 1
            followed.add(name)  # Mark so we don't search again
            continue

        try:
            cl.user_follow(user_id)
            print(f"  {G}Followed ✓{R}")
            followed.add(name)
            followed_today += 1

            # Save state after each follow in case script is interrupted
            state["followed"]      = list(followed)
            state["follow_count"]  = state.get("follow_count", 0) + 1
            state["last_run"]      = __import__("datetime").date.today().isoformat()
            save_state(state)

            if followed_today < args.limit:
                delay = random.randint(DELAY_MIN, DELAY_MAX)
                print(f"  {DIM}Waiting {delay}s...{R}")
                time.sleep(delay)

        except Exception as e:
            err = str(e)
            if "feedback_required" in err or "block" in err.lower():
                print(f"  {Y}Instagram rate-limited — stopping for today.{R}")
                break
            print(f"  {Y}Error: {err[:80]}{R}")
            skipped += 1

    print(f"\n  {'─'*44}")
    if args.dry_run:
        print(f"  Dry run — {followed_today} would be searched.")
    else:
        print(f"  Done — {followed_today} followed, {not_found} not on Instagram, {skipped} errors.")
        print(f"  All-time follows: {state.get('follow_count', 0)}")


if __name__ == "__main__":
    main()
