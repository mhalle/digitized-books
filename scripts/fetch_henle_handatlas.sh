#!/usr/bin/env bash
# Ingest Heidelberg's Henle Anatomischer Hand-Atlas (1874–1877),
# the dissection-room atlas-with-text by Henle (Braunschweig: Vieweg).
# Distinct from Henle's Handbuch der systematischen Anatomie (1855–79)
# which is in corpus/wellcome/ — the Hand-Atlas is a smaller working
# companion designed for the dissection table.

set -u
cd "$(dirname "$0")/.."

OUT="corpus/heidelberg"
LOG="$OUT/_fetch_henle_handatlas.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

STEMS="henle1871bd1|Bd. 1 Knochen (Bones) 1874
henle1874bd2|Bd. 2 Bänder (Ligaments) 1874
henle1874bd3|Bd. 3 Muskeln (Muscles) 1874
henle1874bd4|Bd. 4 Gefäße (Vessels) 1874
henle1876bd5|Bd. 5 Nerven (Nerves) 1876
henle1877bd6|Bd. 6 Eingeweide (Viscera) 1877"

echo "[$(ts)] Henle Hand-Atlas fetch start (6 vols)" | tee -a "$LOG"

done_count=0; skip_count=0; fail_count=0
FAILED=""

while IFS='|' read -r stem label; do
  [ -z "$stem" ] && continue
  out="$OUT/${stem}.sqlite"

  if [ -s "$out" ]; then
    echo "[$(ts)] SKIP  $stem — $label (exists)" | tee -a "$LOG"
    skip_count=$((skip_count + 1))
    continue
  fi

  echo "[$(ts)] FETCH $stem — $label" | tee -a "$LOG"
  if uv run iiif-utils create-index -P heidelberg "$stem" -o "$out" >>"$LOG" 2>&1; then
    sz=$(du -h "$out" 2>/dev/null | awk '{print $1}')
    echo "[$(ts)]   OK  $stem ($sz)" | tee -a "$LOG"
    done_count=$((done_count + 1))
  else
    rc=$?
    echo "[$(ts)]   FAIL $stem (rc=$rc)" | tee -a "$LOG"
    FAILED="$FAILED
  - $stem"
    fail_count=$((fail_count + 1))
    rm -f "$out"
  fi
done <<< "$STEMS"

echo "[$(ts)] DONE — $done_count fetched, $skip_count skipped, $fail_count failed" | tee -a "$LOG"
if [ "$fail_count" -gt 0 ]; then
  printf '%s\n' "$FAILED" | tee -a "$LOG"
  exit 1
fi
