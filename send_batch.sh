#!/bin/bash
# send_batch.sh — Mid-day/afternoon email batch (called by cron at 12pm and 4pm)
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/cron_run.log"
PYTHON=/usr/bin/python3

export SENDGRID_API_KEY="$(grep SENDGRID_API_KEY ~/.zshrc | cut -d'"' -f2)"
export GMAIL_APP_PASSWORD="$(grep GMAIL_APP_PASSWORD ~/.zshrc | cut -d'"' -f2 2>/dev/null)"

echo "" >> "$LOG"
echo "  Batch send: $(date)" >> "$LOG"
$PYTHON "$SCRIPT_DIR/scheduled_send.py" --sms-limit 0 --email-limit 500 >> "$LOG" 2>&1
echo "  Batch done: $(date)" >> "$LOG"
