#!/bin/bash
# WebByMaya daily outreach — runs automatically via cron at 9 AM
# Pipeline: find prospects → enrich emails → send SMS + email

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/cron_run.log"
PYTHON=/usr/bin/python3
TODAY=$(date +%Y-%m-%d)

# Load API keys (cron doesn't source .zshrc)
export GOOGLE_PLACES_API_KEY="$(grep GOOGLE_PLACES_API_KEY ~/.zshrc | cut -d'"' -f2)"
export TWILIO_ACCOUNT_SID="$(grep TWILIO_ACCOUNT_SID ~/.zshrc | cut -d'"' -f2)"
export TWILIO_AUTH_TOKEN="$(grep TWILIO_AUTH_TOKEN ~/.zshrc | cut -d'"' -f2)"
export TWILIO_PHONE_NUMBER="$(grep TWILIO_PHONE_NUMBER ~/.zshrc | cut -d'"' -f2)"
export SENDGRID_API_KEY="$(grep SENDGRID_API_KEY ~/.zshrc | cut -d'"' -f2)"

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "  WebByMaya Daily Run — $TODAY" >> "$LOG"
echo "  Started: $(date)" >> "$LOG"
echo "========================================" >> "$LOG"

# ── Step 1: Find prospects for next Philly zone ───────────────────────────
echo "" >> "$LOG"
echo "[1/3] Finding prospects..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/scheduled_find.py" >> "$LOG" 2>&1
FIND_EXIT=$?

if [ $FIND_EXIT -ne 0 ]; then
    echo "[1/3] All Philly zones exhausted or error — skipping send." >> "$LOG"
    echo "  Done: $(date)" >> "$LOG"
    exit 0
fi

# ── Step 2: Enrich with emails ────────────────────────────────────────────
PROSPECTS_CSV="$SCRIPT_DIR/prospects_$TODAY.csv"
if [ ! -f "$PROSPECTS_CSV" ]; then
    echo "[2/3] No prospects CSV found for today — skipping enrich + send." >> "$LOG"
    exit 1
fi

echo "" >> "$LOG"
echo "[2/3] Enriching emails..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$PROSPECTS_CSV" >> "$LOG" 2>&1

# ── Step 3: Pull latest bounces from SendGrid ────────────────────────────
echo "" >> "$LOG"
echo "[3/4] Checking bounces..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_bounces.py" >> "$LOG" 2>&1

# ── Step 4: Send SMS + emails ─────────────────────────────────────────────
echo "" >> "$LOG"
echo "[4/4] Sending outreach..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/scheduled_send.py" --sms-limit 200 --email-limit 50 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "  Done: $(date)" >> "$LOG"
