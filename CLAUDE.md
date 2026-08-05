# Working in this repo

Notes for an agent picking this up cold. Everything here is something
you would plausibly get wrong without being told.

## This repo is two things at once

It is a Python package (`iiif-utils`, importable as `iiif_utils`) **and**
an Agent Skill (`digitized-books`) — `SKILL.md` sits at the root beside
`pyproject.toml` and `src/`. There is deliberately no separate skill
repo. Consequences:

- The skill's `name` must equal its directory name, so the release
  bundle's root directory is pinned to `digitized-books`, not derived
  from the repo name.
- `SKILL.md` is user-facing documentation for *using* the tool. This
  file is for *developing* it. Don't merge them.

## Commands

```bash
uv sync --extra dev            # NOT `--dev`, which omits pytest/ruff/mypy
uv run pytest -q
uv run ruff check src/ tests/  # NOT `.` — scripts/ holds ad-hoc scratch files
uv run mypy src/
```

Always invoke through `uv run`. Bare `python3` / `pytest` will not find
the environment, and the permissions allowlist is written around
`uv run *`.

## Releasing

Read [docs/RELEASING.md](docs/RELEASING.md) before touching versions or
tags. The short version:

```bash
sh scripts/release.sh X.Y.Z --push
```

**Never ship a locally built artifact.** Release bundles come only from
CI, built from a clean checkout with HEAD exactly at the tag — that is
the only state where the embedded version is correct.

Never commit `wheels/*.whl` or `src/iiif_utils/_version.py`. Both are
build outputs; a committed one becomes a stale liar about the version.

## Gotchas

- **Leaf ≠ printed page, and the relationship is a table.** `-l/--leaf`
  is the 0-based scan index (integer); `-b/--book` is the number printed
  on the page (TEXT — `xii`, `12a`). `page_numbers` maps between them,
  one row per leaf, from the provider's own detection. There is no
  offset to apply: Gray 1918 alone has five distinct leaf-minus-page
  values, shifting at every plate. Never convert by arithmetic — look it
  up. Use `parse_leaf_spec` for one and `parse_book_spec` for the other;
  conflating them was a real bug.
- **Leaf ≠ canvas for Internet Archive.** IA numbers every scan; the
  IIIF manifest keeps only the access leaves (scandata
  `addToAccessFormats`) and renumbers them densely. hOCR `page_N`,
  `_page_numbers.json` `leafNum` and the jp2 file number are all LEAF
  keyed; canvases are not. Translate at ingest with
  `internet_archive.canvas_leaf_map` — storing leaf-keyed data at a
  canvas index shifted every IA book's text against its images. Pure
  IIIF providers have no leaf; canvas is the universal key.
- **"Leaf" is two different numbers on IA, and they disagree.** The
  hOCR page id (`page_000040`) and the scan file number (`_0041.jp2`)
  are separate sequences: Gray 1918 has them equal, `barkuoft` has the
  id one lower, and no arithmetic covers both. So join OCR to canvases
  on the *filename* the `ocr_page` title declares (`image "…/x_0041.jp2"`),
  which the canvas's Image API URL also names — see
  `hocr.page_image_name` / `internet_archive.canvas_image_names`. Fall
  back to the file number only when the hOCR names no usable image
  (Gray writes the placeholder `image https://archive.org/todo`), and
  never accept a partial or non-distinct filename match.
  `_page_numbers.json` `leafNum` is the FILE number (1-based), so page
  numbers must be rekeyed by that map even when the text was joined by
  filename — one `leaf_to_canvas` for both is a bug.
- **Printed page numbers are not unique.** Plates repeat them and bound
  volumes restart at 1, so `resolve_leaf` deliberately *refuses* on an
  ambiguous page rather than picking one. Do not "fix" it to return the
  first match.
- **Records emit both `leaf` and `canvas`** with the same value, on
  purpose, so output joins across commands. Removing either breaks
  callers; see `utils/page.py::page_ref`.
- **The layout detector is uncalibrated**, so `contradiction_warning`
  returns None. That is intentional until ~40 pages are labelled — a
  warning from an unvalidated classifier pushes users toward the wrong
  layout. Do not enable it without doing the calibration.
- **`quotable: false` on reconstructed layouts** (`columns`, `table`) is
  a correctness claim, not decoration: that text is evidence of what is
  on the page, not a transcription. Never present it as a quotation.
- **DjVu leaf numbering can't be corroborated** against canvases on some
  items, so a warning fires. Suppressing it would let text attach
  silently to the wrong images.
- **IA page numbers come from `_page_numbers.json`**, never from canvas
  labels — IA's labels are sequential counters, so using them mislabels
  every page in the book.

## Verifying against real data

Fixtures cover the shapes; real books catch the rest. Several bugs in
this codebase were invisible to fixtures and only appeared when checked
against an actual index — Gray's *Anatomy* (`anatomyofhumanbo1918gray`)
and Charcot (`ecturesondiseas00chargoog`) are the usual reference
items, and `assessedpollscit1965newt` is the table-layout fixture.
Prefer cross-checking against a second, independent source over
asserting that output looks plausible.
