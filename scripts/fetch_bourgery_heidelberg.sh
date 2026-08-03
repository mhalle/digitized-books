#!/usr/bin/env bash
# Ingest the 8 Heidelberg text volumes of Bourgery & Jacob's Traité
# (1831–1854), the matching 1st edition. Pairs with the existing
# corpus/wellcome/p747b7vs_v*.sqlite indexes (Wellcome imagery,
# image-only) by providing OCR-able text against Heidelberg's imagery.
#
# Vol-1 stem is `bourgey1832bd1_1` — note the one-r spelling, a typo
# preserved in Heidelberg's permalinks. Vols 2-8 use `bourgery`.

set -u
cd "$(dirname "$0")/.."

OUT="corpus/heidelberg"
LOG="$OUT/_fetch_bourgery.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# stem | label
STEMS="bourgey1832bd1_1|Tome 1 (Osteologie + Syndesmologie) 1832
bourgery1834bd2_1|Tome 2 (Myologie) 1834
bourgery1844bd3_1|Tome 3 1844
bourgery1835bd4_1|Tome 4 1835
bourgery1839bd5_1|Tome 5 (Splanchnologie) 1839
bourgery1837bd6_1|Tome 6 1837
bourgery1840bd7_1|Tome 7 1840
bourgery1854bd8_1|Tome 8 1854"

echo "[$(ts)] Heidelberg Bourgery text fetch start (8 vols)" | tee -a "$LOG"

total=0; done_count=0; skip_count=0; fail_count=0
FAILED=""

while IFS='|' read -r stem label; do
  [ -z "$stem" ] && continue
  total=$((total + 1))
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
