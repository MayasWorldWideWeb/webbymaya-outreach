#!/usr/bin/env python3
"""health_check.py — daily outreach pipeline health check + alerting.

Runs after the daily cron. Inspects today's sends/follow-ups/providers and,
if anything looks wrong (no sends, high failure rate, dead provider, bad Gmail
token), alerts Maya via THREE channels with retry:
  1. Email  — via the hardened multi-provider send_email (Brevo-first, reliable)
  2. SMS    — Twilio to her cell, with backoff
  3. Desktop— macOS notification

Designed so a silent breakage (like the 184 follow-up / 585 batch failures)
pings her automatically instead of going unnoticed.

Usage:
  python3 health_check.py              # alert only if problems
  python3 health_check.py --always     # also send an all-clear summary email
"""
import argparse, base64, csv, datetime, json, os, subprocess, sys, time
import urllib.request, urllib.parse, urllib.error
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
HEALTH_LOG = SCRIPT_DIR / "health_log.csv"
UNDELIVERED_ALERTS = SCRIPT_DIR / "undelivered_alerts.json"
PROVIDER_LIMIT_FILE = Path.home() / ".webbymaaya/provider_limits.json"
TRACKING_FILE = Path.home() / ".webbymaaya/tracking_sends.json"
GMAIL_TOKEN = Path.home() / ".webbymaaya/gmail_token.json"

MY_NUMBER = "+12154602084"          # Maya's cell
TWILIO_FROM = "+12153099790"
SID = os.environ.get("TWILIO_ACCOUNT_SID", "")
TOKEN = os.environ.get("TWILIO_AUTH_TOKEN", "")

# thresholds
MIN_SENDS = 1                       # 0 sends today = critical
MAX_FAIL_RATE = 0.15                # >15% send-attempt failures = problem
MAX_FU_FAIL_RATE = 0.25             # >25% follow-up failures = problem

TODAY = str(datetime.date.today())

# Must match run_daily.sh: 0 means cold acquisition runs in GitHub Actions.
LOCAL_COLD = os.environ.get("LOCAL_COLD", "0") == "1"

# The cloud job is scheduled at 13:00 UTC and this check runs on the Mac in the
# morning, so "did the cloud send TODAY" races the schedule and would false-alarm
# every morning. Ask instead whether it has sent at all recently.
CLOUD_WINDOW_HOURS = 30

SUPABASE_URL = "https://ycsauzlqsjjbusugshpz.supabase.co"
SUPABASE_ANON = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inljc2F1"
    "emxxc2pqYnVzdWdzaHB6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3Nzk0NjMzMTQsImV4cCI6MjA5"
    "NTAzOTMxNH0._rjYuGZch-CA4sfm2rV3lvs_ixDcQfNFg90KWsbe1HI"
)


def _cloud_first_touch():
    """(sent_count, last_sent_at, error) for cloud sends inside the window.

    scheduled_send logs every send to Supabase email_log via sb.log_email, so
    that table is the one place the Mac can see what the runner actually did.
    """
    since = (datetime.datetime.utcnow()
             - datetime.timedelta(hours=CLOUD_WINDOW_HOURS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = (f"{SUPABASE_URL}/rest/v1/email_log"
           f"?select=sent_at,status&status=eq.sent&sent_at=gte.{urllib.parse.quote(since)}"
           f"&order=sent_at.desc&limit=1000")
    req = urllib.request.Request(
        url, headers={"apikey": SUPABASE_ANON, "Authorization": f"Bearer {SUPABASE_ANON}"})
    try:
        rows = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except Exception as e:
        # Report the failure — do NOT return 0, which reads as "the cloud is dead"
        # and would swap one false alarm for another.
        return 0, None, str(e)[:120]
    last = rows[0]["sent_at"][:16].replace("T", " ") if rows else None
    return len(rows), last, None


def _rows(path):
    p = SCRIPT_DIR / path
    if not p.exists():
        return []
    with open(p) as f:
        return list(csv.DictReader(f))


def _status_counts(rows):
    sent = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "sent")
    failed = sum(1 for r in rows if (r.get("status") or "").strip().lower() == "failed")
    return sent, failed


def gmail_ok():
    """Return True if the Gmail refresh token still works."""
    if not GMAIL_TOKEN.exists():
        return False
    try:
        tok = json.loads(GMAIL_TOKEN.read_text())
        data = urllib.parse.urlencode({
            "client_id": tok["client_id"], "client_secret": tok["client_secret"],
            "refresh_token": tok["refresh_token"], "grant_type": "refresh_token",
        }).encode()
        urllib.request.urlopen(urllib.request.Request(
            "https://oauth2.googleapis.com/token", data=data), timeout=15)
        return True
    except Exception:
        return False


def assess():
    """Return (problems:list[str], summary:str)."""
    problems, lines = [], []

    # --- first-touch batch ---
    batch = _rows(f"send_log_{TODAY}.csv")
    b_sent, b_fail = _status_counts(batch)
    attempts = b_sent + b_fail
    fail_rate = (b_fail / attempts) if attempts else 0
    lines.append(f"First-touch (local): {b_sent} sent, {b_fail} failed ({fail_rate*100:.0f}% fail)")

    if LOCAL_COLD:
        # Cold acquisition runs here, so a local zero is a real zero.
        if b_sent < MIN_SENDS:
            problems.append(f"❗ NO first-touch emails sent today ({b_sent}).")
        elif fail_rate > MAX_FAIL_RATE:
            problems.append(f"⚠️ First-touch failure rate {fail_rate*100:.0f}% (>{int(MAX_FAIL_RATE*100)}%).")
    else:
        # Cold moved to GitHub Actions on 08-09. A local zero is now the CORRECT
        # result, but this check kept reading the local send log and alerted by
        # email AND SMS on 08-10, 08-11 and 08-12 — three straight days of crying
        # wolf while the cloud was sending 49/day perfectly well. Ask the cloud.
        cloud_sent, cloud_when, cloud_err = _cloud_first_touch()
        if cloud_err:
            lines.append(f"First-touch (cloud): could not check — {cloud_err}")
            problems.append(f"⚠️ Could not verify cloud sending: {cloud_err}")
        else:
            lines.append(f"First-touch (cloud): {cloud_sent} sent, last at {cloud_when or 'never'}")
            if cloud_sent < MIN_SENDS:
                problems.append(
                    f"❗ NO first-touch emails sent in the last {CLOUD_WINDOW_HOURS}h — "
                    "the GitHub Actions job is not sending."
                )
        if fail_rate > MAX_FAIL_RATE and attempts:
            problems.append(f"⚠️ Local first-touch failure rate {fail_rate*100:.0f}%.")

    # --- follow-ups ---
    fu = _rows(f"followup_log_{TODAY}.csv")
    f_sent, f_fail = _status_counts(fu)
    fu_attempts = f_sent + f_fail
    fu_rate = (f_fail / fu_attempts) if fu_attempts else 0
    if fu_attempts:
        lines.append(f"Follow-ups: {f_sent} sent, {f_fail} failed ({fu_rate*100:.0f}% fail)")
        if fu_rate > MAX_FU_FAIL_RATE:
            problems.append(f"⚠️ Follow-up failure rate {fu_rate*100:.0f}% (>{int(MAX_FU_FAIL_RATE*100)}%).")

    # --- providers ---
    try:
        pl = json.loads(PROVIDER_LIMIT_FILE.read_text())
        exhausted_today = [p for p, d in pl.items() if d == TODAY]
    except Exception:
        exhausted_today = []
    if exhausted_today:
        lines.append(f"Providers exhausted today: {', '.join(exhausted_today)}")

    # --- gmail token ---
    if not gmail_ok():
        problems.append("⚠️ Gmail token refresh FAILED (fallback provider down).")
        lines.append("Gmail: token refresh FAILED")
    else:
        lines.append("Gmail: ok")

    # --- tracking denominator ---
    try:
        tr = json.loads(TRACKING_FILE.read_text()).get(TODAY, 0)
        lines.append(f"Tracked sends today: {tr}")
    except Exception:
        pass

    summary = f"WebByMaya pipeline {TODAY}\n" + "\n".join(lines)
    return problems, summary


def send_alert_email(subject, body):
    """Use the hardened multi-provider sender."""
    try:
        from batch_send_outreach import send_email
        html = "<pre style='font:14px monospace'>" + body.replace("<", "&lt;") + "</pre>"
        ok, prov = send_email("mayasierra1999@gmail.com", subject, body, html)
        return ok
    except Exception as e:
        print(f"[health] email alert failed: {e}")
        return False


def send_alert_sms(body):
    if not (SID and TOKEN):
        return False
    url = f"https://api.twilio.com/2010-04-01/Accounts/{SID}/Messages.json"
    data = urllib.parse.urlencode({"To": MY_NUMBER, "From": TWILIO_FROM, "Body": body[:600]}).encode()
    creds = base64.b64encode(f"{SID}:{TOKEN}".encode()).decode()
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=data,
                headers={"Authorization": f"Basic {creds}",
                         "Content-Type": "application/x-www-form-urlencoded"})
            urllib.request.urlopen(req, timeout=20)
            return True
        except Exception as e:
            if attempt == 2:
                print(f"[health] sms alert failed: {e}")
            time.sleep(2 ** attempt)
    return False


def _ascii_clean(s):
    return "".join(c for c in s.replace("\n", " ") if 32 <= ord(c) < 127).replace('"', "'")[:180]


def mac_notify(title, body):
    try:
        b, t = _ascii_clean(body), _ascii_clean(title)
        subprocess.run(["osascript", "-e",
            f'display notification "{b}" with title "{t}"'],
            check=False, timeout=10)
    except Exception:
        pass


def log_health(problems, summary):
    new = not HEALTH_LOG.exists()
    with open(HEALTH_LOG, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "status", "problem_count", "summary"])
        w.writerow([TODAY, "PROBLEM" if problems else "OK", len(problems),
                    summary.replace("\n", " | ")])


def _load_undelivered():
    try:
        return json.loads(UNDELIVERED_ALERTS.read_text())
    except Exception:
        return []


def _save_undelivered(items):
    try:
        if items:
            UNDELIVERED_ALERTS.write_text(json.dumps(items, indent=2))
        elif UNDELIVERED_ALERTS.exists():
            UNDELIVERED_ALERTS.unlink()
    except Exception:
        pass


def flush_undelivered():
    """Re-send alerts that never got out.

    The failure mode this exists for: a network outage takes down the send
    providers AND the alert channels at the same time, so the run that detects
    the problem cannot report it and the breakage passes silently. Queue those
    alerts and retry on the next run, once the network is back.
    """
    pending = _load_undelivered()
    if not pending:
        return
    print(f"\n--- Retrying {len(pending)} undelivered alert(s) ---")
    still_pending = []
    for item in pending:
        subject = f"🚨 WebByMaya outreach problem — {item['date']} (delayed alert)"
        if send_alert_email(subject, item["alert"]):
            print(f"  delivered backlog alert from {item['date']}")
        else:
            still_pending.append(item)
            print(f"  still undeliverable: {item['date']}")
    _save_undelivered(still_pending)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--always", action="store_true", help="send summary email even when healthy")
    args = ap.parse_args()

    flush_undelivered()

    problems, summary = assess()
    print(summary)
    log_health(problems, summary)

    if problems:
        alert = "🚨 WebByMaya outreach needs attention:\n\n" + "\n".join(problems) + "\n\n" + summary
        print("\n--- PROBLEMS DETECTED — alerting ---\n" + "\n".join(problems))
        mac_notify("WebByMaya — outreach problem", "\n".join(problems))
        e = send_alert_email("🚨 WebByMaya outreach problem — " + TODAY, alert)
        s = send_alert_sms("🚨 WebByMaya: " + " ".join(p.strip("⚠️❗ ") for p in problems))
        print(f"alert sent → email:{e} sms:{s}")
        if not e and not s:
            # Both channels down — almost certainly the same outage that caused
            # the problem. Queue it so the next healthy run still tells her.
            pending = _load_undelivered()
            pending.append({"date": TODAY, "alert": alert})
            _save_undelivered(pending[-14:])
            print("both alert channels failed — queued for retry on next run")
        sys.exit(1)
    else:
        mac_notify("WebByMaya — all healthy", summary.split("\n", 1)[-1][:150])
        if args.always:
            send_alert_email("✅ WebByMaya outreach OK — " + TODAY, summary)
        print("\n--- All healthy ---")


if __name__ == "__main__":
    main()
