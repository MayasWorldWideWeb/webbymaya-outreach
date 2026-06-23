#!/bin/bash
# Runs scrape → enrich in a continuous loop until killed.
# Maya runs this until she has enough leads, then kills it.
SCRIPT_DIR="/Users/mayasierra/webbymaaya-scripts"
PYTHON=/usr/bin/python3
TODAY=$(date +%Y-%m-%d)

echo "[loop] Started continuous scrape+enrich — $(date)"
echo "[loop] Kill with: pkill -f run_until_stop"

count_ready() {
    ENRICHED="$SCRIPT_DIR/prospects_${TODAY}_enriched.csv"
    [ -f "$ENRICHED" ] || { echo 0; return; }
    $PYTHON - <<PYEOF 2>/dev/null
import csv, glob
sent = set()
for p in glob.glob('$SCRIPT_DIR/send_log_*.csv') + glob.glob('$SCRIPT_DIR/followup_log_*.csv'):
    with open(p, newline='', errors='replace') as f:
        for r in csv.DictReader(f):
            e = (r.get('email_sent_to') or r.get('email') or '').strip().lower()
            if e: sent.add(e)
bounce = set()
try:
    with open('$SCRIPT_DIR/bounce_log.csv', newline='', errors='replace') as f:
        for r in csv.DictReader(f): bounce.add(r.get('email','').strip().lower())
except: pass
skip = sent | bounce
total = 0
with open('$SCRIPT_DIR/prospects_${TODAY}_enriched.csv', newline='', errors='replace') as f:
    for r in csv.DictReader(f):
        e = r.get('email','').strip().lower()
        if e and e not in skip: total += 1
print(total)
PYEOF
}

while true; do
    # ── Scrape: run ALL remaining zones (each capped at 4 min) ──────────────
    echo ""
    echo "[loop] === Scrape pass — $(date) ==="
    $PYTHON -c "
import scheduled_find
scheduled_find.ZONES_PER_RUN = 999  # run all remaining zones
scheduled_find.main()
" 2>&1

    # ── Enrich whatever we got ───────────────────────────────────────────────
    RAW="$SCRIPT_DIR/prospects_${TODAY}.csv"
    if [ -f "$RAW" ]; then
        echo ""
        echo "[loop] === Enriching — $(date) ==="
        pkill -f "enrich_emails.py" 2>/dev/null; sleep 1
        $PYTHON "$SCRIPT_DIR/enrich_emails.py" --input "$RAW" --workers 16 2>&1
    fi

    READY=$(count_ready)
    echo ""
    echo "[loop] ✓ Ready to send tomorrow: $READY emails — $(date)"

    # ── If all zones exhausted, reset and loop ───────────────────────────────
    ZONE_IDX=$($PYTHON -c "import json; s=json.load(open('$SCRIPT_DIR/zone_state.json')); print(s['current_index'])" 2>/dev/null)
    ZONE_TOT=$($PYTHON -c "import json; s=json.load(open('$SCRIPT_DIR/zone_state.json')); print(len(s['zones']))" 2>/dev/null)
    if [ "$ZONE_IDX" -ge "$ZONE_TOT" ]; then
        echo "[loop] All $ZONE_TOT zones done — resetting and going again..."
        $PYTHON -c "
import json
from pathlib import Path
s = json.loads(Path('$SCRIPT_DIR/zone_state.json').read_text())
s['current_index'] = 0
Path('$SCRIPT_DIR/zone_state.json').write_text(json.dumps(s, indent=2))
print('[loop] Zone index reset to 0')
"
    fi

    sleep 5
done
