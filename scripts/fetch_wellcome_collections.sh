#!/usr/bin/env bash
# Follow-up pass: expand any Wellcome work that resolved to a IIIF Collection
# (rather than a single manifest) into its child manifests, and index each.
#
# Reads parent IDs + Collection URLs from corpus/wellcome/_fetch.log.
# For each child manifest URL, runs:
#   iiif-utils create-index -P wellcome <child_url> -o corpus/wellcome/<parent_id>_v<N>.sqlite
# Resumable: skips any output file that already exists.

set -u
cd "$(dirname "$0")/.."

OUT="corpus/wellcome"
LOG="$OUT/_fetch_collections.log"
mkdir -p "$OUT"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# Build the list of parent ID + Collection URL from _fetch.log.
# A successful Collection error looks like:
#   FETCH <id> — <label>
#   Error: https://iiif.wellcomecollection.org/presentation/<bnum> is a Collection of N manifests.

PARENTS=$(awk '
  /^\[.*\] \[.*\] FETCH / {
    # capture id from "FETCH <id> —"
    for (i=1;i<=NF;i++) if ($i == "FETCH") { last_id=$(i+1); next }
  }
  /Error: .* is a Collection of [0-9]+ manifests\./ {
    # extract the URL — the 2nd field
    url=$2
    if (last_id != "") print last_id "|" url
    last_id=""
  }
' "$OUT/_fetch.log" | sort -u)

if [ -z "$PARENTS" ]; then
  echo "[$(ts)] no Collection-failure entries found in $OUT/_fetch.log — nothing to do" | tee -a "$LOG"
  exit 0
fi

echo "[$(ts)] Wellcome collection-expansion start" | tee -a "$LOG"
echo "$PARENTS" | sed 's/^/  parent: /' | tee -a "$LOG"

total_done=0; total_skip=0; total_fail=0
FAILED=""
# Newline-delimited list of "url|<parent_id>_v<N>" tuples already seen, so duplicate
# parents (e.g. Cajal Histologie) don't double-fetch. Bash 3.2 has no associative arrays.
SEEN_CHILD=""

while IFS='|' read -r pid purl; do
  [ -z "$pid" ] && continue
  echo "[$(ts)] EXPAND $pid → $purl" | tee -a "$LOG"

  # Fetch child manifest URLs from the Collection
  CHILDREN=$(curl -s "$purl" \
    | python3 -c "
import sys, json
d = json.load(sys.stdin)
items = d.get('items') or d.get('manifests') or []
for it in items:
    u = it.get('id') or it.get('@id')
    if u:
        print(u)
")
  if [ -z "$CHILDREN" ]; then
    echo "[$(ts)]   FAIL $pid — could not enumerate child manifests" | tee -a "$LOG"
    FAILED="$FAILED
  - $pid (enumeration)"
    total_fail=$((total_fail + 1))
    continue
  fi

  n=0
  while IFS= read -r curl_url; do
    [ -z "$curl_url" ] && continue
    n=$((n + 1))
    out="$OUT/${pid}_v${n}.sqlite"

    prior=$(printf '%s\n' "$SEEN_CHILD" | awk -F'|' -v u="$curl_url" '$1==u {print $2; exit}')
    if [ -n "$prior" ]; then
      echo "[$(ts)]   DUP   ${pid}_v${n} — already indexed under $prior" | tee -a "$LOG"
      total_skip=$((total_skip + 1))
      continue
    fi
    SEEN_CHILD="$SEEN_CHILD
$curl_url|${pid}_v${n}"

    if [ -s "$out" ]; then
      echo "[$(ts)]   SKIP  ${pid}_v${n} (exists)" | tee -a "$LOG"
      total_skip=$((total_skip + 1))
      continue
    fi

    echo "[$(ts)]   FETCH ${pid}_v${n} ← $curl_url" | tee -a "$LOG"
    if uv run iiif-utils create-index -P wellcome "$curl_url" -o "$out" >>"$LOG" 2>&1; then
      sz=$(du -h "$out" 2>/dev/null | awk '{print $1}')
      echo "[$(ts)]   OK    ${pid}_v${n} ($sz)" | tee -a "$LOG"
      total_done=$((total_done + 1))
    else
      rc=$?
      echo "[$(ts)]   FAIL  ${pid}_v${n} (rc=$rc)" | tee -a "$LOG"
      FAILED="$FAILED
  - ${pid}_v${n} ← $curl_url"
      total_fail=$((total_fail + 1))
      rm -f "$out"
    fi
  done <<< "$CHILDREN"
done <<< "$PARENTS"

echo "[$(ts)] DONE — $total_done fetched, $total_skip skipped, $total_fail failed" | tee -a "$LOG"
if [ "$total_fail" -gt 0 ]; then
  echo "[$(ts)] Failed:" | tee -a "$LOG"
  printf '%s\n' "$FAILED" | tee -a "$LOG"
  exit 1
fi
