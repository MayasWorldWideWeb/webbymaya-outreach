#!/bin/bash
# WebByMaya daily outreach — runs automatically via cron at 9 AM
# Pipeline: find prospects → enrich emails → send cold outreach
#           follow-ups / seasonal / engagement run in parallel with enrichment

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG="$SCRIPT_DIR/cron_run.log"
PYTHON=/usr/bin/python3
TODAY=$(date +%Y-%m-%d)

# Wait for network — Mac cron runs before Wi-Fi is ready; DNS fails silently
for _i in 1 2 3 4 5 6; do
    if /usr/bin/curl -sf --max-time 5 "https://8.8.8.8" > /dev/null 2>&1 || \
       /usr/bin/curl -sf --max-time 5 "https://api.yelp.com" > /dev/null 2>&1; then
        break
    fi
    sleep 10
done

# Load API keys (cron doesn't source .zshrc)
export TWILIO_ACCOUNT_SID="$(grep TWILIO_ACCOUNT_SID ~/.zshrc | cut -d'"' -f2)"
export TWILIO_AUTH_TOKEN="$(grep TWILIO_AUTH_TOKEN ~/.zshrc | cut -d'"' -f2)"
export TWILIO_API_KEY="$(grep TWILIO_API_KEY ~/.zshrc | grep -v SECRET | cut -d'"' -f2)"
export TWILIO_API_SECRET="$(grep TWILIO_API_SECRET ~/.zshrc | cut -d'"' -f2)"
export TWILIO_PHONE_NUMBER="$(grep TWILIO_PHONE_NUMBER ~/.zshrc | grep -v TF | cut -d'"' -f2)"
export TWILIO_TF_NUMBER="$(grep TWILIO_TF_NUMBER ~/.zshrc | cut -d'"' -f2)"
export SENDGRID_API_KEY="$(grep SENDGRID_API_KEY ~/.zshrc | cut -d'"' -f2)"
export YELP_API_KEY="$(grep YELP_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export FSQ_API_KEY="$(grep 'FSQ_API_KEY=' ~/.zshrc | grep -v CLIENT | cut -d'"' -f2 2>/dev/null)"
export BREVO_API_KEY="$(grep '^export BREVO_API_KEY=' ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export BREVO_API_KEY_2="$(grep '^export BREVO_API_KEY_2=' ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export BREVO_SMTP_KEY="$(grep BREVO_SMTP_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export BREVO_SMTP_LOGIN="$(grep BREVO_SMTP_LOGIN ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export HERE_API_KEY="$(grep HERE_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export PEXELS_API_KEY="$(grep PEXELS_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export PIXABAY_API_KEY="$(grep PIXABAY_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export SUPABASE_URL="$(grep SUPABASE_URL ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export SUPABASE_SERVICE_KEY="$(grep SUPABASE_SERVICE_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export GMAIL_APP_PASSWORD="$(grep GMAIL_APP_PASSWORD ~/.zshrc | cut -d'"' -f2 2>/dev/null)"

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "  WebByMaya Daily Run — $TODAY" >> "$LOG"
echo "  Started: $(date)" >> "$LOG"
echo "========================================" >> "$LOG"

# ── SETUP: run first — both pipelines read bounce/suppression lists ──────────
echo "" >> "$LOG"
echo "[setup] Syncing bookings from website..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/sync_bookings.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[setup] Checking 10DLC campaign status..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_10dlc_auto_enable.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[setup] Syncing unsubscribes from Supabase..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/sync_unsubscribes.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[setup] Checking bounces..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_bounces.py" >> "$LOG" 2>&1

# ── BACKGROUND: find → enrich → cold outreach (the long path) ───────────────
(
    echo "" >> "$LOG"
    echo "[cold] ── Cold Outreach Pipeline Started ──" >> "$LOG"

    if [ -n "$YELP_API_KEY" ]; then
        echo "[cold:1] Finding new prospects via Yelp..." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/scheduled_find.py" >> "$LOG" 2>&1
        FIND_EXIT=$?
        if [ $FIND_EXIT -ne 0 ]; then
            echo "[cold:1] Yelp find failed — falling back to existing leads." >> "$LOG"
            $PYTHON "$SCRIPT_DIR/build_unsent_csv.py" >> "$LOG" 2>&1
            FIND_EXIT=$?
        fi
    else
        echo "[cold:1] No Yelp key — using existing untexted leads..." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/build_unsent_csv.py" >> "$LOG" 2>&1
        FIND_EXIT=$?
    fi

    if [ $FIND_EXIT -ne 0 ]; then
        echo "[cold] No new prospects today — skipping cold outreach." >> "$LOG"
    else
        PROSPECTS_CSV="$SCRIPT_DIR/prospects_$TODAY.csv"
        if [ -f "$PROSPECTS_CSV" ]; then
            echo "" >> "$LOG"
            echo "[cold:2] Scoring leads..." >> "$LOG"
            $PYTHON "$SCRIPT_DIR/score_leads.py" "$PROSPECTS_CSV" >> "$LOG" 2>&1

            echo "" >> "$LOG"
            echo "[cold:3] Enriching emails (running while follow-ups send)..." >> "$LOG"
            $PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$PROSPECTS_CSV" >> "$LOG" 2>&1
        fi

        echo "" >> "$LOG"
        echo "[cold:4] Sending cold outreach emails..." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/scheduled_send.py" --sms-limit 0 --email-limit 500 >> "$LOG" 2>&1
    fi

    echo "" >> "$LOG"
    echo "[cold] ── Cold Outreach Pipeline Done: $(date) ──" >> "$LOG"
) &
COLD_PID=$!

# ── FOREGROUND: follow-ups + engagement — run NOW while enrichment is running ─

echo "" >> "$LOG"
echo "[fu:1] Sending clicker follow-ups (48h after link click)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/clicker_followups.py" --limit 50 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:2] Processing replies (hot leads → pricing, opt-outs → suppression)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/auto_reply.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:3] Responding to new form submissions..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/form_responder.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:4] Follow-up drip sequences (day 3 / 7 / 14)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/followup_send.py" --limit 250 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:5] Seasonal campaign emails..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/seasonal_send.py" --limit 200 >> "$LOG" 2>&1

# Re-engagement: Tue / Wed / Thu only
if [ "$(date +%u)" = "2" ] || [ "$(date +%u)" = "3" ] || [ "$(date +%u)" = "4" ]; then
    echo "" >> "$LOG"
    echo "[fu:6] Re-engagement pass (30-day no-response leads)..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/reengagement_pass.py" --limit 150 >> "$LOG" 2>&1
fi

echo "" >> "$LOG"
echo "[ig:1] Following Philly businesses on Instagram (30/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/follow_prospects.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[ig:2] Liking Philly hashtag posts (100/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/ig_hashtag_liker.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[ig:3] DMing follow-backs (12/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/ig_dm_followbacks.py" >> "$LOG" 2>&1

# Weekly jobs (run in foreground — they're fast)
if [ "$(date +%u)" = "7" ]; then
    echo "" >> "$LOG"
    echo "[weekly] Posting to Craigslist..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/craigslist_poster.py" >> "$LOG" 2>&1

    echo "" >> "$LOG"
    echo "[weekly] Sending weekly digest email..." >> "$LOG"
    $PYTHON -c "import sys; sys.path.insert(0,'$SCRIPT_DIR'); import dashboard; dashboard.send_weekly_digest()" >> "$LOG" 2>&1
fi

if [ "$(date +%u)" = "5" ]; then
    echo "" >> "$LOG"
    echo "[weekly] Sending testimonial requests..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/testimonial_request.py" >> "$LOG" 2>&1
fi

# ── WAIT for cold outreach pipeline to finish ─────────────────────────────────
echo "" >> "$LOG"
echo "[wait] Follow-ups done. Waiting for cold outreach pipeline (PID $COLD_PID)..." >> "$LOG"
wait $COLD_PID

echo "" >> "$LOG"
echo "  Done: $(date)" >> "$LOG"
