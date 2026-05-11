# iiif-utils — Design Sketch

A command-line utility for discovering, indexing, and downloading material from
IIIF-based digitized collections. Modeled on
[`ia-utils`](../../internet-archive/ia-utils) with the explicit goal that the
SQLite indexes it produces should be **structurally compatible** with `ia-utils`
indexes wherever possible, so the same query patterns, skill files, and
downstream tooling work across both archives.

First-class provider: **Wellcome Collection**. Architecture is
provider-pluggable so additional sources (Bodleian, Gallica/BnF, Library of
Congress, Stanford, Harvard, Bibliothèque Nationale, Vatican DigiVatLib,
Cambridge Digital Library, Princeton, NLM, etc.) can be added by dropping in a
provider module and a config entry.

---

## 1. Why a separate tool

`ia-utils` is tightly bound to the Internet Archive's REST/Python API, its
file-naming conventions (`_hocr.html`, `_hocr_searchtext.txt.gz`,
`_hocr_pageindex.json.gz`), and its leaf-number addressing scheme. The IIIF
world is fundamentally different in three ways:

1. **Identifiers are URLs.** A IIIF item is identified by the URL of its
   Presentation API manifest. There is no global "identifier" string; each
   provider has its own opaque IDs (Wellcome b-numbers, Gallica ARKs, LoC
   service IDs, etc.).
2. **Discovery varies per provider.** IIIF defines no universal search API for
   the corpus. Each provider exposes its own catalogue/search endpoint
   (Wellcome Catalogue API, Gallica SRU, LoC JSON API, etc.). A few providers
   expose IIIF Change Discovery activity streams; most do not.
3. **OCR and text are not standardized.** The IIIF Content Search API (v0/v1/v2)
   may exist or may not. Plain text, ALTO XML, hOCR, METS-ALTO, and inline
   `seeAlso` annotation lists are all common alternatives. PDFs are sometimes
   available via `rendering`.

A new tool lets us model these properly without contorting `ia-utils`. The
SQLite schema, however, can stay deliberately close so a single skill or LLM
prompt can work over either kind of index.

### IIIF-only capabilities (not possible in `ia-utils`)

IIIF unlocks a few things IA cannot do — these are the value-add of
this tool, not just feature parity:

1. **Region-level image URLs on demand.** The IIIF Image API exposes
   any rectangular subregion of any canvas as a stable HTTP URL:
   `{image_service_url}/{x,y,w,h}/{size}/{rotation}/{quality}.{format}`.
   Construct, share, embed, or fetch — no source download, no
   server-side image processing on our end. IA's `download/...` URLs
   are whole-image-only.
2. **First-class figure extraction.** ALTO `<Illustration>` regions
   parsed at index time populate the `illustrations` table. Combined
   with (1) every figure becomes a directly fetchable URL.
   Demonstrated end-to-end in `experiments/morris_index/`: an FTS
   query for "femur" → caption block on canvas 198 → adjacent
   illustration bbox → working URL
   `https://iiif.wellcomecollection.org/image/b21212600_0199.jp2/454,306,694,2370/1400,/0/default.jpg`
   returning an anatomical plate of the left femur with labels.
   `ia-utils` has no analog because IA does not segment figures.
3. **Arbitrary-region cropping by `(page, bbox)`.** Same Image-API
   mechanism, but driven by any source of bboxes — a `text_blocks`
   row, a Content Search hit's `#xywh=` fragment, a hand-supplied
   region. Powers `get-region` (a new command) and `get-page
   --region`.
4. **No bulk source download to view a figure.** A user can click
   through from an FTS hit to a tightly-cropped image of just the
   matched line or figure, fetching only that bbox — useful in
   constrained environments (offline corpora with the SQLite shipped
   but images served from Wellcome's CDN).

`get-figure`, `get-region`, and the `--region` flag on existing
commands are therefore M1 deliverables (§11), not v1.5 niceties — the
data is already in the schema and URL construction is two-line code.

---

## 2. Concept mapping: IA ↔ IIIF

| Internet Archive concept              | IIIF equivalent                                   | Notes |
|---------------------------------------|---------------------------------------------------|-------|
| Item (`identifier`)                   | Manifest (`@id` / `id` URL)                       | Item is the unit of indexing. |
| Files in item (`files.xml`)           | `rendering` array on manifest + canvas-level seeAlso | PDFs, ALTO, plain text, EPUB. |
| Leaf (`leaf42`)                       | Canvas (0-indexed within sequence/items)           | Canvas is the page. |
| Book page number                      | Canvas `label` (often the printed page) or `nav-place` index | Often a string ("xii", "145", "Plate IV"). |
| `hocr` / `djvu` / `searchtext` modes  | One ALTO mode with full bboxes (§3.5). IIIF providers don't generally publish a cheap per-page plain-text source, so multiple modes aren't useful. |
| Image URL (per leaf)                  | Image API service URL on canvas                   | URL template: `{base}/{region}/{size}/{rotation}/{quality}.{format}`. |
| `download/{id}/{filename}`            | `rendering` URLs (often direct CDN paths)         | |
| Multi-volume (sibling items)          | IIIF Collection (`Collection` resource)           | A Collection points at child manifests. |

With this mapping, the same SQLite tables can absorb both worlds with very
small additions.

---

## 3. SQLite schema

The schema is a superset of `ia-utils`'s. Tables and column names match where
the meaning is the same, with a small number of additions for IIIF-specific
data. v1 has one ALTO-derived mode with full bboxes; see §3.5 "Why one
mode, not two" for why we don't ship `searchtext`/`djvu`/`hocr` mode
distinctions like IA does.

### 3.1 `index_metadata` (key-value, identical to IA)

| Key | Description |
|-----|-------------|
| `slug` | Human-readable filename base. |
| `created_at` | ISO-8601 timestamp. |
| `index_mode` | `alto` for v1 (only mode shipped). Reserved for future modes if a provider offers a cheap per-page text source — see §3.5. |
| `provider` | **New.** Provider key from config (e.g. `wellcome`, `gallica`, `loc`). |
| `manifest_url` | **New.** Canonical manifest URL. |
| `presentation_api_version` | **New.** `2` or `3`. |
| `search_api_version` | **New.** `0`, `1`, `2`, or `none`. |
| `iiif_utils_version` | **New.** Tool version that wrote the index. |

### 3.2 `document_metadata` (key-value, identical to IA)

Same shape as `ia-utils`: `(key TEXT PRIMARY KEY, value TEXT)`. Populated from
the manifest's `label`, `metadata` array, `requiredStatement`, `rights`,
`provider`, `homepage`, `seeAlso`, plus a `provider_record` slot for the raw
provider catalogue record (JSON-encoded) when discovery returned one. We
deliberately keep the IA key vocabulary (`title`, `creator`, `date`,
`subject`, `language`, `description`, `identifier`) and add IIIF-native keys
alongside them (`manifest_url`, `rights`, `attribution`, `homepage`).

This means an LLM or downstream consumer that already knows
`SELECT value FROM document_metadata WHERE key='title'` keeps working unchanged.

**Rights handling — raw vs. override.** Provider-stated rights can be wrong
or out of date (Wellcome routinely marks pre-1929 works as `inc` /
"in copyright" when they are in fact public domain in the US under the
pre-1929 rule, or in EU jurisdictions under life+70). The schema slots
both:

| Key | Source |
|-----|--------|
| `rights` | The IIIF `rights` URI as served (e.g. `https://creativecommons.org/publicdomain/mark/1.0/`). |
| `license` | Provider shorthand if exposed (`pdm`, `inc`, `cc-by-nc`, etc.). |
| `rights_override` | Optional. User-supplied override (e.g. `pd-us-pre-1929`). |
| `rights_override_reason` | Optional. Human-readable rationale. |

The override fields are populated only when the user passes
`create-index --rights-override <code> [--rights-override-reason <text>]`.
The tool never *infers* rights — it only records what the user asserts and
its raw counterpart. Downstream filtering can use either, with the
override taking precedence when present.

### 3.3 `archive_files` (renamed concept, same shape)

```sql
CREATE TABLE archive_files (
    filename TEXT PRIMARY KEY,
    format TEXT,
    size_bytes INTEGER,
    source_type TEXT,          -- 'rendering' | 'seeAlso' | 'derivative'
    md5_checksum TEXT,
    sha1_checksum TEXT,
    crc32_checksum TEXT,
    download_url TEXT
);
```

For IIIF, rows come from manifest-level `rendering` entries (PDF, EPUB, plain
text, METS) and from canvas-level `seeAlso` entries when they describe
whole-item resources. `filename` is derived from the URL path; checksums and
size are usually NULL (IIIF rarely publishes them).

### 3.4 `page_numbers` (analog of IA's table, extended)

```sql
CREATE TABLE page_numbers (
    leaf_num INTEGER PRIMARY KEY,    -- canvas index, 0-indexed
    book_page_number TEXT,           -- printed page from canvas label
    confidence INTEGER,              -- NULL for IIIF (no analog)
    pageProb INTEGER,                -- NULL
    wordConf INTEGER,                -- NULL
    -- IIIF additions:
    canvas_id TEXT NOT NULL,         -- full canvas URI
    canvas_label TEXT,               -- raw label (may be JSON for v3 langs)
    image_id TEXT,                   -- annotation body / image resource id
    image_service_url TEXT,          -- IIIF Image API service base
    image_api_version TEXT,          -- '2' or '3'
    width INTEGER,
    height INTEGER
);
```

`leaf_num` is the canvas index in the manifest's sequence (v2) or `items`
array (v3). This preserves the IA convention that `leaf_num` is the natural
addressing scheme and that book/printed page numbers are a separate, lossy
mapping.

**Empirical mapping for Wellcome** (audited across 4 works in
`experiments/page_numbers/`: Spalteholz Vol 1, Cunningham Manual 1914,
Morris Anatomy 1914, Wellcome reference fixture `b22396147`):

- Canvas `label` is the only source of structured page-number data.
- Wellcome uses exactly two label vocabularies: literal `'-'` or a digit
  string (e.g. `'126'`). No roman numerals, no folio marks (`1r`/`1v`),
  no compound labels (`"Plate IV"`) in any sampled work.
- Mapping: `'-'` → `book_page_number = NULL`; digit string → stored
  as-is (TEXT, no integer coercion — same as IA).
- `canvas_label` always stores the raw label string, even when
  `book_page_number` is NULL — preserves provenance.

**Known data-loss limitations for Wellcome:**

1. **Roman-numeral front matter.** Wellcome encodes every roman-numbered
   page as `'-'`, but the printed numbers *are* in the OCR text.
   Verified on Morris Anatomy 1914: canvas 11 / label `'-'` / ALTO top
   reads `vi ARRANGEMENT OF...`; canvas 13 / label `'-'` / ALTO top
   reads `viii EDITOR'S PREFACE...`. A v1.5 backfill could scan
   page-edge `text_blocks` rows for an isolated roman token and
   populate `book_page_number`. v1 leaves them NULL.
2. **Non-monotonic numbering exists.** Cunningham Manual had 7
   non-monotonic transitions in its numbered run; Spalteholz vols 1 & 2
   had 1 each. Causes: plate insertions, mid-volume printing quirks,
   or (Cunningham case) the within-manifest concatenated volume
   boundary. Consumers should not assume `book_page_number` is strictly
   increasing with `leaf_num`.
3. **In a Collection-of-Manifests work, `book_page_number` is not a
   unique key across volumes.** Spalteholz vol 1 ends at p.257; vol 2
   starts at p.255 (overlap from a vol-break that lands mid-section).
   Use `(canvas_id, book_page_number)` for unique lookups.

For non-Wellcome providers (Bodleian, Gallica, LoC, etc.) the canvas
label vocabulary will be richer — roman numerals, folio marks, plate
designations, compound prefixes. The v1 parser stores the label string
as-is, with `'-'` and empty strings mapped to NULL. A normalizer for
common prefixes (`"p. "`, `"Plate "`) is a v1.5 enhancement.

The `image_service_url` is the killer column for IIIF: with it you can build
arbitrary tile/region/size requests on demand.

### 3.5 `text_blocks` — empirically grounded

The schema decisions below are grounded in the Spalteholz study under
`experiments/alto_vs_ia/` (see `results/e1_granularity.md` and
`results/e2_text_overlap.md`). Wellcome `b31362126` (3-vol English
Spalteholz, 1929/30) compared against IA `b31362138` (same translation,
1933 bound-as-one reprint). Headline numbers cited inline.

#### Why one mode, not two

`ia-utils` ships three modes (`searchtext`, `djvu`, `hocr`) because IA
publishes a cheap pre-built per-page plain-text artifact
(`_hocr_searchtext.txt.gz`, ~5 MB) alongside the full hOCR (~50 MB).
The `searchtext` mode is genuinely lighter — it pulls a smaller file.

Wellcome (and we expect other IIIF providers) **does not** offer that.
The `/text/v1/{bnumber}` rendering is one giant whole-book blob with no
page boundaries (verified `morris_index`). The only way to get per-page
text from Wellcome is via the per-canvas ALTO `seeAlso`. Once we've paid
the ALTO fetch cost (~156 MB for Morris), throwing away the bboxes saves
~10 MB of SQLite and loses every IIIF-only capability in §1 (region URLs,
figure extraction, block-level FTS bboxes).

v1 therefore ships **one mode only** — ALTO with full bboxes —
whenever per-canvas ALTO is available. A `searchtext` mode would be
worth adding only when a future provider offers a genuinely cheap
per-page text source we can use *instead* of fetching ALTO. None of the
providers we target today qualifies.

#### `text_blocks` (ALTO path)

Reuse IA's hOCR `text_blocks` columns (page_id, block_number, bbox,
language, text_direction, avg_confidence, avg_font_size, line_count,
parent_carea_id, block_type, hocr_id). Map ALTO → those columns at the
**`<TextBlock>` granularity** (one row per ALTO TextBlock, with bbox
from HPOS/VPOS/WIDTH/HEIGHT and text reconstructed from child
`<TextLine>`s).

Specific decisions and the evidence:

- **Row granularity = ALTO `<TextBlock>`.** TextBlock-length is bimodal
  in our 30-page sample: 92.5% of blocks are ≤200 chars (figure labels,
  captions, page numbers, headers — exactly where tight bboxes are most
  valuable on atlases); 6.7% are ≥1000 chars and hold 80.8% of the text
  (column-sized prose blocks). Inspection of long blocks confirmed they
  are mostly *honest* prose paragraphs with narrow column-indent HPOS
  variance (~200 px); exploding them into TextLines would shred a
  coherent paragraph into ~50–65 single-line rows for no FTS gain.
  Coarse bboxes on those prose pages are an acceptable v1 trade.
  Row count on the full 3-vol work: ~12k rows (vs. ~55k if TextLine).
- **Known limitation — fused caption+prose TextBlocks.** A minority of
  long blocks (HPOS spread > ~1000 px) actually fuse a figure caption
  and the following paragraph into one TextBlock. Symptom: lines 0–N
  start at indented HPOS; lines N+ start at column HPOS. A future
  refinement can split these by detecting internal HPOS-variance, but
  v1 stores them as one row. Document this in `troubleshooting.md`.
- **`avg_confidence` is NULL for Wellcome ALTO.** Zero `WC` attributes
  on `<String>` elements across all 30 sampled pages. Wellcome's
  ABBYY-derived ALTO does not emit word confidence. IA's hOCR
  `avg_confidence` column is preserved in the schema so cross-archive
  consumers don't break, but for Wellcome-built indexes it will be NULL
  on every row. The presence/absence is itself information; downstream
  tooling can treat NULL as "confidence not reported."
- **`avg_font_size` is also typically NULL.** ALTO's font size lives in
  `<TextStyle FONTSIZE>` and is referenced via `STYLEREFS`, sparsely
  populated in Wellcome ALTO. Same handling as confidence.
- **Coordinate system: pixel.** Confirmed `MeasurementUnit: pixel` on
  the Wellcome sample. Map ALTO `HPOS/VPOS/WIDTH/HEIGHT` → IA
  `bbox_x0/y0/x1/y1` as `(HPOS, VPOS, HPOS+WIDTH, VPOS+HEIGHT)` without
  conversion. The non-pixel `MeasurementUnit` cases (`mm10`,
  `inch1200`) remain a possible hazard for non-Wellcome providers and
  will be handled by a normalizer when we hit them; not blocking v1.
- **Schema unification with IA is empirically supported.** E2 measured
  median Jaccard 0.930 (mean 0.921; 21/27 pages ≥ 0.9; none <0.7)
  between Wellcome ALTO and IA hOCR page text on the same work. Same
  engine (ABBYY), same images, different serialisation. Cross-archive
  FTS will behave consistently.
- **Reading order.** Naive document order of `<TextBlock>` elements is
  the default. Pending E6, this may need `IDNEXT` chains on
  multi-column pages; if so, walk them at parse time and write rows in
  reconstructed order.

#### Companion table: `illustrations` (new)

```sql
CREATE TABLE illustrations (
    page_id INTEGER,
    illustration_number INTEGER,
    bbox_x0 INTEGER, bbox_y0 INTEGER,
    bbox_x1 INTEGER, bbox_y1 INTEGER,
    illustration_type TEXT,    -- 'Illustration' | 'GraphicalElement'
    alto_id TEXT,
    PRIMARY KEY (page_id, illustration_number)
);
```

ALTO emits `<Illustration>` and `<GraphicalElement>` regions alongside
`<TextBlock>`. E1: median 1/page across 30 atlas pages, max 4.
Importantly, several content pages have 0 TextBlocks but 2
Illustrations (pure-plate pages where the figure is the whole content)
— these don't fit in `text_blocks` and would otherwise be invisible to
the index. With `image_service_url` from `page_numbers`, each row
yields a IIIF region URL (`{service}/{HPOS,VPOS,WIDTH,HEIGHT}/...`)
that points at the figure directly. Powers a future `get-figure`
command and "find figures on page N" queries. For non-ALTO sources
(IA hOCR, plain-text) the table will be empty — that's fine.

**v1 design choice: no caption linkage.** ALTO does not link
`<Illustration>` regions to their captions. End-to-end test on Morris
Anatomy 1914 (`experiments/morris_index/find_femur_figure.py`) showed
the "nearest figure caption above the illustration" heuristic
mislabelling figures on a page that stacks Fig. 219 + Fig. 220 — the
heuristic paired Fig. 220's caption with Fig. 219's image. **v1
exposes illustrations as first-class rows without claiming a caption
mapping.** A future `figures` view can join illustrations to caption
text via `Fig. N`-prefix matching in nearby `text_blocks` and a figure
number extracted from the caption, which is more honest than a
position-only heuristic.

**Known limitation: ALTO `<Illustration>` bboxes are sometimes tight.**
Same Morris test: Fig. 215's anterior-femur illustration had leader
lines and label text (`tubercle`, `attached to`, `trochanter`,
`oas`/`psoas`) extending outside the `<Illustration>` bbox — the
unpadded region URL crops them. A `get-figure` command should accept a
padding flag (e.g. `--padding 5%` or a pixel value) that expands the
bbox before constructing the region URL. v1.5 polish.

#### Block-classification cookbook (derivable from v1 schema, no STYLEREFS needed)

Wellcome ALTO does not emit `<TextStyle>` definitions or STYLEREFS
attributes — verified across 60 randomly-sampled Morris pages: 0
TextStyle elements, 0 STYLEREFS on 216 TextBlocks / 1,827 TextLines /
15,269 Strings. So `avg_font_size` and `avg_confidence` will always be
NULL on Wellcome-built indexes. **But the bbox columns we already
store are enough to classify block roles geometrically.**

A per-line-height proxy on Morris Anatomy 1914 yielded these clean
clusters:

| Role | line-h = `(bbox_y1 - bbox_y0) / line_count` |
|---|---:|
| Running header / page number / TOC entry | ~14–15 px |
| Figure caption (`Fig.` prefix) | ~25–26 px |
| **Body text** (baseline / median) | **~32 px** |
| Section heading | ~100 px |
| Title-page header (`HUMAN ANATOMY`) | ~112 px |

Recipe for a downstream "what kind of block is this?" classifier,
all from columns already in `text_blocks` + `page_numbers`:

1. **Line-height proxy** — `(bbox_y1 - bbox_y0) * 1.0 / NULLIF(line_count, 0)`.
   Compute the per-index median over body-text-length blocks
   (`length BETWEEN 50 AND 500`) and use it as the body baseline. Then
   classify by ratio to that baseline (≥1.5× = header, ≤0.7× = small).
2. **Length** — captions and page numbers are short (≤200 chars). Index
   entries are short and dense in numerals.
3. **Page position** — `bbox_y0 < 0.08 × page_height` → top-of-page
   (running header, page number, chapter-opener). `bbox_y0 >
   0.92 × page_height` → bottom-of-page (footnote, page number).
4. **Caption regex** — `text LIKE 'Fig.%'` or `text LIKE 'Plate %'`
   reliably identifies figure captions.
5. **Fused-block detector** — internal `HPOS` variance among child
   `<TextLine>` elements > ~1000 px flags the caption+prose fusion
   pathology noted above. (Not in v1 schema unless we add a
   `text_lines` table; computable at parse time and recordable as a
   `block_type` flag.)

Caveats from the demo:

- **Junk-OCR blocks fake huge line heights.** Single-character
  mis-OCRed glyphs on plate pages can yield blocks with vast bboxes
  and `line_count=1` (e.g. line_h = 1264 px). Filter by minimum text
  length before classifying as a heading.
- **ALTO sometimes lumps figure-label lists into one TextBlock.** A
  vertical column of one-word anatomical labels around a figure
  appears as one tall, wide TextBlock with plausible-looking per-line
  height — not a paragraph, but also not a real heading. Detectable
  via low alphabetic-density / many short lines / proximity to an
  `<Illustration>` row, but a simple regex can't catch it.

This is documentation, not schema. We don't ship a classifier in v1;
consumers can write their own from these signals. A future
`iiif-utils block-class` view or stored procedure would be a v1.5
nicety.

### 3.6 `pages`, `pages_fts`, `text_blocks_fts`

Identical to IA. Built the same way (`sqlite-utils enable_fts`,
group_concat-driven page-level FTS5 table).

### 3.7 New IIIF-only tables

#### `manifest_raw`

```sql
CREATE TABLE manifest_raw (
    fetched_at TEXT,
    etag TEXT,
    body TEXT      -- raw JSON, gzip-compressed if large; or stored verbatim
);
```

Single-row table holding the raw manifest. Lets `rebuild-index` work without
re-fetching, and lets advanced users query things we didn't model.

#### `collection_members` (only when index represents a Collection)

```sql
CREATE TABLE collection_members (
    member_index INTEGER PRIMARY KEY,
    type TEXT,              -- 'Manifest' | 'Collection'
    id TEXT,
    label TEXT,
    nav_date TEXT
);
```

Used when a user runs `iiif-utils create-index` against a Collection URL —
records the children so downstream commands can iterate volumes.

#### `ranges` (manifest structures / table-of-contents)

```sql
CREATE TABLE ranges (
    range_index INTEGER PRIMARY KEY,   -- order within the manifest
    range_id TEXT,                     -- IIIF Range @id / id
    parent_range_id TEXT,              -- nested ranges, NULL for top-level
    depth INTEGER,                     -- 0 for top-level
    label TEXT,                        -- e.g. "Cover", "Chapter 1", "Vol. 2"
    behavior TEXT,                     -- v3 'behavior' / v2 'viewingHint'
    canvas_start INTEGER,              -- first leaf_num covered (inclusive)
    canvas_end INTEGER                 -- last leaf_num covered (inclusive)
);
```

Captures the manifest's `structures` array (v2/v3 IIIF Ranges). This is
how table-of-contents, plate lists, and **within-item volume breaks**
are represented.

**This pattern is not new with IIIF.** Internet Archive items have the
same shape — `ia-utils`'s `multi-volume.md` documents "bound-together
editions" where all volumes of a multi-volume work are scanned into a
single IA item (Spalteholz `b31362138` is 3 volumes in one item, ~976
leaves). On IA the only signal is a high `imagecount` and a hint in
`physicalDescription`; there is no programmatic way to find the volume
boundary, so the IA convention is to treat the bound-together edition as
a single unit. **IIIF actually makes this easier**: Ranges in the
manifest's `structures` array carry the boundaries explicitly. The
motivating IIIF case is Wellcome's Cunningham *Manual* (`kw6vt8gv`),
two physical volumes concatenated into one 752-canvas manifest with the
boundary marked by the second `label: "Cover"` range:
`SELECT canvas_start FROM ranges WHERE label='Cover' ORDER BY range_index`.

`create-index` exposes `--split-on-range <label>`: when set, instead of
producing one index it produces one index per range whose label matches.
For manifests without useful Ranges (or for the IA-style "no
boundaries available" case if/when an IA provider kind is added in §10),
the default behavior is one index for the whole item — same as
`ia-utils` today.

---

## 4. Provider configuration

Providers are first-class. Each provider supplies:

- A **discovery adapter** (search) — converts a generic query into provider
  API calls, returns hits as a normalized record.
- A **manifest resolver** — given a provider identifier (e.g. a Wellcome
  b-number) or URL, return the manifest URL and fetch the manifest.
- An **OCR strategy** — declares, per-canvas or per-manifest, where to find
  text: `content_search`, `rendering_text`, `seealso_alto`,
  `seealso_hocr`, `annotation_list`, or `none`.
- A **rendering strategy** — declares how to find PDF/EPUB/etc.

### Provider kinds

For v1, all providers are kind `iiif` (Wellcome, generic IIIF, future
Bodleian / Gallica / LoC). `index_metadata.provider_kind = "iiif"` is
written into every index so a non-IIIF kind can be added later
(`pdf` for sources like BIU Santé and Google Books, `url_set` for things
like Bartleby's HTML Gray's, `ia` deferring to `ia-utils`) without
breaking schema-aware consumers. See §10 for the deferred non-IIIF
kinds — adding them is purely additive on top of the IIIF v1.

### 4.1 Tooling and project layout

Development standardizes on **`uv`** for environment, dependency, and script
management — no `pip`/`venv`/`poetry`/`pipenv`. The project follows the modern
Python packaging conventions:

- `pyproject.toml` is the single source of truth (PEP 621 metadata, declared
  dependencies, `[project.scripts]` entry points). No `setup.py` or
  `setup.cfg`.
- **`src/` layout** — package lives at `src/iiif_utils/`, never importable from
  the repo root. Catches "works on my machine because cwd" bugs.
- **Hatchling** as the build backend, with `hatch-vcs` for version-from-git
  (mirrors `ia-utils`).
- A console-script entry point: `iiif-utils = "iiif_utils.cli:cli"`.
- Lockfile (`uv.lock`) committed to the repo.
- Dev dependencies declared under `[project.optional-dependencies].dev`
  (`pytest`, `pytest-cov`, `ruff`, `mypy`).
- Tests live in top-level `tests/`, discovered via
  `[tool.pytest.ini_options].testpaths`.
- Lint/format with **`ruff`** (replaces black + flake8 + isort); type-check
  with **`mypy --strict`** on `src/iiif_utils/`.

Common workflows:

```bash
uv sync                     # create/update .venv from pyproject + uv.lock
uv sync --dev               # include dev extras
uv run iiif-utils --help    # invoke the CLI in the project env
uv run pytest               # tests
uv run ruff check .         # lint
uv run mypy src             # type-check
uv add httpx                # add a runtime dep (updates pyproject + lock)
uv add --dev pytest-mock    # add a dev dep
uv lock --upgrade           # refresh the lockfile
uv build                    # build sdist + wheel
```

`pyproject.toml` skeleton (mirrors `ia-utils`'s structure deliberately):

```toml
[build-system]
requires = ["hatchling", "hatch-vcs"]
build-backend = "hatchling.build"

[project]
name = "iiif-utils"
dynamic = ["version"]
description = "CLI tool to work with IIIF digitized collections"
readme = "README.md"
license = { text = "MIT" }
requires-python = ">=3.10"
dependencies = [
    "click>=8.1",
    "httpx[http2]>=0.27",
    "sqlite-utils>=3.35",
    "lxml>=4.9",          # ALTO/hOCR parsing
    "pillow>=10.0",
    "pytesseract>=0.3.10",
    "tomli>=2.0; python_version<'3.11'",
]

[project.optional-dependencies]
dev = ["pytest>=8", "pytest-cov>=5", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
iiif-utils = "iiif_utils.cli:cli"

[tool.uv]
managed = true

[tool.hatch.version]
source = "vcs"
fallback-version = "0.0.0"

[tool.hatch.build.hooks.vcs]
version-file = "src/iiif_utils/_version.py"

[tool.hatch.build.targets.wheel]
packages = ["src/iiif_utils"]

[tool.pytest.ini_options]
testpaths = ["tests"]
python_files = ["test_*.py"]

[tool.ruff]
line-length = 100
target-version = "py310"

[tool.mypy]
python_version = "3.10"
strict = true
files = ["src/iiif_utils"]
```

### 4.2 Source layout

```
src/iiif_utils/
    cli.py
    config/
        __init__.py          # loader: packaged defaults <- ./iiif-utils.toml <- --config
        config.toml          # shipped defaults (committed to source)
    core/
        manifest.py          # IIIF v2/v3 normalizer
        image_api.py         # URL builders, info.json fetch
        database.py          # schema + writers (mirror of ia_utils.core.database)
        ocr/
            alto.py
            hocr.py
            content_search.py
            text_rendering.py
        http.py              # httpx client w/ retries, conditional GET, gzip
    providers/
        __init__.py          # registry
        base.py              # Provider ABC
        wellcome.py
        generic.py           # works with any IIIF manifest URL, no discovery
    commands/                # one file per CLI subcommand (mirror of ia_utils)
        create_index.py
        info.py
        list_files.py
        get_page.py
        get_pages.py
        get_pdf.py
        get_text.py
        get_url.py
        ocr_page.py
        rebuild_index.py
        search_iiif.py       # equivalent of search_ia
        search_index.py
    utils/
        slug.py
        output.py
        logger.py
        types.py
```

### 4.3 Configuration file

Config lives **inside the project tree**, not in user-home dotfile
directories. The default location is `src/iiif_utils/config/config.toml`
(packaged with the source so the tool ships with sensible defaults). A
project-local `./iiif-utils.toml` at the repo root overrides the packaged
defaults when present, and `--config <path>` overrides everything for a
single invocation.

We deliberately avoid `~/.config/iiif-utils/`, `~/.iiif-utils.toml`, and
similar XDG/dotfile locations for now — keeping config in the source makes
the tool self-contained, version-controlled, easy to inspect, and avoids
hidden global state across machines. We can revisit a per-user config
location later if real usage demands it.

```toml
# src/iiif_utils/config/config.toml  (defaults, shipped with the package)
# or  ./iiif-utils.toml             (project-local override)

default_provider = "wellcome"

[providers.wellcome]
type = "wellcome"                # selects the wellcome.py adapter
catalogue_api = "https://api.wellcomecollection.org/catalogue/v2"
iiif_base     = "https://iiif.wellcomecollection.org"
# Wellcome exposes Content Search v2 on most manifests; tool will fall back
# to ALTO via seeAlso when not present.
ocr_preference = ["content_search", "alto", "rendering_text"]

[providers.bodleian]
type = "iiif_generic"
discovery_url = "https://digital.bodleian.ox.ac.uk/api/v1/search"
ocr_preference = ["alto", "hocr", "rendering_text"]

[providers.gallica]
type = "gallica"                  # custom adapter (SRU + IIIF)
sru_endpoint = "https://gallica.bnf.fr/SRU"
iiif_base    = "https://gallica.bnf.fr/iiif"

# Lowest common denominator: any IIIF manifest URL on the open web.
[providers.generic]
type = "iiif_generic"
ocr_preference = ["content_search", "alto", "hocr", "rendering_text"]

[http]
user_agent = "iiif-utils/0.1 (+https://github.com/.../iiif-utils)"
timeout_seconds = 60
max_concurrency = 4
cache_dir = "./.iiif-cache"        # relative to project root, not ~/.cache

[output]
default_format = "table"
```

### 4.4 Provider interface (Python)

```python
class Provider(Protocol):
    key: str                              # e.g. "wellcome"

    def search(self, q: str, **filters) -> Iterable[SearchHit]: ...
    def resolve(self, ref: str) -> ManifestRef: ...     # accepts ID, URL, or alias
    def ocr_sources(self, manifest: Manifest) -> list[OcrSource]: ...
    def renderings(self, manifest: Manifest) -> list[Rendering]: ...
    def slug(self, manifest: Manifest, hit: SearchHit | None) -> str: ...
```

`generic` provider implements everything except `search` (raises
`NotSupported`) so any IIIF URL on the open web can still be indexed.

### 4.5 Identifier resolution rules

A user-provided "ref" is resolved in this order:

1. Looks like an HTTP(S) URL → if it ends in/contains `manifest`, treat as
   manifest URL directly. Otherwise pass to the provider whose `iiif_base`
   matches the host; if no match, fall back to `generic`.
2. Looks like a known provider identifier pattern (e.g. Wellcome b-number
   regex `^b\d{7}[\dx]$` — 9 chars total: `b` + 7 digits + 1 trailing
   digit-or-`x` check char) → use that provider's `resolve()`.
   Note that Wellcome additionally has a separate **catalogue work ID**
   space (e.g. `r32p4n5s`) used at `wellcomecollection.org/works/{workId}`
   but **never** in IIIF URLs; see §6.
3. Otherwise require `--provider` explicitly.

---

## 5. CLI sketch

Command names mirror `ia-utils` so muscle memory and existing skill files
transfer. Provider selection is via `--provider/-P`, defaulting to
`default_provider` from config.

```
iiif-utils search-iiif    # discovery (analog of ia-utils search-ia)
iiif-utils info
iiif-utils list-files
iiif-utils create-index
iiif-utils rebuild-index
iiif-utils search-index
iiif-utils get-page
iiif-utils get-pages
iiif-utils get-pdf
iiif-utils get-text
iiif-utils get-url
iiif-utils get-figure     # NEW (IIIF-only): pull an illustration by (page, n)
iiif-utils get-region     # NEW (IIIF-only): pull an arbitrary (x,y,w,h) crop
iiif-utils list-figures   # NEW (IIIF-only): list illustrations + region URLs
iiif-utils ocr-page       # local pytesseract on a downloaded canvas
iiif-utils providers      # list/inspect configured providers
```

### Examples

```bash
# Search Wellcome
iiif-utils search-iiif -q "anatomy atlas" --year 1800-1900 --has-ocr

# Index a Wellcome work by b-number
iiif-utils create-index b31362138 -d ./indexes/

# Index any IIIF manifest URL (uses 'generic' provider)
iiif-utils create-index https://digital.bodleian.ox.ac.uk/iiif/manifest/...

# Switch provider explicitly
iiif-utils -P gallica search-iiif -q "anatomie" --year -1900

# Image API niceties (only useful in IIIF land)
iiif-utils get-page -i index.sqlite -l 42 --size 'full' --format jpg
iiif-utils get-page -i index.sqlite -l 42 --region '500,500,2000,2000' \
                                          --size '!1024,1024'

# IIIF-only: list and extract figures
iiif-utils list-figures -i morris.sqlite -l 198      # all figures on canvas 198
iiif-utils list-figures -i morris.sqlite --all       # whole work
iiif-utils get-figure   -i morris.sqlite -l 198 -n 0 -o femur.jpg
iiif-utils get-figure   -i morris.sqlite -l 198 -n 0 --padding 5%
iiif-utils get-region   -i morris.sqlite -l 198 --bbox '454,306,1148,2676' \
                                                -o femur.jpg

# Get-url versions (just emit the URL, no download)
iiif-utils get-url -i morris.sqlite -l 198 -n 0 --figure
iiif-utils get-url -i morris.sqlite -l 198 --bbox '454,306,1148,2676' --region
```

`get-page` accepts IIIF Image API parameters when present
(`--region`, `--size`, `--rotation`, `--quality`, `--format`); otherwise
keeps the IA-style `--size {small,medium,large,original}` aliases that map
internally to canonical IIIF size strings.

### `get-url` modes

`get-url` produces:
- `--image` (default): direct image URL (built from `image_service_url`)
- `--info`: the `info.json` URL
- `--manifest`: the manifest URL
- `--viewer`: a known viewer URL when the provider configures one
  (e.g. `https://wellcomecollection.org/works/{workId}`,
  Mirador embed, Universal Viewer)
- `--pdf`: rendering PDF URL (if available)
- `--figure` (with `-n <illustration_number>`): IIIF region URL for
  one illustration (from the `illustrations` table). IIIF-only.
- `--region` (with `--bbox 'x,y,w,h'`): IIIF region URL for an
  arbitrary rectangle on the canvas. IIIF-only.

### Multi-volume / collections

`create-index` handles three multi-volume patterns:

1. **IIIF Collection URL.** Default: write a top-level collection index
   whose `collection_members` table lists all child manifest URLs, without
   indexing children. With `--recursive`, also create per-manifest indexes
   named by slug.
2. **Sibling Works on the same provider** (Wellcome's pattern, since they
   don't use Collections — see §6). The corpus driver below is the natural
   way to express this; manually, you list the b-numbers and run
   `create-index` on each.
3. **Within-item concatenation** — multiple physical volumes spliced
   into a single manifest's canvas sequence (or, on IA, a single item).
   On IIIF the breaks are usually marked by Ranges in the manifest's
   `structures` array — Wellcome's Cunningham *Manual* (`kw6vt8gv`) is the
   reference case. On IA there is typically no programmatic boundary
   (Spalteholz `b31362138` = 3 volumes in one item, ~976 leaves), and
   `ia-utils` accordingly treats bound-together editions as a single
   unit. With `--split-on-range <label>` (e.g. `--split-on-range Cover`),
   `create-index` produces one index per matching range instead of one
   combined index. Default writes a single combined index plus the
   `ranges` table so the breaks are queryable. Without usable Ranges,
   the default-and-only behavior is one combined index — matching IA's
   long-standing convention.

### Manifest health checks

`create-index` validates the manifest before writing and refuses (or
warns) on three patterns surfaced repeatedly in `CORPUS.md`:

- **Zero-canvas / bibliographic-only.** Manifest fetched OK but has no
  canvases. Default: error out with
  `"manifest has 0 canvases — bibliographic record only?"`. With
  `--allow-empty`, write a metadata-only index.
- **Partial digitization.** Heuristic flags: `physicalDescription` says
  "volumes" (plural) but only one Range covers everything, or
  `label`/`title` contains "Section N" / "Part N" / "Vol. N only" /
  "fragment". Always written, but `index_metadata.partial_digitization`
  is set with the reason.
- **Within-manifest concatenation.** Detected when `structures` contains
  multiple top-level Ranges with `behavior: top` or repeated structural
  labels (e.g. two `"Cover"` ranges). Always written; sets
  `index_metadata.contains_multiple_volumes = "true"` so downstream
  tooling knows to consult the `ranges` table.

### 5.2 Batch ingest — deferred

A curated reading list (see `CORPUS.md`) is the eventual unit of work,
but a corpus driver / `corpus.toml` format / `iiif-utils corpus-run`
command is **out of scope for v1**. Single-document `create-index` must
work cleanly first; batch can be a thin wrapper layered on top later.
Tracked in §10.

---

## 6. Discovery: Wellcome specifics

All facts in this section verified against the live API on 2026-05-10.
See [`WELLCOME_NOTES.md`](WELLCOME_NOTES.md) for citations and worked
examples.

### Two identifier spaces

Wellcome maintains **two distinct identifier spaces** that the adapter
must carry side-by-side:

- **Catalogue work ID** — opaque slug like `r32p4n5s`. Drives
  `wellcomecollection.org/works/{workId}` and the catalogue API at
  `api.wellcomecollection.org/catalogue/v2/works/{workId}`. Never appears
  in a IIIF URL.
- **Sierra b-number** — `b22396147` (9 chars: `b` + 7 digits + 1 trailing
  digit-or-`x`). Drives every IIIF URL: manifest, image asset, ALTO,
  PDF, search, plain text.

The b-number is found in `work.identifiers[]` where
`identifierType.id == "sierra-system-number"`. The adapter resolves a
catalogue work to a b-number first, then constructs IIIF URLs from there.

### Catalogue API (search)

- Base: `https://api.wellcomecollection.org/catalogue/v2/works`
- No API key, no documented rate limit, CORS open. User-Agent is good
  hygiene but not required.
- Pagination: `page` (≥1), `pageSize` (1–100, default 10). Results carry
  a `nextPage` URL when more exist.
- Sort: only `sort=production.dates` with `sortOrder=asc|desc`. Default
  is relevance for `query`.
- `include=identifiers,items,subjects,contributors,production,...` to get
  the b-number and the IIIF location.

Filters of interest (verified live):

| Filter | Notes |
|---|---|
| `query` | Full-text query string |
| `workType` | Single-letter format codes (`a` books, `d` journals, `h` archives, ...) |
| `languages` | ISO codes, comma-separated |
| `subjects.label`, `genres.label`, `contributors.agent.label` | Faceted text filters |
| `production.dates.from` / `production.dates.to` | Year strings |
| `availabilities` | `online`, `open-shelves`, `closed-stores` |
| `items.locations.accessConditions.status` | `open`, `restricted`, `safeguarded`, `licensed-resources`, `permission-required` — this is the openness axis |
| `items.locations.locationType` | Use `iiif-presentation` to restrict to digitised items |
| `items.locations.license` | `pdm`, `cc-by`, `cc-by-nc`, `inc`, ... |
| `partOf` / `partOf.title` | Series / parent linkage |
| `identifiers` | Look up by Sierra/CALM/etc. ID |

### Manifest URL pattern

```
https://iiif.wellcomecollection.org/presentation/{bnumber}        # v3 (default)
https://iiif.wellcomecollection.org/presentation/v2/{bnumber}     # v2
```

The catalogue API's `items[].locations[].url` field returns the **v2**
form. Rewrite the path segment to get v3.

### Multi-volume modeling

On Wellcome, multi-volume works are **sibling catalogue Works**, not
IIIF Collections. They are linked via `partOf` series entries in the
catalogue API; each volume is its own Work with its own b-number and its
own manifest. The adapter enumerates volumes via the catalogue, not by
walking a Collection manifest.

A `/presentation/collections/...` endpoint exists but is intentionally
throttled (`HTTP 503 "Dynamic collections are disabled because of too
many requests"`) and must not be part of any discovery path.

### Content Search

**Content Search v1**, not v2. Every sampled manifest carries:

```json
"service": [{
  "@id":     "https://iiif.wellcomecollection.org/search/v1/{bnumber}",
  "@type":   "SearchService1",
  "profile": "http://iiif.io/api/search/1/search",
  "service": {
    "@id":     "https://iiif.wellcomecollection.org/search/autocomplete/v1/{bnumber}",
    "@type":   "AutoCompleteService1",
    "profile": "http://iiif.io/api/search/1/autocomplete"
  }
}]
```

Hit responses are `sc:AnnotationList` with each hit's `on` URI carrying
both the canvas ID and the matched bbox in `#xywh=`. That is enough to
map a hit back to a `page_numbers` row plus an `image_service_url`
region.

### OCR fallback chain (Wellcome)

In priority order, all offline unless noted:

1. **Per-canvas ALTO via `seeAlso`** — best for word-level bboxes.
   Match on `format == "text/xml"` AND `profile` substring `alto`. URL:
   `https://api.wellcomecollection.org/text/alto/{bnumber}/{bnumber}_NNNN.jp2`
   (the trailing `.jp2` is part of the asset name, not a JPEG2000 file).
   Caveat: the advertised profile is ALTO v3 but the served XML is
   **ALTO v2** (`xmlns="...alto/ns-v2#"`). Parser must accept either
   namespace.
2. **Per-canvas W3C AnnotationPage** at
   `https://iiif.wellcomecollection.org/annotations/v3/{bnumber}/{asset}/line`
   — same OCR data in JSON form, useful if XML parsing is undesirable.
3. **Manifest-level plain-text rendering** at
   `https://api.wellcomecollection.org/text/v1/{bnumber}` (and
   `.zip` variant containing the same single file). Works on restricted
   items too. **Important limitation, verified on Morris Anatomy 1914
   in `experiments/morris_index/`**: this rendering is a single
   concatenated string for the whole work — **no per-page boundaries,
   no form-feeds, no canvas markers** — unlike IA's
   `_hocr_searchtext.txt.gz` which is page-delimited. Useful for
   whole-work grep but **cannot populate per-canvas `text_blocks` rows**.
   For our `searchtext` mode on Wellcome, derive per-page text by
   reconstructing line text from each per-canvas ALTO (`<String
   CONTENT>` joins, bboxes dropped) — same source files as ALTO mode,
   lighter schema, real per-page boundaries.
4. **Live Content Search v1** — last-resort, online-only.

### Renderings (PDF, plain text)

Manifest-level `rendering` typically includes:

```json
[
  {"id": "https://iiif.wellcomecollection.org/pdf/{bnumber}",
   "type": "Text", "format": "application/pdf"},
  {"id": "https://api.wellcomecollection.org/text/v1/{bnumber}",
   "type": "Text", "format": "text/plain"}
]
```

PDF is usually but not always present (restricted items often have only
the plain-text rendering). No METS, EPUB, or full-work XML renderings
seen at the manifest level.

### Image API — version and auth

- **Image API v2** (`ImageService2`,
  `http://iiif.io/api/image/2/context.json`). Despite the developer
  portal's "IIIF APIs (v3)" branding, only the *Presentation* API is v3.
  §8 size-keyword translation must default to v2 for Wellcome.
- URL pattern:
  `https://iiif.wellcomecollection.org/image/{asset}/{region}/{size}/{rotation}/{quality}.{format}`
- `{asset}` is `{bnumber}_NNNN.jp2` for paged content, or a Miro ID
  (e.g. `M0004078`) for legacy single-image items.
- Level 2 compliance, formats `[jpg, tif, gif, png]` (no `webp` in the
  supports list of sampled assets), tile size 512×512.

**Auth (restricted material).** Restricted assets advertise IIIF Auth in
the **manifest's** image-service block — *not* in `info.json`:

```json
"service": [
  {"@id":  "https://iiif.wellcomecollection.org/auth/restrictedlogin",
   "@type":"AuthCookieService1"},
  {"id":   "https://iiif.wellcomecollection.org/auth/v2/probe/{asset}",
   "type": "AuthProbeService2",
   "service": [{"id": ".../auth/v2/access/restrictedlogin",
                "type": "AuthAccessService2"}]}
]
```

Both v1 (`AuthCookieService1`) and v2 (`AuthProbeService2` /
`AuthAccessService2`) are advertised together. Unauthenticated image
fetch returns bare `HTTP 401` (no body, no `WWW-Authenticate`). The
asset's own `info.json` carries the `auth/2` `@context` but **omits**
the actual service block, so auth discovery must walk the manifest.

**Important**: restricted manifests still serve plain-text rendering and
Content Search v1 successfully. The adapter should still build a
text-only index for them and only skip image downloads. Access status
values to expect on `items[].locations[].accessConditions[].status.id`:
`open`, `restricted`, `safeguarded`, `licensed-resources`,
`permission-required`. Treat anything ≠ `open` as "skip image download,
keep text indexing."

### Reference fixtures

Three concrete works to use as test fixtures (full details in
`WELLCOME_NOTES.md` §8):

- **Open single-volume book** — work `r32p4n5s` / b-number `b22396147`
  (24 canvases, ALTO + PDF + Content Search all present).
- **Multi-volume sibling Works** — "The complete works of John Hunter"
  in 4 volumes (`b21131569`, `b21131570`, `b21131582`, `b21131594`),
  exercising the catalogue-driven enumeration path.
- **Restricted clinical material** — work `a22mnm7y` /
  b-number `b32858899` (manifest fetches, search and plain text work,
  image fetch returns 401), exercising the auth-detection and
  text-only-index paths.

### Generic provider OCR detection

For arbitrary IIIF manifests (non-Wellcome), the generic provider walks
the manifest in this order and uses whichever it finds first
(configurable via `ocr_preference`):

1. Canvas-level `seeAlso` with ALTO/hOCR/plain-text profiles.
2. Manifest-level `rendering` of type `text/plain`.
3. Manifest-level `service` of type `SearchService1`/`SearchService2`
   (live, online-only fallback).
4. Otherwise, mark `index_mode = none` and skip text indexing — the
   index still has canvas/image data and is useful for image retrieval.

---

## 7. Identifiers, slugs, filenames

`ia-utils` slugs index files using metadata (title, creator, date, IA
identifier). We preserve this behavior:

```
{provider-key}_{slug-of-title}_{year}_{identifier}.sqlite
```

e.g. `wellcome_hand-atlas-of-human-anatomy_1923_b31362138.sqlite`.

Including the provider key prevents collisions across providers and makes a
mixed-provider directory navigable.

---

## 8. Image API mechanics

Two important details specific to IIIF that have no IA analog:

- **info.json caching.** Before building image URLs we ideally fetch the
  canvas's `info.json` once to learn its tile sizes, max width, supported
  formats, and Image API compliance level. We cache `info.json` under
  `cache_dir`. The `image_service_url` we store *is* the base; appending
  `/info.json` gives the descriptor URL.
- **Size keywords.** IIIF v2 used `full` and `pct:`; v3 uses `max` and
  `^max`/`^pct:` for upscale-allowed forms. We expose canonical IIIF strings
  via `--size` and translate IA-style aliases (`small`, `medium`, `large`,
  `original`) into the version-correct form using `image_api_version` from
  `page_numbers`.

---

## 9. Compatibility with existing IA tooling

Because `document_metadata`, `index_metadata`, `text_blocks`, `pages_fts`,
`text_blocks_fts`, `archive_files`, and `page_numbers` retain the IA shapes
(with strictly additive columns on `page_numbers`), most IA-era queries work
unchanged:

- `SELECT value FROM document_metadata WHERE key='title'` ✓
- FTS over `pages_fts` and `text_blocks_fts` ✓
- Joins from `pages_fts` to `page_numbers` on `page_id = leaf_num` ✓
- PDF discovery via `archive_files` ✓ (rows now come from manifest renderings)

Differences to flag in the schema doc:

- `confidence` / `pageProb` / `wordConf` are typically NULL for IIIF.
- `archive_files.size_bytes` and checksums are usually NULL.
- `pdf_page = leaf_num + 1` no longer holds: IIIF PDFs come from a separate
  rendering and may be paginated independently.

---

## 10. Open questions / things to revisit

1. **Should we keep one tool (`iiif-utils`) or build a thin `archive-utils`
   meta-tool that dispatches to `ia-utils` and `iiif-utils`?** Single tool is
   simpler but blurs the IIIF contract.
2. **Content Search live mode.** Should `search-index` optionally fall through
   to a live Content Search query for items where we couldn't localize OCR? It
   would be slower but bridges manifests we can't fully index.
3. **Annotation lists.** Some providers expose human-curated annotations
   (commentary, transcriptions) via `seeAlso`. Worth a separate
   `annotations` table?
4. **Auth.** Some IIIF endpoints (especially Bodleian, BL, NLS) require IIIF
   Auth API tokens for high-resolution or restricted images. Out of scope for
   v1; document the failure mode.
5. **Change Discovery.** Wellcome and a few others publish IIIF Change
   Discovery activity streams. Could power an `update` command that refreshes
   indexes incrementally — likely v2.
6. **Caching.** `ia-utils` re-downloads source files on rebuild; we should
   honor HTTP caching headers (`ETag`, `Last-Modified`) and store
   `manifest_raw.etag` so rebuilds are cheap.
7. **Skill file.** Once shape is settled, port `ia-utils/SKILL.md` to a
   sibling `iiif-utils/SKILL.md` so an LLM can drive both tools with shared
   conventions.
8. **Batch / corpus driver.** A `iiif-utils corpus-run --from corpus.toml`
   wrapper that ingests a curated reading list (see `CORPUS.md`) in one
   pass, with per-work `rights_override`, `tier`, `split_on_range`,
   `volume_labels`, etc. Deferred until single-document `create-index` is
   solid; should be a thin layer that reuses the v1 primitives.
9. **Non-IIIF provider kinds.** `pdf` (BIU Santé, Google Books) and
   `url_set` (Bartleby Gray's) source kinds, writing the same SQLite shape
   minus IIIF-only fields. Deferred — implement only after the IIIF
   `create-index` path is stable enough that the additional kinds are
   purely additive.
10. **ALTO ↔ IA-OCR empirical study.** Status: mostly resolved. See
    `experiments/alto_vs_ia/` and §3.5 above. Remaining open items:
    - **E6 (reading order).** Do multi-column ALTO pages need `IDNEXT`
      chains followed, or is document order enough? Not yet measured.
      Likely cheap to handle either way; investigate when first
      multi-column work surfaces.
    - **Non-Wellcome ALTO providers.** All measurements so far are
      Wellcome (ABBYY → ALTO v2 served as v3-profile). Other providers
      may emit ALTO with: non-pixel `MeasurementUnit`, populated `WC`
      and `FONTSIZE`, or different fused-block patterns. Re-run the
      study when adding the next ALTO-serving provider.
    - **Fused caption+prose splitting heuristic.** Documented v1.5
      refinement (§3.5). Worth measuring how common it is on a
      prose-heavy textbook (not an atlas) before committing.

---

## 11. Initial milestones

Strict scope rule: **single-document create-index must work cleanly
before anything multi-document is built.** No batch driver, no
sibling-Works enumeration, no non-IIIF provider kinds in v1.

1. **M1 — Generic provider, single manifest.** `create-index
   <manifest_url>` produces a SQLite that mirrors `ia-utils` schema for
   any open IIIF v2/v3 manifest. M1 ships these commands:
   - `info`, `list-files` (read manifest / show index metadata)
   - `create-index` (the workhorse — ALTO mode by default)
   - `search-index` (FTS over `pages_fts` and `text_blocks_fts`)
   - `get-page`, `get-url` (whole-canvas image + URL)
   - **`get-figure`, `get-region`, `list-figures`** (IIIF-only,
     §1 capability 1+2 — leverage `illustrations` and the Image API
     to produce region URLs and crops on demand)

   Manifest health checks (zero-canvas refusal, partial-digitization
   flag, multi-volume-concat flag, `ranges` table population) are part
   of M1 because they protect every later milestone from bad data.
   Text indexing in M1 is the **ALTO path** (`text_blocks` +
   `illustrations`) per the §3.5 mapping.

   **M1 status: shipped.** `src/iiif_utils/` package exists. The
   following commands are wired and validated end-to-end against
   Morris Anatomy 1914 (1564 canvases, 10,691 TextBlocks, 1,278
   illustrations, 20.7 MB SQLite, matches the reference output of
   `experiments/morris_index/`):

   - `info` — show manifest or index metadata
   - `list-files` — list manifest renderings
   - `create-index` — fetch manifest + ALTO, write SQLite (with
     `--allow-empty`, health-check flags, `archive_files` PK
     disambiguation)
   - `search-index` — page-level and block-level FTS5
   - `get-page` — whole-canvas image
   - `get-figure` — IIIF-only: one illustration by `(leaf, n)` with
     optional padding
   - `get-region` — IIIF-only: arbitrary `(x, y, w, h)` bbox
   - `get-url` — unified URL emitter (--manifest, --image, --info,
     --figure, --region, --pdf)
   - `list-figures` — IIIF-only: per-canvas illustration list with
     region URLs

   The schema decisions are grounded in `experiments/alto_vs_ia/`
   (Spalteholz) and `experiments/morris_index/`. Tooling: uv +
   hatchling + ruff + mypy --strict + pytest, all green.

   **M1 gaps deferred:**
   - `--split-on-range` for the Cunningham-Manual within-manifest
     concatenation case (detection ships in M1; the per-range split
     deferred to M1b).
   - Fixture-based tests for `create-index` (currently only smoke
     tests; full-pipeline tests need cached fixtures so they're
     offline).

   **`searchtext` mode dropped from v1.** See §3.5 "Why one mode, not
   two." For IIIF providers (unlike IA), per-canvas ALTO is the only
   source of per-page text — once we've paid the fetch, keeping the
   bboxes is free in network terms and unlocks the IIIF-only capabilities
   in §1.

   **Open design question (not blocking M1):** one-SQLite-per-work
   (current) vs. a `library merge` rollup that combines many per-work
   files into a single corpus-wide DB for cross-book FTS. Discussed
   2026-05-11; deferred — the per-work primitive must be solid first.

1a. **M1a — `searchtext` mode (lean fallback).** Add `--mode
   searchtext` that drops bboxes and reconstructs per-page text from
   ALTO `<String CONTENT>` joins. Same source files as M1, lighter
   schema. **Do not use Wellcome's manifest-level `/text/v1/{bnumber}`
   rendering for this** — it has no per-page boundaries (verified in
   `morris_index`).
2. **M2 — Wellcome adapter (single document).** `iiif-utils info b22396147`
   resolves a Wellcome b-number to its manifest and produces a working
   index. Content Search v1 + ALTO + plain-text OCR fallback chain
   (per §6). Restricted-item path (text-only index, image fetch returns
   401) handled. Within-manifest concatenation handled via the `ranges`
   table and `--split-on-range`. **Sibling-Works multi-volume
   enumeration is explicitly NOT in M2** — the user is expected to run
   `create-index` once per b-number for now.
3. **M3 — Image-API and download polish.** `--region`, `--size`,
   `--rotation` on `get-page`; info.json caching; PDF rendering; parallel
   `get-pages`; ZIP packaging.
4. **M4 — Catalogue search.** `search-iiif` against Wellcome Catalogue
   API. Returns a list of works with b-numbers; user picks one and runs
   `create-index`. No sibling-Works auto-enumeration yet.
5. **M5 — Second IIIF adapter (Bodleian or Gallica).** Validates the
   provider abstraction. Still single-document.

Anything past M5 (corpus driver, non-IIIF kinds, sibling enumeration,
Change Discovery) lives in §10 until M1–M5 prove stable.
