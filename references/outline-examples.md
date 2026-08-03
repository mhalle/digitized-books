# Worked examples

Four works have been outlined end-to-end and round-trip cleanly through
the resolver. Read these when you need to calibrate the shape of a flat
transcription for a particular book type.

| work | db | language | source | shape highlights |
|---|---|---|---|---|
| Ranson 1927 — Anatomy of the Nervous System | `corpus/wellcome/bjsh27ua.sqlite` | English | Wellcome single-manifest | 21 chapters at level-0, 2-level nesting, 3 back-matter entries (Laboratory Outline, Bibliography, Index). IIIF labelled the TOC at canvases 12–14. 118 entries total. |
| Cunningham *Manual* 1914 | `corpus/wellcome/kw6vt8gv.sqlite` | English | Wellcome single-manifest | 3 anatomical regions at level-0 (Superior Extremity, Inferior Extremity, Abdomen) + INDEX; chapters under each region. Same-canvas siblings: Anal Triangle / Urogenital Triangle of Female Perineum both at p.369. Plate fold-out duplicate scans cause 34 duplicate page-numbers, handled transparently. 50 entries. |
| Bourgery Bd 1 1832 — *Anatomie descriptive* | `corpus/heidelberg/bourgey1832bd1_1.sqlite` | French | Heidelberg | TOC at **end** of book (canvases 198–200), Continental convention. Five level-0 entries: INTRODUCTION, PROLÉGOMÈNES, PREMIÈRE PARTIE, TABLE DES MATIÈRES (the TOC pages themselves), ERRATA. 4-deep hierarchy with `Livre / Section / sub-section`. Letter-paginated front matter (A–J), arabic body 1–188. Native French vocabulary preserved. 54 entries. |
| Rauber-Kopsch Abteilung V 1912 — *Lehrbuch der Anatomie* | `corpus/wellcome/h8cwyqvx.sqlite` | German | Wellcome single-manifest | Volume V of a multi-volume Lehrbuch, all neurology. Top-level `A. Allgemeine Neurologie / B. Spezielle Neurologie / Register`. 4-deep nesting (`B → II. Gehirn → 5. Gehirnabteilungen → F. Telencephalon → I. Äußere Oberfläche`). Same-canvas cluster: cranial nerves I/II/III all at p.293, IV/V at p.299, VI/VII at p.315 — all handled by the resolver's clamping. OCR gap from p.451+ — handled by linear extrapolation, each affected entry gets a note. 88 entries. |

The flat-JSON intermediate for each (which the resolver consumes)
lives at:

- `experiments/ranson_toc/outline_payload.json` (already nested, but
  flattenable as a reference for shape)
- `experiments/cunningham_toc/outline_payload.json`
- `experiments/bourgery_toc/outline_payload.json`
- `experiments/rauber_kopsch_toc/outline_payload.json`

The resolver round-trips all four — see the smoke-test results in the
SKILL.md or run:

```bash
# Pull any nested payload back to flat, then re-resolve and dry-run.
# Should validate with the same entry count.
uv run python3 -c "
import json; from pathlib import Path
orig = json.loads(Path('experiments/ranson_toc/outline_payload.json').read_text())
flat = []
def walk(node, level):
    flat.append({'level': level, 'title': node['title'],
                 'printed_page': node['printed_page_start']})
    for c in node.get('children', []):
        walk(c, level + 1)
for n in orig['entries']:
    walk(n, 0)
Path('/tmp/check.json').write_text(json.dumps({'work': orig['work'], 'flat_entries': flat}))
"
uv run python3 skills/build-outline/scripts/resolve_outline.py \
    corpus/wellcome/bjsh27ua.sqlite /tmp/check.json -o /tmp/check_resolved.json
uv run iiif-utils outline-import corpus/wellcome/bjsh27ua.sqlite \
    /tmp/check_resolved.json --dry-run
# → OK (dry-run): 118 entries valid for bjsh27ua
```

## What each example exercises

- **Ranson** — the simplest happy path. English, modern type, IIIF
  labels the TOC, clean front-matter pagination. Start here if you've
  never run this skill before.
- **Cunningham** — region-based top hierarchy without page numbers
  (Superior Extremity / Inferior Extremity / Abdomen as labels above
  chapter lists), and the duplicate-scan handling. Demonstrates that
  the resolver's first-occurrence rule on `page_numbers` is correct.
- **Bourgery** — back-matter TOC location, French native vocabulary
  with accents and ligatures, deep hierarchy (Partie / Division /
  Livre / Section), letter-paginated front matter coexisting with
  arabic body.
- **Rauber-Kopsch** — deep nesting plus extensive same-canvas
  collisions plus OCR gaps requiring linear extrapolation. The
  toughest of the four; if your case looks like this, expect notes
  on multiple entries.
