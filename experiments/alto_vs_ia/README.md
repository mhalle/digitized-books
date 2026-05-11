# ALTO vs IA hOCR — Spalteholz

Empirical study driving `docs/DESIGN.md` §3.5. Test pair:

- **Wellcome**: work `d8quuwxg`, IIIF Collection `b31362126` (Hand atlas of
  human anatomy, Spalteholz, 1929/30 Lippincott English). 3 manifests:
  - `https://iiif.wellcomecollection.org/presentation/b31362126_0001` (Vol 1)
  - `https://iiif.wellcomecollection.org/presentation/b31362126_0002` (Vol 2)
  - `https://iiif.wellcomecollection.org/presentation/b31362126_0003` (Vol 3)
- **Internet Archive**: item `b31362138`, the 1933 Lippincott reprint of the
  same translation, 3 volumes bound as one (976 leaves). Already indexed by
  `ia-utils` at `../../../internet-archive/b31362138.sqlite` — hOCR mode
  with bbox, confidence, font-size, parent_carea_id columns populated.

The two sides should share ~all text (3 years apart, same translator,
same publisher). Differences in `text_blocks` will therefore mostly
reflect format (ALTO vs hOCR) and engine choices, not different OCR runs.

## Layout

| Path | Purpose |
|---|---|
| `scripts/` | Numbered scripts, one per experiment + a shared `fetch.py` |
| `data/` | Cached downloads (manifests, ALTO XMLs, sampled hOCR rows). Gitignored — regenerable. |
| `results/` | Generated reports (Markdown + JSON). Gitignored — regenerable. |

## Running

```bash
cd experiments/alto_vs_ia
uv sync
uv run python scripts/fetch.py          # cache manifests + sampled ALTOs
uv run python scripts/e1_granularity.py # TextBlock vs TextLine sweep
# ...etc
```

## Experiments

1. **e1_granularity** — TextBlock-per-row vs TextLine-per-row from the same
   ALTO files. Compare row count, mean text length, FTS-snippet quality.
2. **e2_text_overlap** — On 20 sampled pages aligned by visual landmark,
   measure Levenshtein / token-Jaccard between IA hOCR and Wellcome ALTO
   text. Is the underlying OCR the same?
3. **e3_coord_units** — Audit `MeasurementUnit` and bbox magnitudes across
   sampled ALTOs from different scan eras.
4. **e4_confidence_calibration** — Compare `x_wconf` (IA) and `WC` (ALTO)
   distributions on the same hand-corrected sample.
5. **e5_illustrations** — Count `<Illustration>` / `<GraphicalElement>`
   regions per page; decide whether a dedicated table is warranted.
6. **e6_reading_order** — On multi-column pages, check whether document
   order of `<TextBlock>`s reproduces reading order or whether `IDNEXT`
   chains must be followed.

Findings roll up to `../docs/ALTO_vs_IA_OCR.md` (created when the study
finishes), which is what §3.5 of `DESIGN.md` will cite.
