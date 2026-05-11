# iiif-utils

CLI for indexing and downloading from IIIF digitized collections — a IIIF-side
companion to [`ia-utils`](https://github.com/mhalle/ia-utils). Index a
manifest into a SQLite database (canvases, page numbers, OCR text with
bboxes, illustrations, FTS); then search, navigate, and pull cropped
images straight from the IIIF Image API.

Status: **early — single-document M1 path** (see [docs/DESIGN.md](docs/DESIGN.md)
§11). The schema is empirically grounded; not all commands are wired yet.

## Quick start

```bash
uv sync
uv run iiif-utils --version
uv run iiif-utils info https://iiif.wellcomecollection.org/presentation/b21212600
uv run iiif-utils create-index https://iiif.wellcomecollection.org/presentation/b22396147 \
    -d ./indexes
```

## What's here

| Path | What |
|---|---|
| `docs/DESIGN.md` | Full design rationale, schema, milestones. |
| `docs/CORPUS.md` | A curated public-domain anatomy corpus (eventual ingest target). |
| `docs/WELLCOME_NOTES.md` | Field notes on Wellcome's APIs. |
| `experiments/` | Throwaway recon — Spalteholz ALTO study, Morris full-book index. |
| `src/iiif_utils/` | The package. |

## Development

```bash
uv sync --dev
uv run pytest
uv run ruff check .
uv run mypy src
```
