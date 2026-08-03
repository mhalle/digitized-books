#!/usr/bin/env bash
# Index all 14 Bourgery volumes with --no-ocr (ALTO endpoints return 500
# for every canvas, so this is the only viable path until either Wellcome
# repairs the ALTO API or we run Tesseract locally on the text vols).

set -u
cd "$(dirname "$0")/.."

OUT="corpus/wellcome"
LOG="$OUT/_fetch_bourgery.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

PARENT="p747b7vs"
BASE="https://iiif.wellcomecollection.org/presentation/b33545182"

echo "[$(ts)] Bourgery --no-ocr fetch start (14 child manifests)" | tee -a "$LOG"

done_count=0; skip_count=0; fail_count=0
declare -a FAILED=()

for v in 1 2 3 4 5 6 7 8 9 10 11 12 13 14; do
  out="$OUT/${PARENT}_v${v}.sqlite"
  url=$(printf "%s_%04d" "$BASE" "$v")

  if [ -s "$out" ]; then
    echo "[$(ts)] [$v/14] SKIP ${PARENT}_v${v} (exists)" | tee -a "$LOG"
    skip_count=$((skip_count + 1))
    continue
  fi

  echo "[$(ts)] [$v/14] FETCH ${PARENT}_v${v} ← $url" | tee -a "$LOG"
  if uv run iiif-utils create-index --no-ocr -P wellcome "$url" -o "$out" >>"$LOG" 2>&1; then
    sz=$(du -h "$out" 2>/dev/null | awk '{print $1}')
    echo "[$(ts)] [$v/14]   OK   ${PARENT}_v${v} ($sz)" | tee -a "$LOG"
    done_count=$((done_count + 1))
  else
    rc=$?
    echo "[$(ts)] [$v/14]   FAIL ${PARENT}_v${v} (rc=$rc)" | tee -a "$LOG"
    FAILED+=("${PARENT}_v${v}")
    fail_count=$((fail_count + 1))
    rm -f "$out"
  fi
done

echo "[$(ts)] DONE — $done_count fetched, $skip_count skipped, $fail_count failed" | tee -a "$LOG"
if [ "$fail_count" -gt 0 ]; then
  for f in "${FAILED[@]}"; do echo "  - $f" | tee -a "$LOG"; done
  exit 1
fi
