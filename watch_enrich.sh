#!/bin/bash
while true; do
    LINE=$(grep "done  |" /Users/mayasierra/webbymaaya-scripts/cron_run.log | tail -1)
    DONE=$(echo "$LINE" | grep -o '\[.*\]' | tr -d '[]' | cut -d'/' -f1)
    TOTAL=$(echo "$LINE" | grep -o '\[.*\]' | tr -d '[]' | cut -d'/' -f2)
    FOUND=$(echo "$LINE" | grep -o '[0-9]* emails found' | grep -o '[0-9]*')
    DONE=${DONE:-0}; TOTAL=${TOTAL:-1264}; FOUND=${FOUND:-0}
    PCT=$((DONE * 100 / TOTAL))
    FILLED=$((PCT * 40 / 100))
    EMPTY=$((40 - FILLED))
    BAR=$(printf '█%.0s' $(seq 1 $FILLED 2>/dev/null))$(printf '░%.0s' $(seq 1 $EMPTY 2>/dev/null))
    DONE_FILE=$(ls /Users/mayasierra/webbymaaya-scripts/prospects_2026-06-19_enriched.csv 2>/dev/null)
    if [ -n "$DONE_FILE" ]; then
        echo -e "\r✅ DONE — enriched file ready! ($FOUND emails found)          "
        exit 0
    fi
    printf "\r[%s] %d%% — %d/%d businesses — %d emails found" "$BAR" "$PCT" "$DONE" "$TOTAL" "$FOUND"
    sleep 5
done
