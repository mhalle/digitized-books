# Building a navigation outline

Loaded on demand from `SKILL.md`. Transcribe a book's printed table
of contents and populate its `derived_outline` table.

Given an `iiif-utils` sqlite index for a digitized work (textbook, atlas,
monograph), find the printed Table of Contents, transcribe it from the
TOC images, and populate the `derived_outline` table via `iiif-utils
outline-import`.

The CLI handles the deterministic parts (validation, insertion). The
vision part — reading the printed TOC and emitting a structured entry
list — is what this skill is for. There is a script that does the
deterministic plumbing in between (page→canvas resolution, tree
assembly, range computation, same-canvas clamping); you don't need to
re-derive it.

## When to use

- The user asks to outline a work, build a TOC for a book in the corpus,
  populate `derived_outline` for a specific db, or set up navigation
  metadata for a scan.
- `iiif-utils outline-status <db>` shows no outline yet for the target.
- The work has a printed TOC (most textbooks and many atlases). Plate-only
  atlases without a TOC need a different procedure; see "Bailing out"
  below.

## What this skill writes

- A flat-JSON intermediate at `experiments/<short-name>_toc/flat.json`
  containing your TOC transcription.
- A nested-JSON payload at `experiments/<short-name>_toc/outline_payload.json`
  produced by the resolver script.
- Rows in the db's `derived_outline` table after the import succeeds.
- Cached TOC images at `experiments/<short-name>_toc/toc_pages/` for
  audit and re-runs.

`experiments/` is the conventional scratch location in this repo — see
the existing `experiments/ranson_toc/`, `cunningham_toc/`, etc. for
prior work.

## Tooling — always invoke CLI/Python via `uv run`

This repo manages its environment with **uv**. Every Bash invocation
in this skill must go through `uv run`:

- `iiif-utils <subcommand> ...` — NOT `iiif-utils ...` or
  `.venv/bin/iiif-utils ...`
- `uv run python3 ...` — NOT bare `python3 ...` or `.venv/bin/python ...`
- `uv run --no-project python3 scripts/resolve_outline.py ...`

The repo's permissions allowlist matches the `uv run *` pattern.
Direct invocations of `.venv/bin/*` or bare `python3 <script>`
typically fail with a Bash-denied error. If a command bounces, the
first thing to try is wrapping it in `uv run`.

## Procedure

### 1. Confirm the target needs an outline

```bash
iiif-utils outline-status <db_path>
```

If `outline_rows` is non-zero, the work already has an outline. Confirm
with the user whether to skip, re-run with `outline-clear` first, or
fix specific entries (which the skill doesn't cover — that's hand-SQL
or a fresh import).

### 2. Inspect the db: pagination + IIIF structure

```bash
uv run python3 -c "
import sqlite3
con = sqlite3.connect('<db_path>')
print('canvases:', con.execute('SELECT COUNT(*) FROM page_numbers').fetchone()[0])
print('arabic page span:',
      con.execute(\"SELECT MIN(CAST(book_page_number AS INT)), MAX(CAST(book_page_number AS INT)) FROM page_numbers WHERE book_page_number GLOB '[0-9]*'\").fetchone())
print('p.1 at leaf:',
      con.execute(\"SELECT leaf_num FROM page_numbers WHERE book_page_number='1' LIMIT 1\").fetchone())
print('IIIF ranges:')
for r in con.execute('SELECT label, canvas_start, canvas_end FROM ranges ORDER BY range_index'):
    print(f'  [{r[1]}..{r[2]}]  {r[0]!r}')
"
```

You're looking for:
- **A TOC range in the IIIF structures** — labelled `Table of Contents`,
  `Inhalt`, `Sommaire`, `Table des matières`, `Indice`, etc. with a
  non-null `canvas_start`. If present, use those canvases directly and
  skip to step 4.
- **The page→canvas offset** — typically `leaf = printed_page + N`. You
  don't need to use this; the resolver script handles it. But it's
  helpful to know what's normal so you can spot anomalies later.

### 3. Find the TOC canvases when IIIF doesn't pinpoint them

Most works don't have a labelled TOC range, or their range has null
canvas indices (e.g. Heidelberg). Scan for it:

**Front matter** (default first guess — most English and modern works):

```bash
uv run python3 -c "
import sqlite3, re
con = sqlite3.connect('<db_path>')
pat = re.compile(r'\b(contents|inhalt|inhaltsverzeichnis|sommaire|table\s+des\s+matières|indice|índice|tabula)\b', re.IGNORECASE)
for r in con.execute('SELECT page_id, text FROM text_blocks WHERE page_id < 30 ORDER BY page_id, block_number'):
    if pat.search(r[1] or ''):
        print(f'  leaf {r[0]}: {r[1][:80]!r}')
"
```

**Back matter** (Continental atlases and many German works put the
TOC at the end — Bourgery, Toldt, some Henle vols):

Replace `page_id < 30` with `page_id > (SELECT MAX(leaf_num)-30 FROM
page_numbers)`.

The hit gives you the start canvas of the TOC. The TOC is usually
**1–4 consecutive pages**; you'll confirm extent in the next step by
fetching and reading.

### 4. Fetch the TOC images at 1600 px

```bash
iiif-utils get-pages -i <db_path> --leaves <start>-<end> \
    --size '!1600,1600' --prefix experiments/<short>_toc/toc_pages/page
```

1600 px gives the VLM plenty of margin to read body type, dot-leader
columns, and small page numbers. Smaller resolutions will fail on
tightly-set indexes.

### 5. Read the TOC and transcribe

There are two TOC formats in this corpus, and they want different
primary sources:

- **Columnar / dot-leader TOC** (Ranson, Cunningham, Sobotta-style,
  most modern textbooks): one entry per typeset line, title on the
  left, dot-leader, page number on the right. Visually clean.
  **Use the page image as the primary source** via the `Read` tool —
  it captures hierarchy through indentation and gives you the page
  numbers in a column you can scan.

- **Run-on paragraph TOC** (Bourgery, some Continental 19th-century
  works): all entries in a section are one dense paragraph, separated
  by em-dashes, equals signs, or commas — e.g.
  `MUSCLES DU VOILE DU PALAIS, 53—55. Péristaphylin interne, 53.—
  Péristaphylin externe, 53, 54.= Glosso-staphylin, 54.…`
  Visual transcription is unreliable at this density (hundreds of
  entries in a few text blocks, easy to lose alignment).
  **Use the OCR in `text_blocks` as the primary source**, with the
  page image only to confirm typographic hierarchy (caps vs italic
  vs bold) when the OCR alone can't tell parent from child. Query
  the OCR like this:

  ```bash
  uv run python3 -c "
  import sqlite3
  con = sqlite3.connect('<db_path>')
  for leaf in [<toc canvases>]:
      print(f'=== leaf {leaf} ===')
      for r in con.execute('SELECT block_number, text FROM text_blocks WHERE page_id=? ORDER BY block_number', (leaf,)):
          print(r[1])
  "
  ```

  Then parse the run-on string into entries by splitting on the
  separators the book uses, recovering `title, printed_page` pairs.

  **Heidelberg-provider caveat**: Heidelberg's OCR doesn't preserve
  column structure. A two-column TOC layout will have left-column line
  N and right-column line N concatenated into the same string in
  `text_blocks`, in unpredictable order across blocks. The OCR is
  useful as a scaffold of named entities and page numbers, but you
  may need to fall back to the page images to disentangle which
  entries belong to which column. Wellcome's ALTO is column-aware
  and doesn't have this problem.

In both cases, emit a flat list of entries as a JSON file:

```json
{
  "work": "<filename-stem-of-the-sqlite>",
  "flat_entries": [
    {"level": 0, "title": "Chapter I — Origin and Function", "printed_page": 17},
    {"level": 1, "title": "The Diffuse Nervous System of Coelenterates", "printed_page": 19},
    {"level": 1, "title": "The Central Nervous System", "printed_page": 20},
    {"level": 0, "title": "Chapter II — The Neural Tube", "printed_page": 24},
    ...
  ]
}
```

#### Rules for transcription

The point of this skill is faithful capture of what's on the page —
the resolver does everything else.

**Per-entry fields:**

- `level` is the depth of the entry in the TOC's visual hierarchy.
  Top-level structural units are `0` (chapter, plate, Livre, Abteilung,
  region — whatever this book uses). Direct children are `1`. Deeper
  nesting goes `2`, `3`, etc. Use the typographic indentation and the
  numbering scheme as your cue. If a book has a meta-organizational
  header without a page number (e.g. "Section I" or "Première Division"
  appears as a sibling-grouping label only), include it at the
  appropriate level with the page number it implies (= the first child's
  page) and the resolver will treat it correctly.

- `title` is **verbatim** what the page shows. Preserve native
  vocabulary (*Chapter*, *Plate*, *Livre*, *Tafel*, *Abteilung*,
  *Section première*), preserve accents and ligatures, preserve the
  separator dash (—) used in headings like "Chapter VI — The Spinal
  Cord". No translation. No normalization. The title is what gets
  cited; the book's own language is canonical.

- `printed_page` is the page label printed next to the entry. Usually
  an integer (the arabic page number), but **strings are accepted** when
  the book uses non-arabic pagination:
  - Roman numerals — `"VII"`, `"III"`, `"LII"` for Roman-paginated
    supplements (common in 19th-century French anatomical works).
  - Letter pagination — `"a"`, `"g"`, `"A"` for letter-numbered front matter.
  - Plate labels — `"Planche 1"`, `"Tafel I-X"`, etc. when the book
    indexes plates by their printed plate-number rather than a page.

  Pass whatever the book prints, verbatim. The resolver does an
  exact-match lookup against `page_numbers.book_page_number` (with
  case-folding for Roman variants — `"vii"` matches `"VII"`).

  If a page number is genuinely illegible (OCR-style smudge, fold-out
  interruption, page-number artifact like "10⁰" for "109"), use your
  best inference from the surrounding context and add `"notes":
  "page number unclear, inferred as N from context"` to that entry.
  Linear extrapolation for missing pages only works in arabic sequences;
  Roman/letter labels must match exactly.

- `notes` is optional. Use it sparingly, only when the entry needs a
  caveat that won't be obvious from the data itself.

**On how deep to transcribe — be fine-grained:**

The outline's purpose is search and citation, so every named entry
that the TOC enumerates should become a row. Citing
"*Plexus brachial — Nerf médian*, p.70" is dramatically more useful
to a downstream user than citing "*Système nerveux périphérique*,
pp.205-296" (a section that contains it). Skipping detail you can
see in the TOC throws away free signal.

**Rule of thumb: if the book's TOC names it with a page number,
transcribe it.** A run-on paragraph that lists 50 muscles by name
with embedded page numbers (`Pectine, 98.—Moyen adducteur, 98.—Grand
adducteur, 99.—…`) produces 50 entries, not one. Hierarchy among
them comes from typography (caps for the section header above the
paragraph, body text for the entries inside it), so the 50 muscles
sit at one level below the section heading.

Concretely: Bourgery Bd 2's outline has 279 entries at depth 3 — every
named muscle gets a row. That's the right shape for this corpus, not
an outlier. Modern textbooks with columnar dot-leader TOCs (Ranson,
Cunningham) naturally have 50-120 entries because their TOC explicitly
enumerates only chapters and subsections. Continental 19th-century
works with dense run-on paragraph TOCs (Bourgery, Sappey) naturally
have 200-400 entries because their TOC enumerates every anatomical
structure by name.

**On OCR errors at small page numbers.** Dense paragraph TOCs frequently
mis-OCR small numbers (`i3o` for 130, `5g` for 59, `i?>i` for 121).
Don't skip those entries — fix the page number. Two recovery patterns:

1. **Trust the surrounding sequence.** If the entry before reads
   p.59 and the one after reads p.61, the mangled `5g` in between
   is almost certainly p.60. The TOC's page numbers within a section
   are monotonically increasing; use that to interpolate.
2. **Confirm against the page image.** The Read tool on the TOC
   image gives you the actual typeset number, no OCR errors. Use it
   to verify the entries the OCR mangled — you don't need to re-read
   the whole TOC, just spot-check the suspect ones.

The resolver's linear-extrapolation fallback handles entries where
you can't recover the page number — pass `printed_page` as your best
inference and add a `notes` field flagging it.

**On determining `level`:**

The book's own structure governs `level=0`, not a global rule:

- *Single-volume textbook with chapters and subsections* (Ranson):
  chapters are `level=0`, subsections `level=1`, sub-subsections `level=2`.
- *Dissection-room manual organized by region* (Cunningham): the regions
  ("The Superior Extremity", "The Inferior Extremity", "Abdomen") are
  `level=0` even though they have no page number of their own — they
  group the chapters that do.
- *Multi-volume work, one volume per db* (Rauber-Kopsch Abteilung V):
  the volume's internal top-level sections (`A. Allgemeine Neurologie`,
  `B. Spezielle Neurologie`) are `level=0`. The volume's title page is
  not an outline entry.
- *Liber/Caput structure* (Vesalius / Crooke): *Liber* is `level=0`,
  *Caput* is `level=1`.

The simple test: if removing this entry's child structure would still
leave a navigable structural unit, it's `level=0`. Subsections that
exist as further subdivision of a level-0 unit are `level=1+`.

**On same-canvas siblings:**

When two consecutive TOC entries point at the same printed page
(common — "Restiform Body, p.144 / Formatio Reticularis, p.144"; or
cranial nerves I/II/III all at p.293), write them both into the flat
list with the same `printed_page`. The resolver clamps the earlier
sibling to a single-canvas range and adds a note. You don't need to
do anything special.

**On compound entries spanning a numbering range:**

Sometimes the TOC shows one entry whose title combines multiple
chapter/lesson numbers — `Lessons XVII. and XVIII. — Glands of
the alimentary canal`, `Lessons XLVI., XLVII., and XLVIII. — Eye`.
The book bound those chapters together with a shared title block.
Treat it as **one TOC entry** with the verbatim compound title; the
range it covers is from its `printed_page` to the next entry's
`printed_page - 1`, same as any other entry. Do not synthesize three
separate entries for an "XLVI / XLVII / XLVIII" line.

**On unnumbered prefatory sections:**

Some books open with a section that has no chapter number — an
`INTRODUCTORY` block before Lesson I, an `INTRODUCTION` or
`PROLÉGOMÈNES` before *Livre Premier*, an `AVERTISSEMENT` before
the main body. If the TOC lists it with a page number, include it
as a `level=0` entry alongside the numbered top-level units (chapter,
plate, *Livre*, *Vorlesung*, etc.). If the TOC references it but it
has no page number of its own (because it's in letter-paginated front
matter), omit it from the outline — front matter without arabic
pagination can't be located on a canvas via the standard resolver.

### 6. Resolve to the nested payload

```bash
uv run --no-project python3 scripts/resolve_outline.py \
    <db_path> experiments/<short>_toc/flat.json \
    -o experiments/<short>_toc/outline_payload.json
```

This script handles:

- printed_page → canvas via the `page_numbers` table.
- Linear extrapolation for pages OCR missed (with `notes` flagging the
  inference per affected entry).
- printed_page_end / canvas_end computed via the next-same-or-lower-level
  rule.
- Same-canvas clamping (when two siblings start on the same printed page).
- Parent-range extension (when the last child shares its end canvas with
  the parent's next sibling).
- Tree assembly from the flat list (parent = most recent strictly-lower-level).

You don't need to write any of this yourself.

### 7. Import

```bash
iiif-utils outline-import <db_path> \
    experiments/<short>_toc/outline_payload.json
```

The CLI validates and inserts atomically. Validation errors point at
specific entries — fix the flat JSON, re-run step 6, re-import with
`--replace`.

### 8. Verify

```bash
iiif-utils outline-list <db_path> | head -50
```

Spot-check:
- Chapter titles read correctly with native vocabulary intact.
- Page ranges look plausible (no chapter spanning 200 pages in a
  300-page book unless that's really one chapter).
- Notes flag inferences and clamps where you expect them.

Show the result to the user, summarize what was done (entries
imported, any inferences or notes), and stop. Don't proactively add
the next thing.

## Fallback for incomplete printed TOCs

A small number of books have printed TOCs that don't enumerate the
whole body — they cover only the first half, or only the chapter
titles when the body has named sub-sections, or stop mid-volume for
editorial reasons. Symptom: the printed TOC's last few entries absorb
a huge canvas range (rule of thumb: >50 pages with no sub-entries)
and the body has obvious typographic sectioning.

For these, a separate technique mines the body-text **running
headers** (the centered all-caps strings at the top of each body
page — `UROGENITAL SYSTEM 177`, `VASCULAR SYSTEM 207`) to recover the
section structure. Every synthesized entry is flagged with `notes:
"synthesized from body-text running headers; not in printed TOC"` so
the artifacts stay auditable.

See [references/outline-body-header-fallback.md](outline-body-header-fallback.md)
for the SQL query, the trace-transitions procedure, and a worked
example (Quain *Elements of Anatomy* 1908 vol 1, 68→112 entries via
this technique). **Use only when the printed TOC alone really would
leave the outline thin**; this is a deliberate skill extension, not
the default behavior.

## Atlas-specific: figure-caption extraction

For **plate atlases** (Spalteholz, Sobotta, Toldt, Bourgery atlas vols,
Henle *Hand-Atlas*), the structural primitive isn't a chapter — it's
the **numbered figure caption** (`Fig. 57. Skull, from the right`).
Every named figure is individually citable, and the captions are
preserved verbatim in the body OCR. A section-level outline (15 entries
for Spalteholz Vol 1) becomes a per-figure outline (164 entries) by
mining `text_blocks` for the `^N. Title` pattern and inserting each
figure as a child of its containing section.

See [references/outline-figure-captions.md](outline-figure-captions.md)
for the regex, the deduplication and parent-assignment procedure, and
the worked Spalteholz Vol 1 example.

Use this **after** producing a section-level outline (TOC or
body-header fallback), as an enrichment pass. Don't use it for
non-atlas works — modern textbooks number their figures too, but their
chapter TOC already provides the structure you want.

## Bailing out

This skill **does not** apply to:

- **Plate-only atlases** with no textual TOC (Albinus *Tabulae sceleti*,
  Cheselden *Osteographia*, Hunter *Gravid Uterus*, some Bourgery atlas
  vols). These have an "Explanation of Plates" section that is itself
  the contents — they need per-plate caption extraction, a different
  procedure. If you can't find a TOC after scanning both front and back
  matter, stop and report `(no TOC found — possibly a plate atlas)`.
- **Pre-1600 works with zero OCR** (Vesalius *Epitome* `g6b6smge`,
  Valverde `nrtzmcfn`). The procedure assumes the body OCR is available
  for scanning. These are metadata-only stubs and need VLM-only TOC
  inspection, which this skill doesn't bundle.
- **Books with no internal structure at all** (some short monographs,
  pre-modern dedications-only works). If there's no TOC and no obvious
  chapter structure on a first read, an empty outline is fine — but
  confirm with the user that they want the outline left blank rather
  than synthesizing one.

## Common gotchas

- **`work` field mismatch.** `iiif-utils outline-import` requires that
  `payload.work` equals the sqlite filename stem (e.g. `bjsh27ua` for
  `bjsh27ua.sqlite`). The resolver passes this through from the flat
  input; just make sure you wrote it correctly there.
- **Plate fold-outs producing duplicate page numbers.** Cunningham has
  34 cases where two consecutive scan canvases both register as the
  same printed page (e.g. canvas 464 and 466 both = p.433). The
  resolver takes the first occurrence by canvas order, which is
  correct — the body page comes before the inserted plate.
- **Letter-paginated front matter** (A–J before arabic 1+). The
  `page_numbers` table stores these as letter strings; the resolver
  only looks at digit-parseable values, so they're harmlessly skipped.
- **Heidelberg dbs with null canvas indices in `ranges`.** A known
  schema gap — the IIIF labels are there but the canvas integers
  aren't. Fall back to the front/back-matter OCR scan.

## References

See [references/outline-examples.md](outline-examples.md) for pointers
to four working flat-JSON inputs (Ranson, Cunningham, Bourgery,
Rauber-Kopsch) corresponding to four already-imported outlines.
Reading them is the fastest way to calibrate what a complete
transcription looks like for a given book shape.

The data schema and CLI command reference live in
[docs/OUTLINE.md](../../docs/OUTLINE.md) and
[docs/OUTLINE_SCHEMA.json](../../docs/OUTLINE_SCHEMA.json).
