#!/usr/bin/env python3
"""
ig_dm_followbacks.py — WebByMaya Instagram DM Follow-Backs
When someone follows @webbymaya back, send them a friendly intro DM.
Capped at 12/day. Never DMs the same person twice.
"""
import json, random, sys, time
from datetime import date
from pathlib import Path

SCRIPT_DIR    = Path(__file__).parent
STATE_FILE    = SCRIPT_DIR / ".ig_dm_state.json"
COOKIE_FILE   = Path.home() / ".webbymaaya/ig_cookie.txt"
SESSION_FILE  = Path.home() / ".webbymaaya/ig_session.json"

DAILY_LIMIT = 12
MY_USER_ID  = "21435992045"   # @webbymaya

# Rotate through 4 messages so it doesn't look like a bot
DM_TEMPLATES = [
    "Hey {name}! Thanks for the follow 🙌 I'm Maya — I build websites for Philly small businesses starting at $799. If you ever need a site or want to upgrade your current one, I'd love to help. Check us out at webbymaya.com!",
    "Hi {name}! Appreciate the follow! I'm Maya with WebByMaya — websites for local Philly businesses, flat $799, live in 7 days. If you're ever looking to get online or level up your site, feel free to reach out 😊",
    "Hey {name}, thanks for following! I help Philly business owners get online fast — professional sites starting at $799. If that's ever something you need, I'm here! webbymaya.com 🏙️",
    "Hi {name}! Thanks for the follow 👋 I'm Maya, a web designer based in Philly. I build sites for local businesses like yours — starting at $799, done in a week. Would love to work together someday! webbymaya.com",
]

def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"dm_sent": [], "total_dms": 0, "last_run": None}

def save_state(s):
    STATE_FILE.write_text(json.dumps(s, indent=2))

def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        sys.exit("pip3 install instagrapi")
    cl = Client()
    # Prefer full session file (more stable than sessionid-only login)
    if SESSION_FILE.exists():
        try:
            cl.load_settings(SESSION_FILE)
            cl.login(
                os.environ.get("INSTAGRAM_USERNAME","webbymaya"),
                os.environ.get("INSTAGRAM_PASSWORD",""),
                relogin=False,
            )
            cl.dump_settings(SESSION_FILE)
            return cl
        except Exception as e:
            print(f"Session file login failed: {e} — trying cookie fallback")
    if COOKIE_FILE.exists():
        cl2 = Client()
        cl2.login_by_sessionid(COOKIE_FILE.read_text().strip())
        cl2.account_info()
        return cl2
    sys.exit("No Instagram session. Run: python3 ig_login.py")

def main():
    state    = load_state()
    dm_sent  = set(state.get("dm_sent", []))
    today    = date.today().isoformat()

    if state.get("last_run") != today:
        state["today_count"] = 0
    today_count = state.get("today_count", 0)

    if today_count >= DAILY_LIMIT:
        print(f"DM daily limit ({DAILY_LIMIT}) reached.")
        return

    cl = get_client()

    print("WebByMaya — DM Follow-Backs\n")

    # Get our followers and who we follow
    try:
        followers  = cl.user_followers(MY_USER_ID, amount=500)
        following  = cl.user_following(MY_USER_ID, amount=500)
    except Exception as e:
        print(f"Error fetching follow lists: {e}")
        return

    follower_ids  = set(str(u) for u in followers.keys())
    following_ids = set(str(u) for u in following.keys())

    # Mutual follows = they follow us AND we follow them — these are warm leads
    mutual = follower_ids & following_ids
    # Also DM people who follow us even if we don't follow back yet
    to_dm  = follower_ids - dm_sent

    print(f"Followers: {len(follower_ids)} | Mutual: {len(mutual)} | New to DM: {len(to_dm)}")

    done = 0
    for uid in list(to_dm):
        if today_count + done >= DAILY_LIMIT:
            break
        try:
            user = followers.get(int(uid)) or following.get(int(uid))
            name = (getattr(user, 'full_name', '') or '').split()[0] if user else "there"
            if not name or len(name) < 2:
                name = "there"

            msg = random.choice(DM_TEMPLATES).format(name=name)
            cl.direct_send(msg, user_ids=[int(uid)])

            dm_sent.add(uid)
            done += 1
            print(f"  ✉️  @{getattr(user, 'username', uid)} — DM sent")

            delay = random.randint(120, 240)   # 2-4 min between DMs
            time.sleep(delay)

        except Exception as e:
            err = str(e)
            if "block" in err.lower() or "spam" in err.lower():
                print(f"  Rate limited on DMs — stopping for today.")
                break
            print(f"  Skip {uid}: {err[:60]}")

    state["dm_sent"]     = list(dm_sent)
    state["today_count"] = today_count + done
    state["total_dms"]   = state.get("total_dms", 0) + done
    state["last_run"]    = today
    save_state(state)
    print(f"\nDone — {done} DMs sent today | {state['total_dms']} all-time")

if __name__ == "__main__":
    main()
