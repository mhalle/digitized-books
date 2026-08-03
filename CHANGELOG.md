# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.1] - 2026-08-03

First usable release. 0.1.0 was withdrawn — its bundle was mislabelled
and its tag has been deleted, so nothing references it. The feature list
below under 0.1.0 describes what this release contains.

### Fixed

- The withdrawn 0.1.0 bundle shipped a wheel stamped
  `0.1.1.dev0+gbaef62c2e.d20260803` rather than `0.1.0`. The release
  workflow patched `pyproject.toml`'s `fallback-version` — a tracked
  file — before building, so the tree was dirty and `hatch-vcs` marked
  the build accordingly. Version pinning now happens on the staged
  bundle copy after the wheel is built from a pristine tree, and the
  pinned value is read back from the wheel so the two cannot disagree.
- CI installed no dev dependencies (`uv run --frozen pytest` omits the
  `dev` extra), so the 0.1.0 run failed before it could publish. CI now
  syncs with `--extra dev` and runs ruff and mypy alongside the tests.

Use this release rather than 0.1.0.

## [0.1.0] - withdrawn

Never usable: the published bundle carried a mislabelled version, and
the release and tag were deleted the same day. Its contents shipped as
0.1.1. Retained here because it is the feature inventory for that
release.

The CLI is `iiif-utils`; the Agent Skill is
`digitized-books`. They are the same thing — this repository is
simultaneously a Python package and a skill.

### Added

#### Providers

- **Internet Archive** as a full provider — catalog search, full-text
  indexing, page images, figure crops, outlines. Not a viewer bolted on.
- **Wellcome Collection** (b-numbers and catalogue work IDs, multi-volume
  child manifests), **Library of Congress** (manifest synthesised from
  item JSON, which LoC does not publish directly), **Munich MDZ**,
  **Gallica (BnF)**, **Heidelberg**, and a **generic** adapter for any
  clean IIIF v2/v3 host.

#### Indexing

- `create-index` builds a SQLite index from a manifest, parsing OCR from
  ALTO, hOCR, DjVu XML, or per-canvas plain text as available.
- Internet Archive publishes OCR as one whole-book file (`_hocr.html`, or
  `_djvu.xml` on older scans) listed in the manifest's `rendering` array
  rather than per canvas. A monolithic branch fetches and parses it once.
- Printed page numbers come from a provider's own detection where it
  exists — for IA, `_page_numbers.json`, carrying per-leaf confidence.
- `rebuild-index` refreshes FTS; `--refetch` re-parses the OCR source in
  place, **preserving `derived_outline`**, which a fresh `create-index`
  would discard.
- `migrate-index` converts an `ia-utils` index to this dialect, always
  writing a new file and never touching the source.

#### Word geometry and reading order

- Indexes retain per-word boxes (`page_words`), so reading order is a
  derived view rather than frozen at index time.
- `render-page --layout raw|columns|table` — `columns` unbraids
  multi-column prose that OCR interleaved; `table` reassembles tabular
  matter OCR split into vertical stacks.
- Reconstructed output is marked `quotable: false`: it is evidence of
  what is on the page, not a transcription. FTS stays on raw OCR order,
  so a miscoded layout can never poison search.
- Layout is always explicit — index default, then per-call override.
  Detection exists but only ever *reports* a hint (see Known limitations).

#### Reading and images

- `search-index` (FTS5, block or page granularity), `get-text`
  (whole-work rendering, or per-page from the index), `get-page-stats`
  (`--figures` finds plate pages), `search-catalog -P ia|wellcome|loc`.
- `get-page`, `get-pages` (`--zip`, `--mosaic`, `--sample`),
  `get-region`, `get-figure`, `list-figures`, `get-pdf`, `get-url`,
  `get-info`, `ocr-page` (local Tesseract).
- Image post-processing: `--autocontrast`, `--cutoff`, `--preserve-tone`,
  `--quality`. Flat grey letterpress scans are often illegible without it.
- `derived_outline` plus `outline-import` / `-list` / `-status` / `-clear`
  for per-book navigation.

#### Packaging

- Ships as an Agent Skill from this same repository — `SKILL.md` at the
  root beside `pyproject.toml` and `src/`.
- `scripts/iiif-utils` runs the bundled wheel in an ephemeral uv
  environment, so an installed skill needs no persistent install and
  works when mounted read-only; a checkout runs from source instead.
- `check-update` compares the running build against the latest release.

### Fixed

- **Internet Archive page numbers.** IA's IIIF canvas labels are
  sequential counters, so leaf 24 of Gray's *Anatomy* (1918) — printed
  page 20 — was labelled `25`. Now agrees with `ia-utils` on 1402/1402
  leaves (Gray) and 563/563 (Charcot).
- **`-b/--book` with non-numeric pages.** Printed page numbers are text —
  roman front matter (`xii`), plate suffixes (`12a`) — and previously
  raised an unhandled error.
- **Ambiguous printed pages.** Plates repeat numbers and bound volumes
  restart at 1, so several leaves can claim one printed page. The tool
  now refuses and names the candidates instead of silently returning
  whichever row sorted first.
- **Cross-command joins.** Page-addressed output emits both `leaf` and
  `canvas` for the same value; previously `search-index` emitted only one
  and `get-page-stats` only the other, so joining them raised `KeyError`.

### Known limitations

- **The layout detector is uncalibrated.** Publishing a confidence number
  requires labelling ~40 pages, which has not been done, so
  `contradiction_warning` stays silent — a warning from an unvalidated
  classifier would push users toward the wrong layout. Known miss: it
  calls a genuine poll-book table page `raw` at 0.67.
- **DjVu leaf numbering cannot be corroborated against canvases.** Two
  real items disagree: `ecturesondiseas00chargoog` is contiguous and
  lines up, while `assessedpollscit1965newt` is sparse and sits one off.
  No single offset reconciles both, so a warning fires rather than
  letting text attach silently to the wrong images. DjVu remains a
  fallback for items with no hOCR at all.
- **Gallica OCR** is reachable only from some networks; image-only use
  works everywhere.
- `migrate-index` cannot reconstruct canvas/image columns or word
  geometry, since `ia-utils` never stored them. Both limits are recorded
  in the migrated index's `index_metadata`.

[0.1.1]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.1
