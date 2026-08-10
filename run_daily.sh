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
# The suppression list is the one file that must never be lost — without it the
# pipeline re-mails everyone who bounced, blocked, or unsubscribed. It was
# silently truncated once, so keep a week of daily copies to restore from.
if [ -s "$SCRIPT_DIR/bounce_log.csv" ]; then
    mkdir -p "$SCRIPT_DIR/.bounce_backups"
    cp "$SCRIPT_DIR/bounce_log.csv" "$SCRIPT_DIR/.bounce_backups/bounce_log_$TODAY.csv"
    ls -t "$SCRIPT_DIR"/.bounce_backups/bounce_log_*.csv 2>/dev/null | tail -n +8 | xargs rm -f 2>/dev/null
fi

echo "[setup] Checking bounces..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_bounces.py" >> "$LOG" 2>&1

# ── BACKGROUND: find → enrich → cold outreach (the long path) ───────────────
# ---------------------------------------------------------------------------
# Cold acquisition (find → score → enrich → send) runs in GitHub Actions, not
# here. The workflow .github/workflows/outreach.yml has been doing the same
# find+enrich+send on a 13:00 UTC schedule this whole time, so every prospect
# was being scraped twice a day — once on Maya's Mac and once in the cloud.
# The scraping is the single heaviest thing this machine does, and the cloud
# copy is free, so the local half is off by default.
#
# Everything below the cold block (replies, sales, follow-ups, health) still
# runs locally — it's all API calls, no scraping.
#
#   LOCAL_COLD=1 bash run_daily.sh    # force the local cold pipeline back on
LOCAL_COLD="${LOCAL_COLD:-0}"

if [ "$LOCAL_COLD" != "1" ]; then
    echo "" >> "$LOG"
    echo "[cold] Skipped — cold acquisition runs in GitHub Actions (outreach.yml)." >> "$LOG"
    echo "[cold] Set LOCAL_COLD=1 to run it here instead." >> "$LOG"
fi

[ "$LOCAL_COLD" = "1" ] && (
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
        # TODAY is captured when the script starts, but a run that straddles
        # midnight (or a sleeping Mac) leaves the finder writing a file stamped
        # with a different date — the exact-date match then silently skipped
        # scoring AND enrichment, so a whole batch of prospects reached the
        # sender with no email addresses. Prefer today's file, else the newest.
        PROSPECTS_CSV="$SCRIPT_DIR/prospects_$TODAY.csv"
        if [ ! -f "$PROSPECTS_CSV" ]; then
            PROSPECTS_CSV=$(ls -t "$SCRIPT_DIR"/prospects_????-??-??.csv 2>/dev/null | head -1)
            [ -n "$PROSPECTS_CSV" ] && echo "[cold] prospects_$TODAY.csv missing — using $(basename "$PROSPECTS_CSV")" >> "$LOG"
        fi
        # Enrichment on a large file takes hours, and cold:4 waits on it. When
        # the finder turns up nothing new, the fallback above hands back the
        # same old file every day — re-enriching ~13k rows that were already
        # done and blocking the send stage for the whole day. Only enrich when
        # there is no up-to-date enriched output for this file.
        ENRICHED="${PROSPECTS_CSV%.csv}_enriched.csv"
        if [ -n "$PROSPECTS_CSV" ] && [ -f "$PROSPECTS_CSV" ] && [ ! "$ENRICHED" -nt "$PROSPECTS_CSV" ]; then
            echo "" >> "$LOG"
            echo "[cold:2] Scoring leads..." >> "$LOG"
            $PYTHON "$SCRIPT_DIR/score_leads.py" "$PROSPECTS_CSV" >> "$LOG" 2>&1

            echo "" >> "$LOG"
            echo "[cold:3] Enriching emails (running while follow-ups send)..." >> "$LOG"
            $PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$PROSPECTS_CSV" >> "$LOG" 2>&1
        elif [ -n "$PROSPECTS_CSV" ]; then
            echo "[cold:2-3] $(basename "$ENRICHED") is already current — skipping scoring/enrichment." >> "$LOG"
        fi

        echo "" >> "$LOG"
        echo "[cold:4] Sending cold outreach emails..." >> "$LOG"
        # Cap raised to 250 on 2026-07-03 after fixing the real problem: Brevo #1
        # rejected 100% of mail (unvalidated sender) — sends now route through the
        # validated Brevo #2 / SendGrid. Ceiling = ~400/day (Brevo2 300 + SG 100)
        # until maya@webbymaya.com is validated in Brevo #1 to reclaim its 300/day.
        $PYTHON "$SCRIPT_DIR/scheduled_send.py" --sms-limit 0 --email-limit 250 >> "$LOG" 2>&1
    fi

    echo "" >> "$LOG"
    echo "[cold] ── Cold Outreach Pipeline Done: $(date) ──" >> "$LOG"
) &
COLD_PID=$!

# ── FOREGROUND: follow-ups + engagement — run NOW while enrichment is running ─

echo "" >> "$LOG"
echo "[fu:1] Sending clicker follow-ups (48h after link click)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/clicker_followups.py" --limit 30 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:1b] Second touch to warm clickers (15+ days, validated, checkout-forward)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/clicker_second_touch.py" --limit 25 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:2] Processing replies (hot leads → pricing, opt-outs → suppression)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/auto_reply.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:3] Responding to new form submissions..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/form_responder.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[sales] Processing new Stripe website sales (alert Maya + send buyer intake)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/check_sales.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[offer] Keeping live offer.json in sync so previews never go stale..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/publish_offer.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:3b] Syncing hard bounces + blocked contacts to suppression list..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/sync_bounces.py" --days 45 >> "$LOG" 2>&1   # drop dead addrs before follow-ups

echo "" >> "$LOG"
echo "[fu:4] Follow-up drip (day 3 / 7 / 14, then monthly until reply-no or bounce)..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/followup_send.py" --limit 100 >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "[fu:5] Seasonal campaign emails..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/seasonal_send.py" --limit 50 >> "$LOG" 2>&1

# Re-engagement: Tue / Wed / Thu only
if [ "$(date +%u)" = "2" ] || [ "$(date +%u)" = "3" ] || [ "$(date +%u)" = "4" ]; then
    echo "" >> "$LOG"
    echo "[fu:6] Re-engagement pass (30-day no-response leads)..." >> "$LOG"
    # PAUSED during warm-up (set 2026-06-29): re-mailing 30-day non-responders is the
    # highest spam-complaint risk. Restore --limit 150 once reputation recovers (~3-4 weeks).
    $PYTHON "$SCRIPT_DIR/reengagement_pass.py" --limit 0 >> "$LOG" 2>&1
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

# ── HEALTH CHECK — alerts Maya (email+SMS+desktop) if the pipeline misbehaved ──
echo "" >> "$LOG"
echo "[health] Running daily health check..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/health_check.py" >> "$LOG" 2>&1

# ── DELIVERY RECONCILE — did what we logged as "sent" actually get delivered? ──
# Catches silent provider rejections (the Brevo #1 outage that hid for a week).
echo "" >> "$LOG"
echo "[reconcile] Verifying logged sends vs actual provider deliveries..." >> "$LOG"
$PYTHON "$SCRIPT_DIR/reconcile_delivery.py" >> "$LOG" 2>&1

echo "" >> "$LOG"
echo "  Done: $(date)" >> "$LOG"
