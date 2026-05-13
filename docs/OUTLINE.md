# `derived_outline` — synthesized navigation outline

Every per-work sqlite index produced by `iiif-utils create-index` can
optionally carry a `derived_outline` table: a hierarchical outline of
the work's chapters, sections, plates, or whatever its native structure
is.

This is a **derived** artifact, not a faithful transcription of the
printed table of contents. Entries may come from the TOC, from
per-plate caption extraction, from typographic detection in the body,
from the IIIF manifest's `ranges`, or from manual correction. The
schema doesn't try to taxonomize provenance per row — anything worth
calling out lives in the freeform `notes` column.

The CLI in this package is **deterministic plumbing only**. It loads
JSON into the table, prints what's there, and clears it. The
non-deterministic step — figuring out *what the outline should be* —
happens outside `iiif-utils`, typically by feeding TOC images to a
vision-capable LLM.

## Schema

```sql
CREATE TABLE derived_outline (
  id                 INTEGER PRIMARY KEY,
  level              INTEGER NOT NULL,
  parent_id          INTEGER REFERENCES derived_outline(id),
  title              TEXT    NOT NULL,
  printed_page_start INTEGER,
  printed_page_end   INTEGER,
  canvas_start       INTEGER NOT NULL,
  canvas_end         INTEGER NOT NULL,
  notes              TEXT
);
CREATE INDEX ix_outline_canvas ON derived_outline(canvas_start);
CREATE INDEX ix_outline_parent ON derived_outline(parent_id);
```

| column | required | meaning |
|---|---|---|
| `id` | auto | opaque row id; auto-assigned. |
| `level` | yes | depth in the tree, `0` for roots. Must equal the nesting depth in the import payload — redundant with the tree shape, but kept explicit so each row stands alone. |
| `parent_id` | no (NULL for roots) | navigation only. Boundaries are stored on each row, so consumers that don't need hierarchy can ignore this. |
| `title` | yes | the native heading as the work announces it — `CONTENTS`, `Inhalt`, `Chapter VI — The Spinal Cord`, `Plate XI`, `Liber I, Caput III`. No normalization. |
| `printed_page_start` / `printed_page_end` | no | printed page numbers, when known. Front matter, unpaginated plates, and synthetic entries may be NULL. |
| `canvas_start` / `canvas_end` | yes | the `page_numbers.leaf_num` range, **stored explicitly** — not computed from siblings at query time. |
| `notes` | no | short human-readable caveat. See "On `notes`" below. |

Each row is **self-contained**: its canvas range is on the row, not
inferred from neighbors. `parent_id` exists for hierarchy traversal
but is not load-bearing for ordering or boundaries.

Ordering is by `id`. The importer walks the JSON tree top-down and
sqlite assigns ids in insertion order, so `id` order is reading order:
parents appear before children, siblings appear in payload order, and
same-canvas siblings (a chapter and its opening subsection, or two
consecutive subsections that share a printed page) sort exactly as the
payload had them.

`canvas_start` is also monotonic in id order — the validator enforces
that — so sorting by `id` alone gives the same sequence as sorting by
`(canvas_start, id)`. `id` is simpler and unambiguous; use it.

The canonical sort is therefore `ORDER BY id`. The `outline-list`
command does this; SQL queries against the table should do the same
when ordering matters.

## CLI

### `iiif-utils outline-import <index_path> <payload_path>`

Bulk-load a JSON outline into a work's sqlite index. The operation is
atomic — validation errors or insertion failures roll back the
transaction; a partial outline is never left behind.

```bash
# normal import
iiif-utils outline-import corpus/wellcome/bjsh27ua.sqlite outline.json
# → imported 122 outline entries into corpus/wellcome/bjsh27ua.sqlite

# validate without writing
iiif-utils outline-import corpus/wellcome/bjsh27ua.sqlite outline.json --dry-run
# → OK (dry-run): 122 entries valid for bjsh27ua

# overwrite an existing outline
iiif-utils outline-import corpus/wellcome/bjsh27ua.sqlite outline.json --replace
# → imported 122 outline entries into corpus/wellcome/bjsh27ua.sqlite
```

**Validations enforced:**

- `payload.work` matches the db's work id (the value returned by
  `outline.work_id()` — the sqlite filename stem, e.g. `bjsh27ua` for
  `bjsh27ua.sqlite`).
- `entries` is a non-empty array.
- Every entry has `level`, `title`, `canvas_start`, `canvas_end`.
- `canvas_end >= canvas_start`.
- Canvas indices lie within `[0, max(page_numbers.leaf_num)]`.
- Each entry's `level` equals its nesting depth in the tree.
- Each child's `[canvas_start, canvas_end]` is within its parent's range.
- Flattened `canvas_start` values are non-decreasing.

Without `--replace`, the command refuses to import when
`derived_outline` already has rows. Pass `--replace` to clear-then-import
in a single transaction.

### `iiif-utils outline-list <index_path> [--format tree|table|json|jsonl|records]`

Pretty-print the outline. The default `tree` format renders an
indented hierarchical view; the other formats emit one row per entry
for piping into other tools.

```bash
$ iiif-utils outline-list corpus/wellcome/bjsh27ua.sqlite
Origin and Function of the Nervous System pp.17-23  [c.16-22]
  The Diffuse Nervous System of Coelenterates pp.19  [c.18]
  The Central Nervous System pp.20-23  [c.19-22]
The Neural Tube and its Derivatives pp.24-36  [c.23-35]
  ...
```

Notes attached to a row are shown indented underneath with a `↳` marker.

### `iiif-utils outline-clear <index_path> [--yes]`

Delete all rows from `derived_outline`. The table itself is kept; use
this before re-importing an outline. Other tables (`page_numbers`,
`text_blocks`, `illustrations`, `ranges`, …) are untouched.
Confirmation is required unless `--yes` is passed.

### `iiif-utils outline-status <index_path> [<index_path> ...]`

Across one or more sqlite indices, print a one-row summary showing
canvas count, outline row count (or `—` when absent), top-level
entries, and max nesting depth. Useful for tracking outline-population
progress across the corpus.

```bash
iiif-utils outline-status corpus/wellcome/*.sqlite corpus/heidelberg/*.sqlite
```

Pipe-friendly formats: `--format jsonl` / `json` / `records`.
`--missing-only` filters to indices that have no outline yet — the
natural batch-driver input.

## Payload format

```json
{
  "work": "bjsh27ua",
  "entries": [
    {
      "level": 0,
      "title": "Origin and Function of the Nervous System",
      "canvas_start": 16,
      "canvas_end": 22,
      "printed_page_start": 17,
      "printed_page_end": 23,
      "children": [
        {
          "level": 1,
          "title": "The Diffuse Nervous System of Coelenterates",
          "canvas_start": 18,
          "canvas_end": 18,
          "printed_page_start": 19,
          "printed_page_end": 19
        },
        {
          "level": 1,
          "title": "The Central Nervous System",
          "canvas_start": 19,
          "canvas_end": 22,
          "printed_page_start": 20,
          "printed_page_end": 23
        }
      ]
    },
    {
      "level": 0,
      "title": "The Neural Tube and its Derivatives",
      "canvas_start": 23,
      "canvas_end": 35,
      "printed_page_start": 24,
      "printed_page_end": 36,
      "children": []
    }
  ]
}
```

The `work` field must match the value `outline.work_id()` returns for
the target db — the sqlite filename stem. Every provider's file
naming follows the convention: Wellcome single-manifest works are
named after their `catalogue_id` (`bjsh27ua.sqlite`); Heidelberg works
are named after `identifier:heidelberg_diglit`
(`bourgey1832bd1_1.sqlite`); Wellcome Collection-child manifests use
`<parent_id>_v<N>` (`mvaqfjxm_v1.sqlite`).

`printed_page_start`, `printed_page_end`, `notes`, and `children` are
all optional. `level` must equal the nesting depth (top-level entries
are `0`, their children are `1`, etc.).

**On what belongs at `level = 0`.** "Level 0" means the topmost
structural unit *in this manifest* — whatever the work calls it. In
the Ranson example above it's a chapter, because Ranson is a single
volume with no umbrella. Other shapes that also live at level=0:

- **Bound-together volumes.** A IIIF manifest that concatenates two or
  more volumes (e.g. Cunningham *Manual of Practical Anatomy* 1914,
  Wellcome `kw6vt8gv` — a 2-volume work in one 752-canvas manifest)
  puts each volume at level=0, chapters at level=1, subsections at
  level=2. The volume break is usually identifiable from the IIIF
  `structures` table (a second `Cover` range, a `Vol. 2` label).
- **Early-modern *Liber* works.** Vesalius / Crooke / Valverde use
  *Liber I, Liber II*… as the top unit, with *Caput* (chapters) below.
- **Multi-sequence works.** An atlas with both a "Contents" and a
  separate "List of Plates" sequence is naturally expressed as two
  parallel level=0 roots, one per sequence.

**On a synthetic "CONTENTS" / "Inhalt" root.** The schema enforces
that each child's `[canvas_start, canvas_end]` lies within its
parent's. A TOC-heading root cannot be parented at the TOC pages only
(e.g. canvases 12–14) while listing chapters that live at canvases
16+ — the children would fall outside the parent. If you want such a
root, give it a range that spans all its children, and note the TOC's
actual location in `notes`. The simpler convention is to omit the
synthetic root entirely.

A machine-validatable JSON Schema lives at
[`docs/OUTLINE_SCHEMA.json`](OUTLINE_SCHEMA.json).

## On the `notes` column

`notes` is for **human-readable caveats that don't need to be queried.**
If you'd ever filter on it, that's a typed column instead.

Typical uses:

- *Why this entry exists when it isn't from the TOC* — "synthesized
  root, work has no titled heading"; "from IIIF range labelled
  'Bibliography'"; "extracted from caption on canvas 47".
- *OCR / transcription corrections* — "TOC printed as `10⁰`,
  interpolated as 109".
- *Resolution offsets applied* — "printed_page resolved via −1 offset".
- *Manual edits* — "corrected title 2026-05-12 from VLM misread".

Conventions: short — one sentence per caveat, separated by `; ` when
multiple. Plain English, no codes. NULL is the common case.

## Building an outline — typical workflow

The CLI does not call any VLMs or external services. The intended
end-to-end workflow is:

1. **Identify the TOC canvases.** Check the manifest's IIIF `ranges`
   first; many providers label "Table of Contents" / "Inhalt" /
   "Sommaire" / "Table des matières" directly. Otherwise scan front
   matter (and, for Continental atlases, back matter) for centered
   uppercase headings.

2. **Fetch those canvases** at a readable resolution. Body text on
   typical 20th-century textbooks is comfortably legible at
   `~700 px` page-width; for TOC parsing, `1600 px` gives the VLM
   plenty of margin.

   ```bash
   iiif-utils get-pages -i corpus/wellcome/bjsh27ua.sqlite \
     --leaves 12-14 --size '!1600,1600'
   ```

3. **Drive the VLM** outside `iiif-utils`. Hand it the images plus
   a prompt asking for the structured payload above. The model,
   the prompt, and the correction workflow are out of scope for
   this package.

   **Multi-volume manifests.** Some IIIF manifests concatenate
   multiple physical volumes into one (e.g. Cunningham *Manual of
   Practical Anatomy* 1914, Wellcome `kw6vt8gv` — two volumes; other
   bound-together works can carry three or more). Each volume has its
   own printed TOC in its own front matter, parsed independently. The
   volume boundaries are usually identifiable from the IIIF `structures`
   table — look for repeated `Cover` ranges, or labels like
   `Vol. 2 — Title page`. The resulting payload has one level=0 entry
   per volume with chapters at level=1 underneath.

   *Page-number resolution must be volume-scoped* if printed pagination
   restarts within each volume (which is common for bound-together
   editions). Scan `page_numbers.book_page_number` for duplicates across
   the manifest — duplicates mean restarted pagination and the
   resolver must constrain `printed_page → canvas` lookup to the
   target volume's `[canvas_start, canvas_end]` range.

4. **Import** the resulting JSON:

   ```bash
   iiif-utils outline-import corpus/wellcome/bjsh27ua.sqlite outline.json
   ```

5. **Verify**:

   ```bash
   iiif-utils outline-list corpus/wellcome/bjsh27ua.sqlite
   ```

If the VLM got something wrong, edit `outline.json`, re-run with
`--replace`. For one-off fixes, hand-SQL is fine too — the schema is
small enough that `UPDATE derived_outline SET title=… WHERE id=…` is
no more painful than editing the JSON.

## Querying the outline

`canvas_start` / `canvas_end` are stored explicitly on every row, so
typical lookups don't need a recursive CTE:

```sql
-- Canvas range for the chapter on the spinal cord
SELECT canvas_start, canvas_end FROM derived_outline
WHERE level = 0 AND title LIKE 'The Spinal Cord%';

-- Every entry across the corpus that mentions 'lymphatic'
SELECT title, canvas_start FROM derived_outline
WHERE title LIKE '%lymphatic%' OR title LIKE '%lymphatique%'
ORDER BY id;
```

A recursive CTE is only needed for tree-shaped output — see
`outline-list`'s implementation.

**Reading-order traversal.** `ORDER BY id` is the canonical sort.
`id` is autoincremented in insertion order, the importer walks the
JSON tree top-down, and the validator enforces monotonicity of
`canvas_start` — so `id` order is reading order, with no tiebreaker
needed.
