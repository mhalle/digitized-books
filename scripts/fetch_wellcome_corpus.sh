#!/usr/bin/env bash
# Fetch the Wellcome ★ picks from docs/CORPUS.md.
# Resumable: skips any <id>.sqlite that already exists in corpus/wellcome/.

set -u
cd "$(dirname "$0")/.."

OUT="corpus/wellcome"
LOG="$OUT/_fetch.log"
mkdir -p "$OUT"

# id|extra_flags|label
read -r -d '' WORKS <<'EOF' || true
ad56hqjs||Morris 1914 (T1)
cfn934u3||Cunningham Text-book 4th 1914 (T1)
kw6vt8gv||Cunningham Manual 1914 — 2 vols concatenated (T1)
mvaqfjxm||Piersol 1918 (T1)
dsgx7nzq||Gerrish 1899 (T1)
gw75hbbr||Quain 11th 1908 (T1)
cafpy896||Holden Dissection (T2)
dzmjbt9h||Ellis Demonstrations 1887 (T2)
jev9kze2||Gray UK 11th 1883 (T2)
d8quuwxg||Spalteholz 1929/30 English (T3)
kdckv24y||Sobotta English McMurrich 1927–28 (T3)
tgekje3p||Toldt 1919–20 (T3)
p747b7vs||Bourgery & Jacob 1831–54 (T3)
g6b6smge|--allow-empty|Vesalius Epitome 1543 — no ALTO (T4)
nrtzmcfn|--allow-empty|Valverde 1556 — no ALTO (T4)
resfyxts||Crooke 1618 (T4)
jfkydvqm||Cheselden Osteographia 1733 (T4)
r3thaf6m||Albinus Tabulae sceleti 1754 English (T4)
ugz833qz||Albinus Tabulae ossium 1753 (T4)
t6hqn97a||Albinus Tabulae uteri 1748–51 (T4)
wc7gxkcu||Hunter Gravid Uterus 1815 (T4)
cfbxq8k8||Cajal Histologie vol 1 1909–11 (T5)
akfqm42j||Cajal Histologie vol 2 1909–11 (T5)
gsfwgf65||Cajal Nouvelles idées 1894 (T5)
z8w4cbad||Edinger Vorlesungen 1911 (T5)
bjsh27ua||Ranson 3rd 1927 (T5)
vrnkkxtj||Brodmann 1909 (T5)
b69dh6vk||Schäfer Essentials 11th 1920 (T6)
n8dz65uv||Bailey Histology 1913 (T6)
v43geect||Sobotta Histologie 1929 (T6)
w8yhh68k||Keith Embryology 3rd 1913 (T6)
g9my2acs||McMurrich Development 1910 (T6)
h9n43hma||Sappey Traité descriptive 5th 1888–89 (T7)
dnbmq5p3||Sappey Traité générale 1894 (T7)
xugmyg7r||Hyrtl Lehrbuch 1889 (T7)
e5pwrbf9||Henle Knochen 1855 (T7)
xs8jejsy||Henle Bänder 1856 (T7)
cz73pq6c||Henle Muskel 1858 (T7)
veuxugxf||Henle Eingeweide 1862–66 (T7)
ywgnwrfg||Henle Gefäss 1868 (T7)
g84rzrx7||Henle Nerven 1879 (T7)
h8cwyqvx||Rauber-Kopsch 1912 (T7)
z3ny6kad||Bardeleben/Holl 1897 (T7)
wcjvv3n2||Bardeleben/Krause 1909 (T7)
f3xd4cyt||Bardeleben/Tandler 1913 (T7)
yd8qmy94||Poirier-Cunéo Lymphatics 1903 (T7)
EOF

ts() { date '+%Y-%m-%d %H:%M:%S'; }

total=0; done_count=0; skip_count=0; fail_count=0
declare -a FAILED=()

# Count totals
while IFS='|' read -r id flags label; do
  [ -z "$id" ] && continue
  total=$((total + 1))
done <<< "$WORKS"

echo "[$(ts)] Wellcome corpus fetch start — $total works → $OUT" | tee -a "$LOG"

idx=0
while IFS='|' read -r id flags label; do
  [ -z "$id" ] && continue
  idx=$((idx + 1))
  out="$OUT/$id.sqlite"

  if [ -s "$out" ]; then
    echo "[$(ts)] [$idx/$total] SKIP $id — $label (exists)" | tee -a "$LOG"
    skip_count=$((skip_count + 1))
    continue
  fi

  echo "[$(ts)] [$idx/$total] FETCH $id — $label" | tee -a "$LOG"
  # shellcheck disable=SC2086
  if uv run iiif-utils create-index -P wellcome $flags "$id" -o "$out" >>"$LOG" 2>&1; then
    sz=$(du -h "$out" 2>/dev/null | awk '{print $1}')
    echo "[$(ts)] [$idx/$total]   OK   $id ($sz)" | tee -a "$LOG"
    done_count=$((done_count + 1))
  else
    rc=$?
    echo "[$(ts)] [$idx/$total]   FAIL $id (rc=$rc) — see $LOG" | tee -a "$LOG"
    FAILED+=("$id ($label)")
    fail_count=$((fail_count + 1))
    rm -f "$out"
  fi
done <<< "$WORKS"

echo "[$(ts)] DONE — $done_count fetched, $skip_count skipped, $fail_count failed" | tee -a "$LOG"
if [ "$fail_count" -gt 0 ]; then
  echo "[$(ts)] Failed:" | tee -a "$LOG"
  for f in "${FAILED[@]}"; do echo "  - $f" | tee -a "$LOG"; done
  exit 1
fi
