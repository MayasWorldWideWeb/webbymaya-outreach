#!/usr/bin/env python3
"""
ig_hashtag_liker.py — WebByMaya Instagram Hashtag Engagement
Like posts from Philly business hashtags to get on local radar.
Capped at 100/day. Skips already-liked posts.
"""
import json, random, sys, time
from datetime import date
from pathlib import Path

SCRIPT_DIR  = Path(__file__).parent
STATE_FILE  = SCRIPT_DIR / ".ig_liker_state.json"
COOKIE_FILE = Path.home() / ".webbymaaya/ig_cookie.txt"

DAILY_LIMIT = 100
DELAY_MIN   = 18
DELAY_MAX   = 40

HASHTAGS = [
    "phillybusiness",
    "phillysmallbusiness",
    "shopphilly",
    "phillybiz",
    "phillyentrepreneur",
    "supportlocalphilly",
    "phillyrestaurant",
    "phillysalon",
    "phillybarber",
    "phillyfood",
    "southphilly",
    "northphilly",
    "westphilly",
    "fishtown",
    "southstreetphilly",
    "madeInphilly",
]

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"liked_ids": [], "total_likes": 0, "last_run": None}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))

def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        sys.exit("pip3 install instagrapi")
    if not COOKIE_FILE.exists():
        sys.exit("No session cookie. Save sessionid to ~/.webbymaaya/ig_cookie.txt")
    cl = Client()
    cl.login_by_sessionid(COOKIE_FILE.read_text().strip())
    cl.account_info()
    return cl

def main():
    state    = load_state()
    liked    = set(state.get("liked_ids", []))
    today    = date.today().isoformat()

    # Reset daily count if new day
    if state.get("last_run") != today:
        state["today_count"] = 0

    today_count = state.get("today_count", 0)
    if today_count >= DAILY_LIMIT:
        print(f"Daily limit ({DAILY_LIMIT}) already reached today.")
        return

    cl     = get_client()
    done   = 0
    random.shuffle(HASHTAGS)

    print(f"WebByMaya — Hashtag Liker | target: {DAILY_LIMIT - today_count} likes\n")

    for tag in HASHTAGS:
        if today_count + done >= DAILY_LIMIT:
            break
        try:
            medias = cl.hashtag_medias_recent(tag, amount=20)
            random.shuffle(medias)
            for media in medias:
                if today_count + done >= DAILY_LIMIT:
                    break
                mid = str(media.id)
                if mid in liked:
                    continue
                # Skip our own posts and huge accounts (not local)
                if str(media.user.pk) == "21435992045":
                    continue
                if media.user.follower_count and media.user.follower_count > 100_000:
                    continue
                try:
                    cl.media_like(mid)
                    liked.add(mid)
                    done += 1
                    print(f"  ❤️  @{media.user.username} — #{tag}")
                    delay = random.randint(DELAY_MIN, DELAY_MAX)
                    time.sleep(delay)
                except Exception as e:
                    if "block" in str(e).lower() or "feedback" in str(e).lower():
                        print("  Rate limited — stopping.")
                        state["liked_ids"]   = list(liked)
                        state["today_count"] = today_count + done
                        state["total_likes"] = state.get("total_likes", 0) + done
                        state["last_run"]    = today
                        save_state(state)
                        return
        except Exception as e:
            print(f"  Error on #{tag}: {e}")
        time.sleep(random.randint(5, 12))

    state["liked_ids"]   = list(liked)[-5000:]  # keep last 5k to avoid file bloat
    state["today_count"] = today_count + done
    state["total_likes"] = state.get("total_likes", 0) + done
    state["last_run"]    = today
    save_state(state)
    print(f"\nDone — {done} likes today | {state['total_likes']} all-time")

if __name__ == "__main__":
    main()
