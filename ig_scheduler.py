#!/usr/bin/env python3
"""
WebByMaya Instagram Scheduler
Reads ig_queue/schedule.json and posts when scheduled_at time is reached.
Run by launchd every minute.
"""
import json, sys, time
from datetime import datetime
from pathlib import Path

QUEUE_DIR    = Path(__file__).parent / "ig_queue"
SCHEDULE     = QUEUE_DIR / "schedule.json"
COOKIE_FILE  = Path.home() / ".webbymaaya/ig_cookie.txt"
LOG          = QUEUE_DIR / "scheduler.log"

def log(msg):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

def get_client():
    try:
        from instagrapi import Client
    except ImportError:
        log("ERROR: instagrapi not installed")
        sys.exit(1)
    if not COOKIE_FILE.exists():
        log("ERROR: No session cookie. Run ig_login.py first.")
        sys.exit(1)
    sessionid = COOKIE_FILE.read_text().strip()
    cl = Client()
    cl.login_by_sessionid(sessionid)
    cl.account_info()
    return cl

def post_photo(cl, path: Path, caption: str):
    upload_id, width, height = cl.photo_rupload(path)
    result = cl.photo_configure(upload_id, width=width, height=height, caption=caption)
    media  = result.get("media", result) if isinstance(result, dict) else result
    code   = media.get("code") if isinstance(media, dict) else getattr(media, "code", "")
    return f"https://www.instagram.com/p/{code}/"

def post_video(cl, path: Path, caption: str):
    # Generate thumbnail from first frame
    thumb_path = path.parent / (path.stem + "_thumb.jpg")
    try:
        import subprocess
        subprocess.run([
            "ffmpeg", "-y", "-i", str(path), "-ss", "00:00:00",
            "-vframes", "1", "-q:v", "2", str(thumb_path)
        ], capture_output=True)
    except Exception:
        thumb_path = None

    media = cl.video_upload(
        path, caption=caption,
        thumbnail=thumb_path if thumb_path and thumb_path.exists() else None
    )
    code = getattr(media, "code", "") or (media.get("code") if isinstance(media, dict) else "")
    if thumb_path and thumb_path.exists():
        thumb_path.unlink(missing_ok=True)
    return f"https://www.instagram.com/p/{code}/"

def post_to_story(cl, path: Path, post_type: str):
    """Repost a feed image/video to story."""
    try:
        if post_type == "video":
            cl.video_upload_to_story(path)
        else:
            cl.photo_upload_to_story(path)
        return True
    except Exception as e:
        log(f"  Story repost failed: {e}")
        return False

def run():
    if not SCHEDULE.exists():
        log("No schedule.json found — nothing to do.")
        return

    schedule = json.loads(SCHEDULE.read_text())
    now      = datetime.now()
    due      = [p for p in schedule
                if p["status"] == "pending"
                and datetime.strptime(p["scheduled_at"], "%Y-%m-%d %H:%M") <= now]

    if not due:
        return   # nothing due yet — silent exit

    cl = get_client()
    changed = False

    for post in due:
        path = QUEUE_DIR / post["file"]
        if not path.exists():
            log(f"SKIP {post['file']} — file not found")
            post["status"] = "error"
            changed = True
            continue

        log(f"Posting {post['file']} ({post['type']})...")
        try:
            if post["type"] == "photo":
                url = post_photo(cl, path, post["caption"])
            else:
                url = post_video(cl, path, post["caption"])
            log(f"Posted! {url}")
            post["status"] = "posted"
            post["posted_at"] = now.strftime("%Y-%m-%d %H:%M:%S")
            post["url"] = url
            # Also repost to story
            time.sleep(5)
            if post_to_story(cl, path, post["type"]):
                log(f"  Reposted to story.")
        except Exception as e:
            log(f"ERROR posting {post['file']}: {e}")
            post["status"] = "error"
            post["error"] = str(e)
        changed = True
        time.sleep(10)   # brief pause between posts

    if changed:
        SCHEDULE.write_text(json.dumps(schedule, indent=2))

if __name__ == "__main__":
    run()
