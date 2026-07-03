#!/usr/bin/env python3
"""
recontact_send.py — Re-send to businesses whose first contact went through the
broken Brevo #1 (never delivered). Reuses batch_send_outreach's send_email
(fixed provider order → Brevo #2 / SendGrid), verify_mailbox, and suppression.
Reuses the EXISTING preview mockups (no regeneration). Logs to today's send_log.

Usage: python3 recontact_send.py --input <csv> --limit N [--delay 0.5]
"""
import argparse, csv, datetime, importlib.util, time
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent


def load_bso():
    spec = importlib.util.spec_from_file_location("bso", SCRIPT_DIR / "batch_send_outreach.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--limit", type=int, default=250)
    ap.add_argument("--delay", type=float, default=0.4)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    m = load_bso()
    today = datetime.date.today().strftime("%Y-%m-%d")
    log_path = SCRIPT_DIR / f"send_log_{today}.csv"

    # emails already handled today (so re-runs don't double-send)
    done_today = set()
    if log_path.exists():
        for r in csv.DictReader(open(log_path, errors="replace")):
            if r.get("status") == "sent":
                done_today.add((r.get("email_sent_to") or "").strip().lower())

    rows = list(csv.DictReader(open(args.input, errors="replace")))
    print(f"Re-contact pool: {len(rows)} | limit today: {args.limit} | verify: on")

    header = ["timestamp", "name", "category", "email_sent_to", "subject", "status", "mockup_url", "notes"]
    new_log = not log_path.exists()
    out = open(log_path, "a", newline="")
    w = csv.writer(out)
    if new_log:
        w.writerow(header)

    sent = skipped = failed = 0
    for r in rows:
        if sent >= args.limit:
            print(f"\nDaily limit reached ({args.limit}). Stopping.")
            break
        name = (r.get("name") or "").strip()
        category = (r.get("category") or "").strip()
        email = (r.get("email") or "").strip()
        mockup = (r.get("mockup_url") or "").strip()
        el = email.lower()
        ts = datetime.datetime.now().isoformat(timespec="seconds")

        # --- guards (mirror batch_send) ---
        if not email or "@" not in email:
            continue
        if el in done_today:
            continue
        if email.split("@")[-1].lower() in m.SKIP_DOMAINS:
            w.writerow([ts, name, category, email, "", "skipped", "", "platform email"]); skipped += 1; continue
        if el in m.SUPPRESSED_EMAILS:
            w.writerow([ts, name, category, email, "", "skipped", "", "suppressed/bounced"]); skipped += 1; continue
        valid, reason = m.validate_email(email)
        if not valid:
            w.writerow([ts, name, category, email, "", "skipped", "", f"invalid: {reason}"]); skipped += 1; continue
        ok_mb, vr = m.verify_mailbox(email)
        if not ok_mb:
            m.SUPPRESSED_EMAILS.add(el)
            w.writerow([ts, name, category, email, "", "skipped", "", f"bad mailbox: {vr}"]); skipped += 1; continue

        subject = m.get_subject(name, category)
        plain, html = m.build_email_body(name, category, mockup_url=mockup, to_email=email)

        if args.dry_run:
            print(f"  [dry] {email:38s} | {subject[:50]}")
            sent += 1
            continue

        success, prov = m.send_email(email, subject, plain, html)
        if success:
            done_today.add(el)
            w.writerow([ts, name, category, email, subject, "sent", mockup, prov]); sent += 1
            if sent % 20 == 0:
                out.flush(); print(f"  ... {sent} sent")
            time.sleep(args.delay)
        else:
            w.writerow([ts, name, category, email, subject, "failed", mockup, "all providers failed"]); failed += 1

    out.close()
    print(f"\nDONE. sent={sent} skipped={skipped} failed={failed}  -> {log_path.name}")


if __name__ == "__main__":
    main()
