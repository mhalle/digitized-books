# Changelog

All notable changes to this project are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.2] - 2026-08-04

### Fixed

- **IA OCR text was attached to the wrong canvas on some items** — the
  regression reported against 0.2.0/0.2.1. The leaf→canvas translation
  added in 0.2.0 derived the leaf from the scan file number in the
  canvas's Image API URL, then matched it against the hOCR page id.
  Those two agree on some items and not others, and there is no
  arithmetic rule covering both: `anatomyofhumanbo1918gray` has
  `page_000024` ↔ `_0024.jp2`, while `anatomicaltermin00barkuoft` has
  `page_000040` ↔ `_0041.jp2`. Every book of the second shape had its
  text one page out.

  The hOCR spec puts the source scan in the `ocr_page` title
  (`image "…/x_0041.jp2"`), and the canvas's Image API URL addresses
  that same file — so the two now join on the filename, with no
  arithmetic and no per-item assumption. Confirmed against the page
  image: `anatomicaltermin00barkuoft` canvas 40 shows printed page 17,
  and now carries the text of hOCR page 40 ("PARTS OF THE HUMAN BODY
  17") instead of page 41's.

  The file-number map remains the fallback for items whose hOCR names
  no usable image — Gray 1918 writes the placeholder
  `image https://archive.org/todo` on every page — and is still what
  that item's alignment is built from. A partial or non-distinct
  filename match is rejected rather than half-applied.
  `index_metadata.leaf_mapping` now records which join was used
  (`image_filename`, `file_number`, or `identity`).

- **DjVu-sourced books were one page out** for the same reason.
  `parse_djvu_multipage` subtracted 1 from the `usemap` file number to
  "convert to a 0-based leaf" — but that number is an identifier that
  joins to the canvas URL, not an ordinal to renormalise. This affected
  `anatomicalnamese00eycluoft` and `dieanatomischen00hisgoog`, both of
  which have no hOCR at all.

- **Printed page numbers are keyed in a different domain from OCR
  text**, and fixing the text alone would have broken them.
  `_page_numbers.json` `leafNum` is the 1-based scan file number
  (barkuoft: `leafNum 41` → printed `'17'`) while hOCR ids are 0-based.
  The two maps are now kept separate; page numbers are rekeyed by file
  number regardless of how the text was joined.

- `page_numbers.ia_leaf` held a leaf→canvas lookup indexed by canvas,
  i.e. nothing meaningful. It now holds the canvas's actual IA leaf.

### Note for existing indexes

Any IA index built with 0.2.0 or 0.2.1 may have its text offset against
its images by one page; DjVu-sourced ones almost certainly do. Rebuild
IA indexes with `create-index`. Check an existing one with
`sqlite3 <db> "select value from index_metadata where key='leaf_mapping'"`
— an index carrying no such row predates this fix.

## [0.2.1] - 2026-08-04

### Fixed

- **A read timeout silently downgraded the OCR source.**
  `httpx.ReadTimeout` is a *sibling* of the exception classes the retry
  clause listed, not a subclass of any of them, so the entire
  `max_retries` budget was skipped for the one failure archive.org
  actually produces. A single stalled fetch fell straight through to the
  DjVu fallback, and `create-index` reported success — meaning on a bulk
  run the OCR quality of a corpus varied with transient network luck.

  Retries now catch `httpx.TransportError`, which subsumes all four
  previous classes plus every timeout. Verified on
  `sim_american-city-county_1938-04_53_4`: `ocr_source` is now `hocr`
  where it had been `djvu`.

- Connect and read timeouts are configurable separately
  (`connect_timeout_seconds`, `read_timeout_seconds`, default 15 / 180).
  One scalar for both was wrong for a host whose variable cost is
  time-to-first-byte: the same 12.4 MB file transferred in ~1.7s once
  bytes flowed but took anywhere from 1.1s to 45s to start.

- An empty response body is never written to the HTTP cache.

- **`text_blocks.avg_font_size` was always NULL** even though hOCR
  carries `x_fsize` for essentially every word. `TextBlock` had no such
  field, so the column was created and hardcoded to `None`. Now
  populated from the block's per-word **median** — a mean lets a single
  drop cap misreport a body paragraph as display type.

  Caveat worth knowing: in a magazine the largest type is usually
  advertising, so font size alone will not rank article headings first.
  Combine it with `block_type` (`ocr_header`) or page position. The
  column being NULL was a dead end; it is not by itself a heading
  detector.

### Added

- When the preferred OCR source fails, `index_metadata` records
  `ocr_source_fallback_from` and `..._reason`, and the build summary says
  so. A 712-item ingest can be audited with a query instead of by
  scraping stderr.

## [0.2.0] - 2026-08-04

### Fixed

- **Internet Archive indexes stored text and page numbers against the
  wrong pages.** `get-text -l 23` returned printed page 19 while
  `get-page -l 23` returned page 20, and the gap widened through the
  book. Both commands succeeded, so nothing signalled it.

  IA numbers every *leaf* it scanned, including colour-calibration cards
  and leaves marked `Delete`. The IIIF manifest contains only the leaves
  flagged `addToAccessFormats` in scandata, renumbered densely — so
  canvas N is not leaf N. Gray 1918: 1,414 leaves, 1,402 canvases, 12
  omissions in recto/verso pairs, canvas-minus-leaf walking 1, 3, 5, 7,
  9. Everything IA publishes except the manifest is leaf-keyed — hOCR
  `page_N`, `_page_numbers.json`, the jp2 files — and we stored all of
  it at canvas indices.

  Now translated at ingest from the scan file number in each canvas's
  Image API URL, and cross-checked against scandata's
  `addToAccessFormats`. Both sources agreed exactly on every item
  tested; disagreement warns rather than guessing. `page_numbers.ia_leaf`
  records the source leaf, `index_metadata.leaf_mapping` the scheme.

  Verified on Gray at canvases 23, 687 and 1200: image, stored text and
  printed page number now agree.

  **Rebuild any IA index built before this** — `rebuild-index --refetch`
  preserves outlines, and warns when a changed mapping makes an existing
  `derived_outline` stale, since its canvas ranges were resolved under
  the old keying.

  Non-IA providers are unaffected: they have no leaf concept, and canvas
  maps straight to a printed page via the canvas label.

## [0.1.9] - 2026-08-03

### Changed

- Rewrote the leaf-vs-printed-page guidance, which kept producing the
  same mistake. It described the two flags and then gave one example —
  "leaf 24 is printed page 20" — which reads as an offset to apply. It
  is not one. Measured on Gray 1918, the leaf-minus-page difference
  takes **five distinct values** (0 on 57% of pages, then +8, +2, +6,
  +4), shifting at every plate and insert, so arithmetic that works on
  one page is wrong a few pages later.

  There is no rule to learn: there are two flags and a lookup table.
  `-b/--book` for a number that came out of the book, `-l/--leaf` for
  one that came out of this tool, and `page_numbers` maps between them.
  `get-page-stats` prints both columns if you want to see the mapping.

- `get-page` now reports both numbers when it saves —
  `[leaf 24 = printed page 20]`. Addressing the wrong page otherwise
  fails silently: you get a page, just not the one you meant.

## [0.1.8] - 2026-08-03

### Fixed

- `list-figures` and `get-figure` crashed with a raw
  `sqlite3.OperationalError: no such table: illustrations` on any index
  built from hOCR or DjVu. The table is only created when there is
  something to put in it, and neither format has an Illustration
  element — so every Internet Archive index hits this. Both commands now
  explain that it is the source's limitation and point at the caption
  search that does work.

### Added

- `get-region --bbox` accepts percentages (`10%,20%,60%,80%`) and
  fractions (`0.1,0.2,0.6,0.8`) as well as pixels. Isolating a plate
  previously meant eyeballing proportions off a full-page image and
  converting against the page size by hand. Relative forms resolve
  against the canvas's own dimensions, and raise rather than guess when
  those are unknown.

- `SKILL.md` documents the figure-finding path for sources without
  structured illustrations: caption search with `--blocks` gives a bbox
  per match that feeds straight into `get-region`.

## [0.1.7] - 2026-08-03

### Added

- `get-page --source auto|iiif|bookreader|jp2`. Internet Archive serves
  page images outside the Image API, and those endpoints do not share its
  constraints:

  - **bookreader** — `/download/{id}/page/leaf{N}_{small|medium|large}.jpg`,
    keyed on identifier and leaf alone.
  - **jp2** — the original scan, fetched as a *single member* of
    `_jp2.zip` via IA's zip-as-directory URLs. No archive download.

  On `auto` (the default) a failed IIIF fetch now falls back to
  bookreader, then jp2, warning on stderr because the bytes differ from
  what `--size` requested. 0.1.6 claimed such a fallback was impractical;
  that was wrong on both counts.

  The JP2 path is derived from the stored IIIF service URL rather than
  rebuilt from the identifier: the zip and its members are named after
  the item's scan prefix, which frequently is not the identifier —
  `1913-s.-s.-olympic-...` stores pages under `1913 S.S. OLYMPIC White
  Star Line Postcard_jp2/`, so an identifier-derived guess 404s.

  `get-region` and `get-figure` keep no fallback: only IIIF can crop.

## [0.1.6] - 2026-08-03

### Fixed

- **`get-page` failed with 400 on any source narrower than 1400px.** The
  default `--size 1400,` went out unmodified, and IIIF level 2 servers do
  not have to upscale — IA answers an oversized request with 400 rather
  than clamping. A 1280x808 postcard scan was simply unfetchable.

  Requests are now clamped to what the source can serve, using the
  dimensions already in the index (`info.json` only when those are
  missing). `get-page`, `get-pages`, `get-region` and `get-figure` are all
  affected; for the two region commands the bound is the *crop* size, not
  the page, since IIIF size applies to the returned region.

  `resolve_max_size()` only ever handled `--size max`; everything else
  passed through untouched, which is why `resolve_dims()` existed but was
  used only for bbox clamping.

- A failed image fetch now reports what was requested, the source's
  actual dimensions, and what to try — instead of a bare status code.

### Changed

- `SKILL.md` claimed image commands fall back to the derivative URLs in
  `archive_files`. They never did — only the text and PDF paths read that
  table. The claim is corrected rather than the fallback invented:
  extracting one page from a `_jp2.zip` means downloading the whole
  archive, which is not something to do silently. `list-files` and
  `get-url` surface the derivatives for manual use.

## [0.1.5] - 2026-08-03

### Fixed

- The documented invocation now begins with `sh`. The archive records the
  launcher as executable and `unzip(1)` restores that, but Python's
  `zipfile` does not restore Unix mode bits on extraction — and that is
  what installers use, so an installed copy arrives `-rw-r--r--` and
  agents were falling back to `sh` themselves. Nothing in the archive can
  fix this, so the docs stop depending on it. `sh <launcher>` works
  whether or not the bit survived and needs no `chmod` against a
  possibly read-only directory. The allowlist pattern in `SKILL.md`
  is updated to match.

## [0.1.4] - 2026-08-03

### Changed

- **Outline-building is now part of this skill** rather than a separate
  `build-outline.skill` to install alongside it. Populating
  `derived_outline` is core to what this tool is for, so needing a second
  install was wrong.

  It ships as `references/building-outlines.md`, loaded on demand — the
  spec's progressive-disclosure mechanism, which is what lets one archive
  carry the instructions without a second `SKILL.md`. `SKILL.md` says
  explicitly when to read it. The three supporting references and
  `scripts/resolve_outline.py` (stdlib-only) come with it.

  Internal paths were repo-relative (`skills/build-outline/scripts/...`)
  and would have broken once bundled; they are now skill-root-relative
  and verified to resolve inside the archive.

## [0.1.3] - 2026-08-03

### Changed

- **The skill bundle is now self-contained**, assembled from an explicit
  list of what belongs in it rather than a copy of the repository with
  exclusions. It holds `SKILL.md`, the launcher, the wheel, `LICENSE` and
  `CHANGELOG.md` — nothing else. 406K to 133K.

  Every packaging bug here came from the subtractive approach: a stale
  git worktree and a local settings file rode along in the first bundle,
  and a second `SKILL.md` made the next one refuse to install. Under a
  denylist anything new in the repo ships by default; under an allowlist
  a file has to be named to escape. The `.claude` and one-`SKILL.md`
  guards remain as backstops, but they are no longer the mechanism.

  It also removes the duplication: the bundle shipped both `src/` and a
  wheel built from it, leaving open which one actually ran. Now the wheel
  is the code.

- `scripts/build-wheel.sh` removed; `scripts/build-skill.sh` supersedes it.

## [0.1.2] - 2026-08-03

### Fixed

- The 0.1.1 bundle could not be installed: it contained two `SKILL.md`
  files — its own and `skills/build-outline/`'s — and a `.skill` archive
  must hold exactly one. `agentskills validate` passed it, because that
  validates the root skill and has no view of the archive. Sibling skills
  under `skills/` are now excluded from the main bundle and published as
  their own archives (`build-outline.skill`), and the builder aborts if a
  staged bundle ever holds other than exactly one `SKILL.md`.

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

[0.2.1]: https://github.com/mhalle/digitized-books/releases/tag/v0.2.1
[0.2.0]: https://github.com/mhalle/digitized-books/releases/tag/v0.2.0
[0.1.9]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.9
[0.1.8]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.8
[0.1.7]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.7
[0.1.6]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.6
[0.1.5]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.5
[0.1.4]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.4
[0.1.3]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.3
[0.1.2]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.2
[0.1.1]: https://github.com/mhalle/digitized-books/releases/tag/v0.1.1
