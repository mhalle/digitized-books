# Fallback: synthesizing entries from body-text running headers

Sometimes the printed Table of Contents is incomplete — it only enumerates
the first half of the book, only the chapter titles even though the body
has named sub-sections, or stops mid-volume for editorial reasons. The
build-outline skill stays faithful to the printed source by default (only
transcribe what the printed TOC actually contains). But for some works
that's too thin, and the book's body text carries the structure as
**running headers** — the centered all-caps strings at the top of each
page (`UROGENITAL SYSTEM 177`, `VASCULAR SYSTEM 207`, `SKELETON 250`) — that
mark which named section the page belongs to.

Running-header transitions can be mined to recover the section structure.

## When to use this fallback

The printed TOC's last few entries absorb a huge canvas range (rule of
thumb: >50 pages with no sub-entries) and the body has obvious typographic
sectioning. This is a deliberate skill extension, not the default behavior
— every synthesized entry must be flagged.

## Procedure

### 1. Identify the unlabelled body region

Look at the existing outline (or the in-progress flat list). Find entries
whose `canvas_end - canvas_start` is implausibly large given what the TOC
said about that section. Note the canvas range that needs recovery.

### 2. Mine the running headers via `text_blocks`

The first one or two blocks of each canvas usually contain the running
header. Query for short, mostly-uppercase, header-style strings across
the unlabelled range:

All shell snippets here assume `uv run` — e.g. `uv run python3 -c '...'`.

```bash
uv run python3 -c "
import sqlite3, re
con = sqlite3.connect('<db>')
for r in con.execute('''
    SELECT page_id, length(text) as L, text
    FROM text_blocks
    WHERE page_id BETWEEN <lo> AND <hi>
    AND length(text) BETWEEN 8 AND 80
    AND text NOT LIKE '%.%'
    ORDER BY page_id, block_number
'''):
    text = r[2].strip()
    upper = sum(1 for c in text if c.isupper())
    alpha = sum(1 for c in text if c.isalpha())
    if alpha < 6: continue
    if upper / alpha < 0.6: continue
    if re.match(r'^Fig\b|^\d+\s*$', text): continue
    print(f'  leaf {r[0]:>4}  {text!r}')
"
```

What comes back is the running header on each page — usually a `<section
name> <page number>` or `<page number> <section name>` string. Where the
section name **changes** between consecutive pages, you've found a section
boundary.

### 3. Trace transitions to identify sections

Walk the result list in canvas order. The first appearance of a new
section name is the section's start canvas. Cross-reference its `page_id`
with `page_numbers` to get the printed page. Resolve sub-section
boundaries the same way (e.g. `UROGENITAL SYSTEM` is the parent;
`KIDNEY`, `WOLFFIAN BODY`, `GENITAL GLANDS` are sub-sections that appear
as running headers within the urogenital range).

### 4. Spot-check ambiguous OCR

Headers like `UROGENITAL SYSTEM` will sometimes OCR as `UEOGENITAL SYSTEM`
or `UROGENITAL SYSTEAI` — read past the noise. If a transition is
unclear, fetch one or two page images at higher resolution to confirm.

### 5. Splice the new entries into the flat list

Insert them at the appropriate location (usually as siblings of the last
legitimate TOC entry that absorbed the range), with the correct `level`
for the hierarchy you're building. Every synthesized entry gets a `notes`
field with the verbatim string:

```json
{
  "level": 1,
  "title": "Development of the Ear",
  "printed_page": 147,
  "notes": "synthesized from body-text running headers; not in printed TOC"
}
```

This makes synthesized entries auditable and downstream queries can filter
them out of "this came from the printed source" views if needed.

### 6. Re-resolve and re-import with `--replace`

The resolver will compute canvas ranges; the importer validates the same
constraints as for TOC-derived entries.

## What this technique can't recover

- **Sub-sub-section detail.** Running headers typically only carry the
  section name, not its internal structure. If you want every named
  anatomical structure under `WOLFFIAN BODY`, that requires reading body
  text page-by-page — not a running-header pass.
- **Mid-page transitions.** A page that contains the end of one section
  and the start of another has only one running header. Adjacent pages
  will show the transition; the actual transition page (and printed page
  number of the section's first body line) may need image-level
  verification.
- **Non-running-header books.** Some books don't use centered running
  headers at all — they print only page numbers, or alternate decorative
  ornaments, or no header text. The technique requires the source to use
  this typographic convention.

## Example: Quain *Elements of Anatomy* 1908 vol 1

The printed TOC stops at p.141 (Vitreous Body and Lens Capsule); the body
continues through p.260 with Ear, Olfactory Apparatus, Alimentary Canal,
Larynx, Ductless Glands, Pancreas, Urogenital System, Suprarenal Bodies,
Vascular System, Lymphatic System, Body-Cavity, Muscles, and Skeleton —
none of which appear in the printed Contents. Mining the running headers
across canvases 151–269 recovered 44 entries (13 level-1 sections + 31
level-2 sub-sections), bringing the outline from 68 entries (printed TOC
only) to 112 entries. Each synthesized entry carries the notes flag.
