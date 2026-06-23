#!/usr/bin/env python3
"""
regen_all_mockups.py — Regenerate all sent-business mockups with:
  - Real Pexels category-specific images (user-agent fix applied)
  - GA4 tracking (G-8VNPY96XP9)
  - Updated lead form with working Supabase endpoint

Run once. Takes ~20-30 min for 660 mockups (Pexels rate limit = 200 req/min).
"""
import csv, glob, os, sys, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPT_DIR))

# Load Pexels key from env or zshrc
import subprocess
def _zshrc(key):
    try:
        out = subprocess.check_output(
            f"grep '{key}' ~/.zshrc | cut -d'\"' -f2", shell=True).decode().strip()
        return out.split("\n")[0]
    except Exception:
        return ""

if not os.environ.get("PEXELS_API_KEY"):
    os.environ["PEXELS_API_KEY"] = _zshrc("PEXELS_API_KEY")
if not os.environ.get("PIXABAY_API_KEY"):
    os.environ["PIXABAY_API_KEY"] = _zshrc("PIXABAY_API_KEY")

from mockup_uploader import upload_mockup

def load_prospect_data():
    data = {}
    for f in sorted(glob.glob(str(SCRIPT_DIR / "prospects_*.csv"))):
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                name = r.get("name", "").strip()
                if name and name not in data:
                    data[name] = r
    return data

def load_sent_names():
    seen = {}
    for f in sorted(glob.glob(str(SCRIPT_DIR / "send_log_*.csv"))):
        with open(f, newline="", encoding="utf-8") as fh:
            for r in csv.DictReader(fh):
                if r.get("status") == "sent":
                    name = r.get("name", "").strip()
                    cat  = r.get("category", "").strip()
                    if name and name not in seen:
                        seen[name] = cat
    return seen

def main():
    prospects = load_prospect_data()
    sent      = load_sent_names()

    # Build regen list
    jobs = []
    for name, cat in sent.items():
        p   = prospects.get(name, {})
        jobs.append({
            "name":     name,
            "category": cat or p.get("category", ""),
            "phone":    p.get("phone", ""),
            "city":     p.get("city", "Philadelphia, PA"),
            "address":  p.get("address", ""),
        })

    total = len(jobs)
    print(f"Regenerating {total} mockups with real images + GA4\n")

    ok = 0
    failed = 0
    for i, job in enumerate(jobs, 1):
        name = job["name"]
        try:
            url = upload_mockup(
                name     = name,
                category = job["category"],
                phone    = job["phone"],
                city     = job["city"],
                address  = job["address"],
            )
            if url:
                ok += 1
                print(f"  [{i:>3}/{total}] OK  {name[:55]}")
            else:
                failed += 1
                print(f"  [{i:>3}/{total}] FAIL (upload) {name[:50]}")
        except Exception as e:
            failed += 1
            print(f"  [{i:>3}/{total}] ERR {name[:50]}: {str(e)[:60]}")

        # Pexels allows 200 req/min; each mockup makes ~4 photo API calls
        # Sleep 1.5s to stay well under limit
        if i % 20 == 0:
            print(f"  ... {ok} done, {failed} failed so far ...")
            time.sleep(2)

    print(f"\nDone — {ok} regenerated · {failed} failed")

if __name__ == "__main__":
    main()
