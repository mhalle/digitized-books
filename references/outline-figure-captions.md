# Figure-caption extraction for plate atlases

Plate atlases (Spalteholz, Sobotta, Toldt, Bourgery atlas vols, Henle
*Hand-Atlas*) have a structural primitive that a chapter-style TOC and
body-text running headers both miss: the **numbered figure caption**.
Every named figure on every page is individually citable —
`Fig. 57. Skull, from the right`, `Fig. 61. Base of the skull, basis
cranii externa` — and these captions are usually preserved cleanly in
the body OCR.

The standard SKILL.md procedure produces a section-level outline.
The body-header fallback recovers a region-level outline. **Figure-caption
extraction gets you a per-figure outline** — usually 5–20× more entries
than the section-level pass, each one a named anatomical structure with
a single-page canvas anchor.

## When to use this

- The work is a plate atlas — figures are the primary content, not
  prose. Examples in this corpus: Spalteholz *Hand-Atlas*, Sobotta
  *Atlas* (both English and German), Toldt *Anatomischer Atlas*,
  Bourgery atlas vols, Henle *Hand-Atlas*.
- The body OCR has clean figure captions following a `<N>. <Title>`
  pattern at the start of a text block. Spot-check a few pages with
  `SELECT text FROM text_blocks WHERE page_id = <leaf> ORDER BY
  block_number` before committing.
- You've already produced a section-level outline (from TOC parsing or
  the body-header fallback). The figure captions become children of
  those sections.

## Procedure

### 1. Pattern-match figure captions

A figure caption typically looks like one of:

- `42. Frontal bone, a vertebrae.`
- `15 and 16. Right temporal bone, os temporale, ...`
- `25-26. Right ethmoidal labyrinth, ...`
- `158. Skull and cervical spine with ligaments, ...`

**Two text-block shapes are common, and you need to handle both:**

- **Standalone-caption block** — the figure number + title is its own
  short text block, ending where the caption ends. Spalteholz Vol 1
  pages look like this. The strict-anchored regex below catches it.
- **Caption-with-description block** — the caption is the first
  sentence, followed by multi-paragraph descriptive prose in the same
  text block (`Fig. 423. Frontalis muscle. — Form: ... Position: ...
  Origin: ... Insertion: ... Action: ... Innervation: ...`). Spalteholz
  Vol 2 has this throughout because the descriptive text travels with
  the figure. A strict `$` anchor and a short length cap both silently
  drop these.

The regex that catches both, with sentence-boundary truncation:

```python
import re

# Strict anchor — matches when the caption IS the whole block
strict = re.compile(r'^(\d+(?:\s+(?:and|to|—|–|-)\s+\d+)*)\.\s+([A-Z][^\n]*)$')

# Loose anchor — matches caption followed by descriptive prose
loose = re.compile(r'^(\d+(?:\s+(?:and|to|—|–|-)\s+\d+)*)\.\s+([A-Z][^\n.]+(?:\.[^\n]*?(?=\s+(?:Form|Position|Origin|Insertion|Action|Innervation|Course|Branches|M\.|N\.|A\.|V\.|Rr\.)\b))?)')

def parse(text):
    text = text.strip().replace('\n', ' ')
    m = strict.match(text)
    if m:
        return m.group(1), m.group(2)
    m = loose.match(text)
    if m:
        # Truncate at first sentence boundary if the title runs long
        title = m.group(2).strip()
        if len(title) > 200:
            sentence_end = re.search(r'\.\s+[A-Z]', title)
            if sentence_end:
                title = title[:sentence_end.start()]
        return m.group(1), title
    return None
```

Run it over the body text blocks. **Raise the length cap to ~4000
chars** so caption-with-description blocks aren't excluded:

```python
import sqlite3
con = sqlite3.connect('<db>')
figures = []
for r in con.execute(
    "SELECT page_id, block_number, text FROM text_blocks "
    "WHERE page_id BETWEEN <body_lo> AND <body_hi> "
    "AND length(text) BETWEEN 10 AND 4000"
):
    parsed = parse(r[2])
    if parsed:
        figures.append((r[0], parsed[0], parsed[1]))
```

### 2. Deduplicate by (canvas, fig_id)

Captions sometimes appear in multiple text_blocks on the same page
(figure title + figure subtitle, or split across blocks by ALTO).
Keep the first occurrence per `(page_id, fig_id)` pair.

### 3. Assign each figure to its parent section

Map each figure's `page_id` (= canvas) into the existing section-level
outline. The section whose `[canvas_start, canvas_end]` range contains
the figure's canvas is its parent. Prefer the deepest containing
section if multiple levels overlap.

### 4. Splice into the flat list

Build a fresh flat list by walking the existing outline in canvas
order and inserting each figure as a child of the current open
section. Each figure entry has:

```json
{
  "level": <parent.level + 1>,
  "title": "Fig. 57. Skull, from the right",
  "printed_page": 44,
  "notes": "extracted from figure caption in body text"
}
```

### 5. Resolve and re-import with `--replace`

Run the standard resolver. Figure entries share canvases with their
parent section's other figures; the resolver's same-canvas clamping
handles the case where two figures sit on the same printed page.

## What this captures vs. what it doesn't

**Captures:**
- Every figure that has a numbered caption following the pattern above.
- The verbatim title, preserving native anatomical vocabulary (`os
  hyoideum`, `basis cranii externa`, `labyrinthus ethmoidalis`).

**Misses:**
- Figures without numbered captions (uncommon — most 19th–20th c
  anatomical atlases number their figures).
- Sub-figures within a numbered group (e.g. `Fig. 15 and 16` is one
  outline entry, but the entry's title reflects both).
- Plate-only atlases without page-numbered body anchors (Cheselden's
  *Osteographia* — figures exist but `page_numbers` has nothing to
  anchor against).
- Caption text that wraps in OCR with spurious word breaks
  (`ri ght` for `right`, etc.) — preserved verbatim; downstream
  text-normalization handles these for search.

## Worked examples: Spalteholz Vols 1–3

| vol | sections | figure captions | total | content |
|---|---|---|---|---|
| v1 | 15 | 149 | 164 | Bones + Joints |
| v2 | 22 | 214 | 236 | Muscles + Vessels |
| v3 | 45 | 156 | 201 | Viscera + Brain + Nerves + Sense-Organs |

After the body-header fallback gave a section-level outline for each
volume, figure-caption extraction added the per-figure rows. Vol 1
worked with the strict anchored regex (captions are standalone text
blocks). Vols 2 and 3 needed the loose anchor + sentence-boundary
truncation because their pages mix caption text with multi-paragraph
descriptions in the same text block. Each named figure across the
trilogy is now individually citable:

- `Fig. 3. Occipital bone, os occipitale, viewed from in front` (Vol 1, p.3)
- `Fig. 44. Lower jaw bone, mandibula, from below` (Vol 1, p.35)
- `Fig. 423. Frontalis muscle` (Vol 2, p.262)
- `Fig. 567. Heart, from in front` (Vol 3, p.498)

This is the navigation density an anatomist actually wants from an
atlas — not "Bones of the Skull, pp. 4–71" but "the named figure of
the mandibula from below, page 35."

## Wellcome page-numbers gotcha

Wellcome's `page_numbers` table sometimes contains both Roman
front-matter pages OCR'd as Arabic AND the body's actual Arabic pages
with the same low numbers (e.g. `1, 2, 3, ...` for both front matter
*and* the body). The default first-occurrence rule in
`resolve_outline.py` maps page 5 to the *front-matter* leaf, which is
wrong when an outline entry is in the body.

If you encounter low-page entries landing on front-matter canvases:

- Symptom: an outline entry at `printed_page=5` has `canvas_start` ~3
  instead of ~20+.
- Workaround: derive `printed_page → canvas` from the body's running
  headers (more authoritative than `page_numbers` for the body) rather
  than the standard lookup. Or post-process the resolved payload to
  remap collisions using a last-occurrence rule for body pages.

This isn't specific to the figure-caption technique — Gray's *Anatomy*
1883 and Piersol Vol 1 both hit this in their main outline flow. Worth
flagging in the resolver as a future enhancement.
