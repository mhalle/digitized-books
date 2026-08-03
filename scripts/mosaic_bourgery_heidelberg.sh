#!/usr/bin/env bash
# Render a 4K-wide full-volume mosaic for every Heidelberg Bourgery
# index — text (bdN_1) and atlas (bdN_2). 16 mosaics total, all
# saved alongside the earlier preview JPGs.

set -u
cd "$(dirname "$0")/.."

OUT="experiments/bourgery_preview"
LOG="$OUT/_mosaic.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Atlas vols only — text vols are mostly letterpress prose, the mosaic
# adds little visual value over a single sample.
INDEXES=$(ls corpus/heidelberg/bourge*_2.sqlite 2>/dev/null)
if [ -z "$INDEXES" ]; then
  echo "[$(ts)] no Bourgery Heidelberg indexes found" | tee -a "$LOG"
  exit 1
fi

n_done=0; n_skip=0; n_fail=0
for idx in $INDEXES; do
  stem=$(basename "$idx" .sqlite)
  out="$OUT/${stem}_4k.jpg"
  if [ -s "$out" ]; then
    echo "[$(ts)] SKIP  $stem (exists)" | tee -a "$LOG"
    n_skip=$((n_skip + 1))
    continue
  fi
  echo "[$(ts)] MOSAIC $stem" | tee -a "$LOG"
  if uv run iiif-utils get-pages -i "$idx" --mosaic --all --cols 8 \
       -j 3 --size 800, --mosaic-width 4096 --label book \
       -o "$out" >>"$LOG" 2>&1; then
    dims=$(python3 -c "from PIL import Image; im=Image.open('$out'); print(im.size)")
    sz=$(du -h "$out" | awk '{print $1}')
    echo "[$(ts)]   OK  $stem $dims $sz" | tee -a "$LOG"
    n_done=$((n_done + 1))
  else
    rc=$?
    echo "[$(ts)]   FAIL $stem (rc=$rc)" | tee -a "$LOG"
    n_fail=$((n_fail + 1))
    rm -f "$out"
  fi
done

echo "[$(ts)] DONE — $n_done rendered, $n_skip skipped, $n_fail failed" | tee -a "$LOG"
[ "$n_fail" -gt 0 ] && exit 1
exit 0
