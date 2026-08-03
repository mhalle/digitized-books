#!/usr/bin/env bash
# Ingest the 8 Heidelberg atlas volumes of Bourgery & Jacob's Traité
# (1831–1854). Companion to fetch_bourgery_heidelberg.sh (text vols).
# Atlas vols carry the full-color hand-tinted lithographs; OCR coverage
# is typically caption-only (sparse text_blocks per canvas).
#
# Heidelberg's atlas stems use the `bourgey` typo spelling (no second
# `r`), while the text stems are mostly `bourgery`. Canvas labels in
# these manifests preserve plate numbers like "Planche 22".

set -u
cd "$(dirname "$0")/.."

OUT="corpus/heidelberg"
LOG="$OUT/_fetch_bourgery_atlas.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

STEMS="bourgey1831bd1_2|Atlas Bd. 1 (Osteologie/Syndesmologie plates) 1831
bourgey1831bd2_2|Atlas Bd. 2 (Myologie plates) 1831
bourgey1844bd3_2|Atlas Bd. 3 plates 1844
bourgey1836bd4_2|Atlas Bd. 4 plates 1836
bourgey1839bd5_2|Atlas Bd. 5 (Splanchnologie plates) 1839
bourgey1839bd6_2|Atlas Bd. 6 plates 1839
bourgey1840bd7_2|Atlas Bd. 7 plates 1840
bourgey1844bd8_2|Atlas Bd. 8 plates 1844"

echo "[$(ts)] Heidelberg Bourgery atlas fetch start (8 vols)" | tee -a "$LOG"

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
