#!/bin/bash
# Watches for new prospect files and auto-enriches them as they appear
SCRIPT_DIR="/Users/mayasierra/webbymaaya-scripts"
PYTHON=/usr/bin/python3
TODAY=$(date +%Y-%m-%d)
ENRICHED="$SCRIPT_DIR/prospects_${TODAY}_enriched.csv"
RAW="$SCRIPT_DIR/prospects_${TODAY}.csv"
LAST_SIZE=0

echo "[watch] Monitoring for new prospects — $(date)"

while true; do
    # Check if scraper is still running
    SCRAPER_ALIVE=$(ps aux | grep -E "scheduled_find|find_prospects_yelp" | grep -v grep | wc -l | tr -d ' ')

    if [ -f "$RAW" ]; then
        CURRENT_SIZE=$(wc -l < "$RAW" | tr -d ' ')
    else
        CURRENT_SIZE=0
    fi

    # New rows appeared — re-run enrichment
    if [ "$CURRENT_SIZE" -gt "$LAST_SIZE" ] && [ "$CURRENT_SIZE" -gt 0 ]; then
        echo "[watch] Prospects grew: $LAST_SIZE → $CURRENT_SIZE rows — starting enrichment..."
        LAST_SIZE=$CURRENT_SIZE
        # Kill any existing enrichment so we don't double-run
        pkill -f "enrich_emails.py" 2>/dev/null
        sleep 2
        $PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$RAW" --workers 8 >> "$SCRIPT_DIR/cron_run.log" 2>&1
        echo "[watch] Enrichment pass done — $(date)"
    fi

    # Scraper finished and enrichment is done — report final count
    if [ "$SCRAPER_ALIVE" -eq 0 ]; then
        if [ -f "$ENRICHED" ]; then
            READY=$($PYTHON -c "
import csv, glob
sent = set()
for p in glob.glob('$SCRIPT_DIR/send_log_*.csv') + glob.glob('$SCRIPT_DIR/followup_log_*.csv'):
    with open(p, newline='', errors='replace') as f:
        for r in csv.DictReader(f):
            e = (r.get('email_sent_to') or r.get('email') or '').strip().lower()
            if e: sent.add(e)
total = 0
with open('$ENRICHED', newline='', errors='replace') as f:
    for r in csv.DictReader(f):
        e = r.get('email','').strip().lower()
        if e and e not in sent: total += 1
print(total)
" 2>/dev/null)
            echo "[watch] Scraper done. $READY emails ready to send tomorrow."
        fi
        echo "[watch] All done — exiting."
        exit 0
    fi

    sleep 30
done
