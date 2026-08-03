---
name: digitized-books
description: Use when working with scanned books held by the Internet Archive (archive.org) or a IIIF library — Wellcome Collection, Library of Congress, Gallica (BnF), Munich's MDZ / Bayerische Staatsbibliothek, or Heidelberg. Use to find an edition, search the text inside a specific scanned book, read what a given page says, pull page images or the PDF, crop a figure or plate, or reconstruct multi-column and tabular pages that OCR scrambled. Trigger on archive.org links and identifiers, IIIF manifest URLs, Wellcome b-numbers, LCCNs, and on requests like "what does this atlas say about the femur", "get me page 212", "find where this book discusses X", or "pull that plate as an image" — even when the user never says IIIF, OCR, or names a library. Not for PDFs or images the user already has locally, and not for born-digital publications.
license: Apache-2.0
compatibility: Requires uv and Python 3.10+, plus network access to archive.org and the IIIF host. The ocr-page command additionally needs tesseract installed in the OS.
metadata:
  author: mhalle
  repository: https://github.com/mhalle/digitized-books
  download: https://github.com/mhalle/digitized-books/releases/latest/download/digitized-books.skill
---

# digitized-books: Internet Archive and IIIF libraries, one tool

One CLI over two worlds that used to need separate tools. Internet
Archive is a **full provider** here, not a viewer bolted on: `archive.org`
items get real full-text indexes, page images, figure crops and outlines,
exactly like Wellcome or LoC items, and every index shares one schema so
a mixed shelf can be queried uniformly.

If a task mentions archive.org, an IA identifier, a IIIF manifest URL, a
Wellcome b-number, or "this scanned book", this is the tool.

## Running it

Always go through the launcher:

```bash
$SKILL_DIR/scripts/iiif-utils <command> [options]
```

Substitute the real skill path for `$SKILL_DIR` — no shell variable is
set for you. If the executable bit was lost in packaging, `sh
$SKILL_DIR/scripts/iiif-utils ...` works identically.

An installed skill is self-contained: `SKILL.md`, the launcher, and a
wheel holding the code. Nothing is installed into the user's home as a
persistent tool, and nothing is written into the skill directory, so it
works mounted read-only. Warm invocations cost ~0.5s; the first use in a
session resolves dependencies once.

The same launcher works in a checkout of the source repository, where it
runs from source instead so edits take effect immediately.

Do **not** hand-roll the underlying command, and do not use
`uv tool install`, `uvx`, `pip install`, or `uv run --project
<skill-dir>`. The last fails outright on a read-only skill directory —
uv writes `.venv` into the project, and hatch-vcs's build hook writes
`_version.py` back into the source tree.

In a checkout, `wheels/` is empty and the launcher runs from source —
that is expected, and it means edits take effect immediately. Wheels
are built by the release workflow, not committed (their version string
embeds a git hash, so they would churn history). To build one anyway:

```bash
sh $SKILL_DIR/scripts/build-wheel.sh
```

To force a specific checkout from anywhere:

```bash
IIIF_UTILS_REPO=/path/to/checkout $SKILL_DIR/scripts/iiif-utils <command>
```

Permissions note: the launcher does not start with `uv run`, so an
allowlist entry matching `uv run *` will not cover it. Allow
`Bash(*/digitized-books/scripts/iiif-utils *)` (or the absolute path) if
invocations prompt.

**Examples below write `iiif-utils` for brevity — always run it through
the launcher path above.**

## Addressing a page: leaf vs printed page

This trips people up constantly, so get it right first.

- **`-l/--leaf N`** — the 0-based scan sequence index. Always an
  integer. Also called the *canvas* in IIIF vocabulary; the same number.
- **`-b/--book LABEL`** — the number **printed on the page**. This is
  TEXT, not an integer: `xii`, `12a`, `209`. Ranges like `100-150`
  expand; anything non-numeric is matched literally.

They differ by the front matter offset — in Gray's *Anatomy* (1918),
leaf 24 is printed page 20.

A printed page number is **not unique** (plates repeat numbers, bound
volumes restart at 1, OCR misreads). When several leaves claim one
printed page the tool refuses and lists the candidates rather than
guessing; disambiguate with `-l`.

Records carry both `leaf` and `canvas` keys with the same value, so
output from different commands joins cleanly.

## Typical workflow

```bash
# 1. Find something (-P ia | wellcome | loc)
iiif-utils search-catalog -P ia -q "anatomy" --creator "Gray, Henry" --has-iiif

# 2. Build an index — accepts an archive.org URL, IIIF manifest URL,
#    Wellcome b-number, BSB id, LCCN...
iiif-utils create-index https://archive.org/details/anatomyofhumanbo1918gray

# 3. Search inside it
iiif-utils search-index -i ia_anatomyofhumanbo1918gray.sqlite -q "lymphatic vessels"

# 4. Read or crop what you found
iiif-utils get-text  -i INDEX -b 687
iiif-utils get-page  -i INDEX -b 687 -o page687.jpg --autocontrast
iiif-utils get-figure -i INDEX -l 198 -n 0 -o figure.jpg
```

Indexes are named `{provider}_{identifier}.sqlite` — deliberately not
title-derived, since titles vary between editions and get corrected.

## Commands

**Discovery** — `search-catalog` (alias `search-cat`) `-P ia|wellcome|loc`;
IA adds `--collection`. `info`, `list-files`.

**Indexing** — `create-index` (add `--layout raw|columns|table`,
`--no-ocr` for plate atlases). `rebuild-index` refreshes FTS;
`rebuild-index --refetch` re-parses the OCR source in place, adding word
geometry and refreshing page numbers **while preserving `derived_outline`**
— use this to upgrade an existing index rather than rebuilding it, which
would discard the outline. `migrate-index` converts an old ia-utils
SQLite (writes a new file; never touches the source).

**Reading** — `search-index -q` (FTS5; `--blocks` for bboxes),
`get-text` (whole-work rendering, or `-l`/`-b` for per-page OCR with
`--blocks`), `get-page-stats` (per-page counts; `--figures` finds plate
pages), `render-page` (reading order — see below), `outline-list`,
`outline-status`.

**Images** — `get-page`, `get-pages` (`--zip`, `--mosaic`, `--sample`,
`--all`), `get-region` (arbitrary bbox), `get-figure` / `list-figures`
(illustrations, where the OCR source marks them), `get-pdf`, `get-url`,
`get-info`, `ocr-page` (local Tesseract).

Image commands accept `--autocontrast` / `--cutoff` / `--preserve-tone`
/ `--quality`. Flat grey letterpress scans are often unreadable until
you autocontrast them.

## Reading order: `render-page`

OCR reading order is a lossy *rendering*, not data. Indexes store
per-word geometry so the order can be re-derived:

- `raw` — OCR order, verbatim. The default, and **the only quotable
  mode**.
- `columns` — unbraids multi-column prose that OCR interleaved.
- `table` — reassembles tabular matter OCR split into vertical stacks.

```bash
iiif-utils render-page -i INDEX -l 533 --layout table
```

Reconstructed output is marked `quotable: false` — it is evidence of
what is on the page, not a transcription. Never quote it as the
author's words.

The mode is always explicit: index default → `--layout` override →
`--detect`, which only ever *reports* a hint. **The detector is
uncalibrated**; treat its output as a suggestion to check by eye, not a
verdict.

Layout modes need `page_words`, which older indexes lack — add it with
`rebuild-index --refetch`.

## Building a navigation outline

`derived_outline` gives a book a table of contents you can navigate by —
`outline-list`, and `-b/--book` lookups that resolve chapter to canvas.
Populating it is a vision task, not a CLI one: the printed TOC has to be
read off the page images and turned into structured entries.

**When the user asks to outline a work, build a TOC for a book, populate
or fix a `derived_outline`, or set up navigation for a scan — read
[references/building-outlines.md](references/building-outlines.md)
and follow it.** Check first with `outline-status <db>`; a book that
already has an outline needs nothing.

That reference covers finding the TOC pages, transcribing them across
languages, the page→canvas resolution script
(`scripts/resolve_outline.py`), and when to bail out (plate-only atlases
with no printed TOC). It also points at three further references for the
harder cases: books whose TOC must be reconstructed from body headers,
figure-caption extraction, and worked examples.

Don't try to do this from memory — the failure modes (off-by-one canvas
ranges, invented entries, mis-nested levels) are exactly what the
reference exists to prevent.

## Internet Archive specifics

- Pass a URL (`https://archive.org/details/<id>`), or a bare identifier
  with `-P ia`. Bare identifiers are never auto-detected, since they
  look like anything.
- OCR comes from one whole-book file (`_hocr.html`, or `_djvu.xml` on
  older scans) listed in the manifest's `rendering` array — fetched and
  parsed once, not per page.
- Printed page numbers come from IA's own `_page_numbers.json`, not from
  canvas labels (IA's labels are sequential counters and would be wrong).
- IA's IIIF image endpoint occasionally fails on very large items
  (newspapers). Retry, or fall back to the derivative URLs recorded in
  `archive_files`.
- DjVu-only items: leaf numbering is not guaranteed to line up with
  canvases. The tool warns when it can't corroborate the alignment —
  take that warning seriously before trusting page-to-image mapping.

## Staying current

`--version` reports the running build. To find out whether it is stale:

```bash
iiif-utils check-update
```

It compares the running version against the latest published release
and, when one is newer, prints the `.skill` download URL. A build like
`0.1.0.dev12+g58296f4` is a *development* build of 0.1.0, so it reads
as behind 0.1.0, not ahead of it.

Offer this when the user hits behaviour the docs describe but the
installed copy doesn't have.

## Notes

- Config lives in the source tree and project-local overrides; the HTTP
  cache defaults to `./.iiif-cache` in the working directory.
- `ocr-page` needs `tesseract` installed in the OS.
- Requires `uv` and Python ≥3.10.
- Supersedes **ia-utils**, which is in maintenance mode. Existing
  ia-utils indexes: `migrate-index` for search-only use, or
  `create-index` from the identifier for full function (images, layout).
- The CLI is named `iiif-utils` (that is the Python package); the skill
  is named `digitized-books`. Same thing.
