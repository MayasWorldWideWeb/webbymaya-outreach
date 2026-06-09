#!/usr/bin/env python3
"""
outreach.py — WebByMaya One-Command Outreach Pipeline
======================================================
Runs the full cold-outreach workflow for a city in one shot:

  1. Find local businesses with no website or a bad/outdated one
  2. Auto-discover contact emails from their websites / social pages
  3. Preview the emails (dry run — nothing sent yet)
  4. Ask for confirmation
  5. Send (up to --limit at a time, 30 s apart to avoid spam filters)

USAGE
-----
  python3 outreach.py --city "Cedar City, UT"
  python3 outreach.py --city "Page, AZ" --radius 5000 --limit 15
  python3 outreach.py --city "St. George, UT" --city "Hurricane, UT" --limit 20
  python3 outreach.py --city "Kanab, UT" --skip-find   # reuse today's CSV

  # Philadelphia by zone (recommended for large cities)
  python3 outreach.py --zone philly-center --no-web-check
  python3 outreach.py --zone philly-north  --no-web-check --limit 30
  python3 outreach.py --zone philly-south  --zip-radius 1500

  # Custom zip codes
  python3 outreach.py --zips "19102,19103,19106,19107" --zip-radius 2000

FLAGS
-----
  --city CITY        City to search (repeatable for multiple cities)
  --zone ZONE        Named zone preset for large cities (e.g. philly-center, philly-north)
  --zips ZIPS        Comma-separated zip codes to search individually
  --zip-city CITY    City label for zip searches (default: auto-detected)
  --zip-radius M     Search radius per zip code in metres (default: 2000)
  --radius METERS    Search radius when using --city (default: 8000 ≈ 5 miles)
  --limit N          Max emails to send this run (default: 20)
  --workers N        Parallel search threads (default: 20)
  --skip-find        Skip the find step and reuse today's existing prospects CSV
  --no-web-check     Skip website checks — faster, only finds no-website businesses
"""

import argparse
import csv
import datetime
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
PYTHON     = sys.executable


# ─────────────────────────────────────────────────────────────────────────────

def banner(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


LOG_FILE = SCRIPT_DIR / "search_output.log"


def run_step(cmd, label):
    """Run a subprocess. Exit the whole pipeline on non-zero return code."""
    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(f"\n[outreach] Pipeline stopped — '{label}' exited with code {result.returncode}.")


def run_find_step(cmd):
    """Run find_prospects.py, printing output live AND writing it to search_output.log."""
    LOG_FILE.write_text("")   # clear previous log
    with open(LOG_FILE, "w", buffering=1) as log:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            print(line, end="", flush=True)
            log.write(line)
        proc.wait()
    if proc.returncode != 0:
        sys.exit(f"\n[outreach] Pipeline stopped — 'find_prospects.py' exited with code {proc.returncode}.")


def count_prospects(csv_path):
    """Return (total, with_email) from the CSV."""
    total = with_email = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            if row.get("email", "").strip():
                with_email += 1
    return total, with_email


# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="WebByMaya — full outreach pipeline for a city",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--city", action="append", metavar="CITY",
        help='City to search, e.g. "Cedar City, UT". Repeatable.',
    )
    # Zip code / zone flags (for large cities like Philadelphia)
    parser.add_argument(
        "--zone", metavar="ZONE",
        help="Named zone preset, e.g. philly-center, philly-north, philly-south, philly-west, philly-northwest, philly-northeast",
    )
    parser.add_argument(
        "--zips", metavar="ZIPS",
        help='Comma-separated zip codes, e.g. "19102,19103,19106"',
    )
    parser.add_argument(
        "--zip-city", metavar="CITY", default=None,
        help='City label for zip searches (default: auto-detected)',
    )
    parser.add_argument(
        "--zip-radius", type=int, default=2000, metavar="METERS",
        help="Search radius per zip code in metres (default: 2000 ≈ 1.25 miles)",
    )
    parser.add_argument(
        "--radius", type=int, default=8000, metavar="METERS",
        help="Search radius when using --city (default: 8000 ≈ 5 miles)",
    )
    parser.add_argument(
        "--limit", type=int, default=20, metavar="N",
        help="Max emails to send this run (default: 20)",
    )
    parser.add_argument(
        "--workers", type=int, default=80, metavar="N",
        help="Parallel search threads (default: 80)",
    )
    parser.add_argument(
        "--skip-find", action="store_true",
        help="Skip the find step and reuse today's existing prospects CSV",
    )
    parser.add_argument(
        "--no-web-check", action="store_true",
        help="Skip website health checks — faster, only finds no-website businesses",
    )
    parser.add_argument(
        "--bad-sites-only", action="store_true",
        help="Only email businesses with a bad/outdated website (dead, parked, soon, social). "
             "Use after --no-web-check pass is done.",
    )
    parser.add_argument(
        "--sms", action="store_true",
        help="After emailing, also text mobile numbers found in the CSV via Twilio.",
    )
    parser.add_argument(
        "--sms-limit", type=int, default=20, metavar="N",
        help="Max texts to send when --sms is used (default: 20)",
    )
    return parser.parse_args()


def main():
    args     = parse_args()
    today    = datetime.date.today().strftime("%Y-%m-%d")
    csv_path = SCRIPT_DIR / f"prospects_{today}.csv"

    # Validate: need at least one of --city, --zone, --zips (unless --skip-find)
    if not args.skip_find and not args.city and not args.zone and not args.zips:
        sys.exit("[outreach] Provide at least one of: --city, --zone, or --zips")

    # Build a human-readable label for display
    if args.zone:
        label = f"zone: {args.zone}"
    elif args.zips:
        label = f"zips: {args.zips}"
    else:
        label = ", ".join(args.city)

    print(f"\n{'='*60}")
    print(f"  WebByMaya Outreach Pipeline")
    print(f"  Target : {label}")
    print(f"  Limit  : {args.limit} emails this run")
    print(f"  Date   : {today}")
    print(f"{'='*60}")

    # ── STEP 1: Find prospects + discover emails ──────────────────────────────
    if args.skip_find:
        if not csv_path.exists():
            sys.exit(f"[outreach] --skip-find set but no CSV found at:\n  {csv_path}")
        banner("STEP 1/3 — Skipping find (reusing existing CSV)")
        print(f"  Using: {csv_path.name}")
    else:
        banner("STEP 1/3 — Finding prospects & discovering emails")
        find_cmd = [PYTHON, str(SCRIPT_DIR / "find_prospects.py")]

        if args.zone:
            find_cmd += ["--zone", args.zone]
            find_cmd += ["--zip-radius", str(args.zip_radius)]
            if args.zip_city:
                find_cmd += ["--zip-city", args.zip_city]
        elif args.zips:
            find_cmd += ["--zips", args.zips]
            find_cmd += ["--zip-radius", str(args.zip_radius)]
            if args.zip_city:
                find_cmd += ["--zip-city", args.zip_city]
        else:
            for city in args.city:
                find_cmd += ["--city", city]
            find_cmd += ["--radius", str(args.radius)]

        find_cmd += ["--workers", str(args.workers)]
        if args.no_web_check:
            find_cmd += ["--no-web-check"]
        run_find_step(find_cmd)

    if not csv_path.exists():
        sys.exit(f"[outreach] Expected output file not found:\n  {csv_path}")

    # ── STEP 1b: Enrich emails for no-website businesses ─────────────────────
    # If we ran --no-web-check, those businesses have no website to scrape so
    # we search the web (DuckDuckGo, Yelp, directories) to find contact emails.
    enrich_path = SCRIPT_DIR / (csv_path.stem + "_enriched.csv")
    active_csv  = csv_path

    if args.no_web_check and not args.skip_find:
        banner("STEP 1b/3 — Enriching emails (searching web for contacts)")
        run_step(
            [PYTHON, str(SCRIPT_DIR / "enrich_emails.py"), "--input", str(csv_path)],
            "enrich_emails.py",
        )
        if enrich_path.exists():
            active_csv = enrich_path
            print(f"  Using enriched CSV: {active_csv.name}")

    total, with_email = count_prospects(active_csv)
    sendable = min(args.limit, with_email)

    website_filter = None
    if args.bad_sites_only:
        website_filter = "bad"
    elif args.no_web_check:
        website_filter = "none"

    print(f"\n  CSV              : {csv_path.name}")
    print(f"  Total prospects  : {total}")
    print(f"  With email       : {with_email}")
    print(f"  Filter           : {'bad/outdated sites only' if website_filter == 'bad' else 'no-website only' if website_filter == 'none' else 'all'}")
    print(f"  Will preview     : {sendable}")

    if with_email == 0:
        print("\n  No prospects with contact emails found. Nothing to send.")
        return

    # ── STEP 2: Preview (dry run) ─────────────────────────────────────────────
    banner(f"STEP 2/3 — Previewing {sendable} email(s)  (nothing sent yet)")
    preview_cmd = [
        PYTHON, str(SCRIPT_DIR / "batch_send_outreach.py"),
        "--input",  str(active_csv),
        "--limit",  str(sendable),
        "--dry-run",
    ]
    if website_filter:
        preview_cmd += ["--website-filter", website_filter]
    run_step(preview_cmd, "batch_send_outreach.py --dry-run")

    # ── STEP 3: Confirm and send ──────────────────────────────────────────────
    banner("STEP 3/3 — Ready to send")
    print(f"  {sendable} email(s) queued  ·  {label}")
    print(f"  Emails are sent 30 seconds apart to stay out of spam.\n")

    try:
        answer = input(f"  Send {sendable} email(s) now? [y/N]: ").strip().lower()
    except (KeyboardInterrupt, EOFError):
        print("\n  Aborted.")
        return

    if answer != "y":
        print("\n  Aborted — no emails sent.")
        return

    send_cmd = [
        PYTHON, str(SCRIPT_DIR / "batch_send_outreach.py"),
        "--input", str(active_csv),
        "--limit", str(sendable),
    ]
    if website_filter:
        send_cmd += ["--website-filter", website_filter]
    run_step(send_cmd, "batch_send_outreach.py")

    print(f"\n{'='*60}")
    print(f"  Done!  {sendable} email(s) sent for: {label}")
    print(f"  Send log: send_log_{today}.csv")
    print(f"{'='*60}\n")

    # ── Optional: SMS outreach ────────────────────────────────────────────────
    if args.sms:
        banner("SMS — Texting mobile numbers")
        run_step(
            [
                PYTHON, str(SCRIPT_DIR / "sms_outreach.py"),
                "--input", str(active_csv),
                "--limit", str(args.sms_limit),
            ],
            "sms_outreach.py",
        )


if __name__ == "__main__":
    main()
