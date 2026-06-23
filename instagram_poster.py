#!/usr/bin/env python3
"""
instagram_poster.py — WebByMaya Instagram Auto-Poster
======================================================
Posts 3x/week (Mon/Wed/Fri) to the WebByMaya Instagram account.
Rotates through 12 captions targeting Philly small business owners.
Uses instagrapi — no Facebook/Meta developer account needed.

USAGE:
    python3 instagram_poster.py              # post today's caption
    python3 instagram_poster.py --dry-run    # preview without posting
    python3 instagram_poster.py --force      # post even if already posted today
"""

import argparse
import json
import os
import sys
import textwrap
from datetime import date
from pathlib import Path

SCRIPT_DIR    = Path(__file__).parent
STATE_FILE    = SCRIPT_DIR / ".instagram_state.json"
SESSION_FILE  = Path.home() / ".webbymaaya/ig_session.json"

IG_USERNAME   = os.environ.get("INSTAGRAM_USERNAME", "")
IG_PASSWORD   = os.environ.get("INSTAGRAM_PASSWORD", "")

# Image to post alongside the caption (a branded static image on the site)
# instagrapi requires an image for feed posts. We use a local branded graphic.
IMAGE_PATH    = SCRIPT_DIR / "ig_post_image.jpg"

# ---------------------------------------------------------------------------
# Caption rotation — 12 posts, cycles every 4 weeks (3x/week)
# ---------------------------------------------------------------------------

CAPTIONS = [
    """Does your Philly business show up on Google? 📍

If someone searches for your type of business right now, will they find you — or your competitor?

I build affordable websites for local businesses in Philadelphia, South Jersey, and Delaware. Starting at $799, live in 7 days.

👉 Link in bio

#PhillySmallBusiness #WebDesign #Philadelphia #SmallBizPhilly #WebbyMaya""",

    """Your customers are searching online. Are you there? 💻

Most small businesses lose customers every day because they have no website — or a bad one.

I fix that. Clean, fast, mobile-ready sites for Philly businesses — flat $799, done in a week.

Fill out my intake form → link in bio

#PhillyBusiness #WebDesigner #LocalBusiness #Philly #SmallBusiness""",

    """Philly salon owners — this one's for you 💅

Your clients are searching "nail salon near me" right now. If you don't have a website, you're invisible.

I build websites specifically for salons in the Philly area. Starting at $799.

See what you'd get → link in bio

#PhillySalon #NailSalon #HairSalon #PhillyBeauty #WebDesign""",

    """Restaurant with no website? You're leaving money on the table. 🍽️

People Google restaurants before they go. If you're not showing up, they're going somewhere else.

I build restaurant websites for Philly eateries — menu, hours, location, and more. From $799.

Link in bio

#PhillyRestaurant #PhillyFood #RestaurantOwner #PhillyEats #SmallBizPhilly""",

    """Behind every great small business is someone working twice as hard 💪

To every Philly shop owner, salon, mechanic, restaurant, and photographer grinding daily — you deserve to be found online.

A website shouldn't cost a fortune. Mine start at $799 and go live in 7 days.

Let's get you out there → link in bio

#PhillyBusiness #Entrepreneur #SmallBusiness #Philadelphia #Hustle""",

    """Auto shop owners in Philly 🔧

When someone's car breaks down and they Google "auto repair near me," is your shop coming up?

I build websites for local mechanics and auto shops. Fast, affordable, shows up on Google.

Starting at $799 → link in bio

#PhillyAutoRepair #AutoShop #Mechanic #PhillyBusiness #WebDesign""",

    """The #1 thing I hear from Philly business owners:

"I know I need a website, I just haven't gotten around to it."

I make it easy. You answer a few questions, I handle everything, you go live in 7 days. Starting at $799.

Fill out my intake form → link in bio

#PhillySmallBusiness #WebsiteDesign #LocalBusiness #PhillyEntrepreneur""",

    """Free tip for Philly small business owners 💡

Google your business name right now. What comes up?

If it's nothing — or a Yelp page you didn't set up — you need a website.

I build them for $799. Takes a week. You keep full ownership.

More info → link in bio

#GoogleMyBusiness #WebDesign #Philadelphia #SmallBusiness #SEO""",

    """South Jersey business owners 👋

Cherry Hill, Camden, Voorhees, Mount Laurel — I've got you covered too.

Same quality websites as Philly, same $799 price, same 7-day turnaround.

Link in bio

#SouthJersey #CherryHill #CamdenNJ #SmallBusiness #WebDesign""",

    """What does a $799 website actually get you? 🤔

✅ Custom design built for your business
✅ Works on phones (where your customers are)
✅ Shows up on Google
✅ Your domain, your hosting — you own it
✅ Live in 7 days

No monthly payments to me. No fluff.

See examples → link in bio

#WebDesign #Philly #SmallBusiness #Affordable #WebbyMaya""",

    """Photographers in Philly — your work deserves to be seen 📸

A Facebook page is not a portfolio. A website is.

I build photography websites that show off your work, get you inquiries, and rank on Google. From $799.

Link in bio

#PhillyPhotographer #PhotographyWebsite #PhillyPhotography #WebDesign #Freelancer""",

    """Delaware small businesses — don't sleep on this 🙌

Wilmington, Newark, Dover — I cover all of Delaware too.

If your business doesn't have a website, I can fix that in 7 days for $799.

Free consultation → link in bio

#DelawareBusiness #Wilmington #SmallBusiness #WebDesign #WebbyMaya""",
]

# ---------------------------------------------------------------------------

def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"caption_index": 0, "last_posted": None, "post_count": 0}


def save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def already_posted_today(state: dict) -> bool:
    return state.get("last_posted") == date.today().isoformat()


COOKIE_FILE = Path.home() / ".webbymaaya/ig_cookie.txt"

def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        sys.exit("instagrapi not installed. Run: pip3 install instagrapi")

    cl = Client()
    SESSION_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Preferred: login via session cookie (no bot detection)
    if COOKIE_FILE.exists():
        sessionid = COOKIE_FILE.read_text().strip()
        if sessionid:
            try:
                cl.login_by_sessionid(sessionid)
                print("  Logged in via session cookie.")
                return cl
            except Exception as e:
                print(f"  Session expired ({e}). Re-run ig_login.py to refresh.")
                sys.exit(1)

    # Fallback: session settings file
    if SESSION_FILE.exists():
        try:
            cl.load_settings(str(SESSION_FILE))
            sessionid = cl.settings.get("cookies", {}).get("sessionid", "")
            if sessionid:
                cl.login_by_sessionid(sessionid)
                print("  Logged in via saved settings.")
                return cl
        except Exception:
            SESSION_FILE.unlink(missing_ok=True)

    print("\n  No session found.")
    print("  Run this once to connect Instagram:")
    print("    python3 ig_login.py")
    sys.exit(1)


def ensure_image() -> Path:
    """Create a simple branded image if none exists."""
    if IMAGE_PATH.exists():
        return IMAGE_PATH

    try:
        from PIL import Image, ImageDraw, ImageFont
        img  = Image.new("RGB", (1080, 1080), color=(0, 0, 0))
        draw = ImageDraw.Draw(img)
        # White text centered
        lines = ["WebByMaya", "webbymaya.com", "$799 · 7 Days · Philly"]
        y = 400
        for line in lines:
            draw.text((540, y), line, fill=(255, 255, 255), anchor="mm")
            y += 80
        img.save(str(IMAGE_PATH), "JPEG")
        print(f"  Created branded image: {IMAGE_PATH}")
    except ImportError:
        # Pillow not available — create a minimal valid JPEG
        # 1x1 black pixel JPEG
        jpeg_bytes = (
            b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00'
            b'\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t'
            b'\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a'
            b'\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\x1e'
            b'\x1b\x1b\x1b\x1b\x1b\x1b\xff\xc0\x00\x0b\x08\x00\x01\x00\x01'
            b'\x01\x01\x11\x00\xff\xc4\x00\x1f\x00\x00\x01\x05\x01\x01\x01'
            b'\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x01\x02\x03\x04'
            b'\x05\x06\x07\x08\t\n\x0b\xff\xc4\x00\xb5\x10\x00\x02\x01\x03'
            b'\x03\x02\x04\x03\x05\x05\x04\x04\x00\x00\x01}\x01\x02\x03\x00'
            b'\x04\x11\x05\x12!1A\x06\x13Qa\x07"q\x142\x81\x91\xa1\x08#B'
            b'\xb1\xc1\x15R\xd1\xf0$3br\x82\t\n\x16\x17\x18\x19\x1a%&\'()*'
            b'456789:CDEFGHIJSTUVWXYZcdefghijstuvwxyz\x83\x84\x85\x86\x87'
            b'\x88\x89\x8a\x92\x93\x94\x95\x96\x97\x98\x99\x9a\xa2\xa3\xa4'
            b'\xa5\xa6\xa7\xa8\xa9\xaa\xb2\xb3\xb4\xb5\xb6\xb7\xb8\xb9\xba'
            b'\xc2\xc3\xc4\xc5\xc6\xc7\xc8\xc9\xca\xd2\xd3\xd4\xd5\xd6\xd7'
            b'\xd8\xd9\xda\xe1\xe2\xe3\xe4\xe5\xe6\xe7\xe8\xe9\xea\xf1\xf2'
            b'\xf3\xf4\xf5\xf6\xf7\xf8\xf9\xfa\xff\xda\x00\x08\x01\x01\x00'
            b'\x00?\x00\xfb\xd4P\x00\x00\x00\x00\x1f\xff\xd9'
        )
        IMAGE_PATH.write_bytes(jpeg_bytes)

    return IMAGE_PATH


def publish_post(caption: str, dry_run: bool) -> bool:
    if dry_run:
        print(f"\n  [DRY RUN] Caption #{load_state().get('caption_index', 0) + 1}:\n")
        for line in caption.splitlines()[:10]:
            print(f"    {line}")
        print("    ...")
        return True

    cl    = get_client()
    cl.account_info()   # populate session state
    image = ensure_image()

    print("  Uploading...")
    upload_id, width, height = cl.photo_rupload(Path(str(image)))
    print("  Configuring post...")
    result = cl.photo_configure(upload_id, width=width, height=height, caption=caption)
    media  = result.get("media", result) if isinstance(result, dict) else result
    code   = media.get("code") if isinstance(media, dict) else getattr(media, "code", "")
    print(f"  Posted! https://www.instagram.com/p/{code}/")
    return True


def main():
    parser = argparse.ArgumentParser(description="WebByMaya — Instagram auto-poster")
    parser.add_argument("--dry-run", action="store_true", help="Preview caption, don't post")
    parser.add_argument("--force",   action="store_true", help="Post even if already posted today")
    args = parser.parse_args()

    state = load_state()

    if not args.dry_run and not args.force and already_posted_today(state):
        print(f"Already posted today ({state['last_posted']}). Use --force to post again.")
        return

    idx     = state.get("caption_index", 0) % len(CAPTIONS)
    caption = CAPTIONS[idx]

    print(f"\n  WebByMaya — Instagram Poster")
    print(f"  Caption {idx + 1} of {len(CAPTIONS)}")

    success = publish_post(caption, args.dry_run)

    if success and not args.dry_run:
        state["caption_index"] = (idx + 1) % len(CAPTIONS)
        state["last_posted"]   = date.today().isoformat()
        state["post_count"]    = state.get("post_count", 0) + 1
        save_state(state)
        print(f"  Total posts: {state['post_count']}")


if __name__ == "__main__":
    main()
