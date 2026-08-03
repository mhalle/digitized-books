#!/usr/bin/env bash
# Targeted follow-up after killing the Bourgery loop: just Toldt + Sobotta Histo.
# Bourgery is deferred until a --no-alto flag exists on create-index.

set -u
cd "$(dirname "$0")/.."

OUT="corpus/wellcome"
LOG="$OUT/_fetch_remaining.log"
mkdir -p "$OUT"
ts() { date '+%Y-%m-%d %H:%M:%S'; }

# parent_id|collection_url
WORKS="tgekje3p|https://iiif.wellcomecollection.org/presentation/b32839819
v43geect|https://iiif.wellcomecollection.org/presentation/b29821708"

echo "[$(ts)] Remaining collections start" | tee -a "$LOG"

while IFS='|' read -r pid purl; do
  [ -z "$pid" ] && continue
  echo "[$(ts)] EXPAND $pid → $purl" | tee -a "$LOG"
  CHILDREN=$(curl -s "$purl" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for it in d.get('items') or d.get('manifests') or []:
    u = it.get('id') or it.get('@id')
    if u: print(u)
")
  n=0
  while IFS= read -r curl_url; do
    [ -z "$curl_url" ] && continue
    n=$((n + 1))
    out="$OUT/${pid}_v${n}.sqlite"
    if [ -s "$out" ]; then
      echo "[$(ts)]   SKIP  ${pid}_v${n} (exists)" | tee -a "$LOG"
      continue
    fi
    echo "[$(ts)]   FETCH ${pid}_v${n} ← $curl_url" | tee -a "$LOG"
    if uv run iiif-utils create-index -P wellcome "$curl_url" -o "$out" >>"$LOG" 2>&1; then
      sz=$(du -h "$out" | awk '{print $1}')
      echo "[$(ts)]   OK    ${pid}_v${n} ($sz)" | tee -a "$LOG"
    else
      rc=$?
      echo "[$(ts)]   FAIL  ${pid}_v${n} (rc=$rc)" | tee -a "$LOG"
      rm -f "$out"
    fi
  done <<< "$CHILDREN"
done <<< "$WORKS"

echo "[$(ts)] DONE" | tee -a "$LOG"
