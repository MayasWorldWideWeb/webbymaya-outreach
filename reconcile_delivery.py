#!/usr/bin/env python3
"""
reconcile_delivery.py — Catch silent send failures.

The send pipeline logs a row as "sent" the moment a provider's API returns 2xx,
but a provider can still ASYNC-REJECT the mail afterward (exactly what Brevo #1
did for a week: 1,590 "sent", 0 delivered). This reconciles what we LOGGED as
sent against what the providers ACTUALLY delivered, and alerts if they diverge.

Run standalone or from run_daily.sh. Writes reconcile_log.csv and, on a bad
delivery rate, fires notify.py so a silent outage can't hide again.
"""
import csv, datetime, json, os, subprocess, sys, urllib.request
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
ALERT_THRESHOLD = 0.80      # alert if actual delivered / logged sent < 80%


def _key(var: str) -> str:
    v = os.environ.get(var, "")
    if v:
        return v
    # fallback: parse ~/.zshrc (cron context may not have it exported)
    try:
        for line in (Path.home() / ".zshrc").read_text().splitlines():
            if line.strip().startswith(f"export {var}="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    except Exception:
        pass
    return ""


def _brevo_report(key: str) -> dict:
    if not key:
        return {}
    try:
        req = urllib.request.Request(
            "https://api.brevo.com/v3/smtp/statistics/aggregatedReport?days=1",
            headers={"api-key": key, "accept": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=25).read())
    except Exception as e:
        return {"_err": str(e)}


def main():
    today = datetime.date.today().strftime("%Y-%m-%d")
    log = SCRIPT_DIR / f"send_log_{today}.csv"

    logged_sent = 0
    if log.exists():
        for r in csv.DictReader(open(log, errors="replace")):
            if r.get("status") == "sent":
                logged_sent += 1

    b1 = _brevo_report(_key("BREVO_API_KEY"))
    b2 = _brevo_report(_key("BREVO_API_KEY_2"))
    delivered = (b1.get("delivered", 0) or 0) + (b2.get("delivered", 0) or 0)
    errors    = (b1.get("error", 0) or 0) + (b2.get("error", 0) or 0)
    bounces   = (b1.get("hardBounces", 0) or 0) + (b2.get("hardBounces", 0) or 0)

    rate = (delivered / logged_sent) if logged_sent else 1.0
    status = "OK" if rate >= ALERT_THRESHOLD else "ALERT"

    # append to reconcile log
    rl = SCRIPT_DIR / "reconcile_log.csv"
    new = not rl.exists()
    with open(rl, "a", newline="") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "logged_sent", "actually_delivered", "provider_errors",
                        "hard_bounces", "delivery_rate", "status"])
        w.writerow([today, logged_sent, delivered, errors, bounces, f"{rate:.2f}", status])

    msg = (f"Delivery reconcile {today}: logged sent={logged_sent}, "
           f"actually delivered={delivered}, provider errors={errors}, "
           f"hard bounces={bounces}, rate={rate:.0%} -> {status}")
    print(msg)

    if status == "ALERT" and logged_sent >= 20:
        # divergence = a provider is silently rejecting. Leave a durable marker
        # (seen whenever Maya returns) + a best-effort desktop notification.
        alert = SCRIPT_DIR / f"RECONCILE_ALERT_{today}.txt"
        alert.write_text(f"⚠️ WebByMaya SILENT SEND FAILURE\n\n{msg}\n\n"
                         f"Mail was logged as sent but providers did NOT deliver it. "
                         f"Check sender validation in Brevo (both accounts) and provider status.\n")
        try:
            subprocess.run(["osascript", "-e",
                            f'display notification "{msg}" with title "WebByMaya SEND FAILURE"'],
                           timeout=15)
        except Exception:
            pass
        print(f"ALERT written -> {alert.name}")


if __name__ == "__main__":
    main()
