#!/bin/bash
# WebByMaya daily outreach — runs automatically via cron at 9 AM
# Pipeline: find prospects → enrich emails → send SMS + email

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
export BREVO_SMTP_KEY="$(grep BREVO_SMTP_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export BREVO_SMTP_LOGIN="$(grep BREVO_SMTP_LOGIN ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export HERE_API_KEY="$(grep HERE_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export PEXELS_API_KEY="$(grep PEXELS_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export PIXABAY_API_KEY="$(grep PIXABAY_API_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export SUPABASE_URL="$(grep SUPABASE_URL ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export SUPABASE_SERVICE_KEY="$(grep SUPABASE_SERVICE_KEY ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
export GMAIL_APP_PASSWORD="$(grep GMAIL_APP_PASSWORD ~/.zshrc | cut -d'"' -f2 2>/dev/null)"
# Google Places API removed — Yelp + OSM cover it for free

echo "" >> "$LOG"
echo "========================================" >> "$LOG"
echo "  WebByMaya Daily Run — $TODAY" >> "$LOG"
echo "  Started: $(date)" >> "$LOG"
echo "========================================" >> "$LOG"

# ── Step 0a: Sync bookings from Supabase → lead_status.csv ───────────────
echo "" >> "$LOG"
echo "[0a] Syncing bookings from website..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/sync_bookings.py" >> "$LOG" 2>&1

# ── Step 0b: Check 10DLC status — auto-enable SMS if approved ────────────
echo "" >> "$LOG"
echo "[0] Checking 10DLC campaign status..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_10dlc_auto_enable.py" >> "$LOG" 2>&1

# ── Step 1: Find new prospects (Yelp if key set, else use existing) ──────
echo "" >> "$LOG"
if [ -n "$YELP_API_KEY" ]; then
    echo "[1/3] Finding new prospects via Yelp..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/scheduled_find.py" >> "$LOG" 2>&1
    FIND_EXIT=$?
    if [ $FIND_EXIT -ne 0 ]; then
        echo "[1/3] Yelp find failed — falling back to existing leads." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/build_unsent_csv.py" >> "$LOG" 2>&1
        FIND_EXIT=$?
    fi
else
    echo "[1/3] No Yelp key — using existing untexted leads..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/build_unsent_csv.py" >> "$LOG" 2>&1
    FIND_EXIT=$?
fi

if [ $FIND_EXIT -ne 0 ]; then
    echo "[1/3] No new prospects today — skipping outreach, running follow-ups." >> "$LOG"
    SKIP_OUTREACH=1
else
    SKIP_OUTREACH=0
fi

# ── Steps 2-4: Outreach (skipped if no prospects found) ──────────────────
if [ "$SKIP_OUTREACH" -eq 0 ]; then
    PROSPECTS_CSV="$SCRIPT_DIR/prospects_$TODAY.csv"
    echo "" >> "$LOG"
    if [ -f "$PROSPECTS_CSV" ]; then
        echo "[2a] Scoring leads by conversion likelihood..." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/score_leads.py" "$PROSPECTS_CSV" >> "$LOG" 2>&1

        echo "" >> "$LOG"
        echo "[2/3] Enriching emails for today's prospects..." >> "$LOG"
        $PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$PROSPECTS_CSV" >> "$LOG" 2>&1
    else
        echo "[2/3] No new prospects today — skipping enrich, using backlog." >> "$LOG"
    fi

    echo "" >> "$LOG"
    echo "[2b] Syncing unsubscribes from Supabase → bounce_log.csv..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/sync_unsubscribes.py" >> "$LOG" 2>&1

    echo "" >> "$LOG"
    echo "[3/4] Checking bounces..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/check_bounces.py" >> "$LOG" 2>&1

    echo "" >> "$LOG"
    echo "[4/5] Sending outreach (email only — SMS disabled)..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/scheduled_send.py" --sms-limit 0 --email-limit 500 >> "$LOG" 2>&1
else
    echo "" >> "$LOG"
    echo "[2-4] Skipping outreach steps (no new prospects)." >> "$LOG"
fi

# ── Step 5: SMS follow-ups DISABLED ──────────────────────────────────────
echo "" >> "$LOG"
echo "[5/6] SMS follow-ups skipped (SMS disabled)." >> "$LOG"
# $PYTHON "$SCRIPT_DIR/send_followups.py" >> "$LOG" 2>&1

# ── Step 6: Clicker follow-ups (48h after link click) ────────────────────
echo "" >> "$LOG"
echo "[6/7] Sending clicker follow-ups (48h after link click)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/clicker_followups.py" --limit 50 >> "$LOG" 2>&1

# ── Step 8: Auto-reply to hot leads + process opt-outs ───────────────────
echo "" >> "$LOG"
echo "[8/8] Processing replies (hot leads → pricing email + proposal PDF, opt-outs → suppression)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/auto_reply.py" >> "$LOG" 2>&1

# ── Step 9: Respond to new webbymaya.com/book form submissions ────────────
echo "" >> "$LOG"
echo "[9/9] Responding to new form submissions (mockup + pricing)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/form_responder.py" >> "$LOG" 2>&1

# ── Weekly: Craigslist posts (Sundays only) ──────────────────────────
if [ "$(date +%u)" = "7" ]; then
    echo "" >> "$LOG"
    echo "[CL] Posting to Craigslist (Sunday weekly run)..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/craigslist_poster.py" >> "$LOG" 2>&1

    echo "" >> "$LOG"
    echo "[DIG] Sending weekly digest email..." >> "$LOG"
    $PYTHON -c "import sys; sys.path.insert(0,'$SCRIPT_DIR'); import dashboard; dashboard.send_weekly_digest()" >> "$LOG" 2>&1
fi

# ── 3x/week: Re-engagement pass (Tue / Wed / Thu) ────────────────────
if [ "$(date +%u)" = "2" ] || [ "$(date +%u)" = "3" ] || [ "$(date +%u)" = "4" ]; then
    echo "" >> "$LOG"
    echo "[RE] Re-engagement pass (30-day no-response leads)..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/reengagement_pass.py" --limit 150 >> "$LOG" 2>&1
fi

# ── Follow-up sequences (day 3 / day 7 / day 14 drip) ───────────────────
echo "" >> "$LOG"
echo "[FU] Follow-up sequences (3-email drip on non-responders)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/followup_send.py" --limit 250 >> "$LOG" 2>&1

# ── Seasonal campaigns (Valentine's, summer, back-to-school, etc.) ───────
echo "" >> "$LOG"
echo "[SC] Seasonal campaign emails (holiday/event-targeted)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/seasonal_send.py" --limit 200 >> "$LOG" 2>&1

# ── Weekly (Fridays): Testimonial requests for recently-Live clients ─────
if [ "$(date +%u)" = "5" ]; then
    echo "" >> "$LOG"
    echo "[TR] Sending testimonial requests to recently-Live clients..." >> "$LOG"
    $PYTHON "$SCRIPT_DIR/testimonial_request.py" >> "$LOG" 2>&1
fi

# ── Instagram engagement ─────────────────────────────────────────────────
echo "" >> "$LOG"
echo "[IG-1] Following Philly businesses on Instagram (30/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/follow_prospects.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[IG-2] Liking Philly hashtag posts (100/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/ig_hashtag_liker.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[IG-3] DMing follow-backs (12/day)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/ig_dm_followbacks.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "  Done: $(date)" >> "$LOG"
