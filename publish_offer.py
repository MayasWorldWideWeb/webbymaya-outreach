#!/usr/bin/env python3
"""
publish_offer.py — publish the live offer JSON that every preview reads.

Every generated preview fetches this file at view-time (data-offer / data-offer-href
hooks in the mockup template), so changing the offer here updates ALL previews —
past and future — with NO regeneration. offer.py stays the single source of truth;
this just mirrors it to a public URL the static previews can read.

    python3 publish_offer.py            # regenerate offer.json + push
    python3 publish_offer.py --dry-run  # print it, don't push

Run it whenever offer.py changes (also wired into run_daily.sh).
"""
import argparse, json, subprocess, sys
from pathlib import Path

import offer
from mockup_uploader import GITHUB_REPO, GITHUB_REPO_PATH, GITHUB_PAGES_BASE

OFFER_JSON = {
    "price":    offer.PRICE,
    "checkout": offer.CHECKOUT_URL,
    "monthly":  offer.MONTHLY,
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    content = json.dumps(OFFER_JSON, indent=2)
    print(content)
    if args.dry_run:
        return

    repo = Path(GITHUB_REPO_PATH)
    if not (repo / ".git").exists():
        subprocess.run(["git", "clone", f"https://github.com/{GITHUB_REPO}.git", str(repo)],
                       capture_output=True, check=True)
    (repo / "offer.json").write_text(content, encoding="utf-8")
    subprocess.run(["git", "-C", str(repo), "add", "offer.json"], capture_output=True, check=True)
    r = subprocess.run(["git", "-C", str(repo), "commit", "-m", "update offer.json"],
                       capture_output=True, text=True)
    if "nothing to commit" in r.stdout:
        print("offer.json already current — nothing to push.")
        return
    subprocess.run(["git", "-C", str(repo), "push"], capture_output=True, check=True)
    print(f"Published: {GITHUB_PAGES_BASE}/offer.json")


if __name__ == "__main__":
    main()
