# Page numbers — canvas label → printed page

Investigates how IIIF (Wellcome specifically) encodes the printed page
number for each canvas, the analog of IA's `page_numbers` table.

## What's here

`recon.py` (inline in this README, hasn't been factored out yet) — fetches
4 representative Wellcome manifests, classifies every canvas label, and
reports the distribution. See `results/findings.md` for the writeup.

## Findings (Wellcome)

Canvas `label` carries the printed page number directly. Convention is
uniform across all sampled works:

- `'-'` (literal dash) → unnumbered page (cover, blank, plate, *or* roman
  front matter — Wellcome flattens all of these into `'-'`)
- digit string (e.g. `'126'`) → printed page number

No roman numerals, no folio marks (`1r`/`1v`), no compound labels (`"Plate
IV"`) observed in any of 4 works (atlas, textbook, dissection manual,
small open-access book).

## Schema mapping for v1

| Wellcome | `page_numbers` column | Notes |
|---|---|---|
| canvas index | `leaf_num` | 0-indexed, matches IA convention |
| canvas label `'-'` | `book_page_number = NULL` | |
| canvas label digit string | `book_page_number = <string>` | Stored as TEXT, no coercion |
| — | `confidence`, `pageProb`, `wordConf` | NULL — Wellcome doesn't expose |

## Known limitations (Wellcome)

1. **Roman-numeral front matter is lost in `label` but present in the
   OCR.** Verified on Morris Anatomy 1914 front matter:
   - canvas 11, label `'-'`, OCR top-of-page: `vi ARRANGEMENT OF...`
   - canvas 13, label `'-'`, OCR top-of-page: `viii EDITOR'S PREFACE...`
   - canvas 18, label `'-'`, OCR top-of-page: `CONTENTS | xiu | PAGE`
     (OCR misread `xiii` → `xiu`)

   All three are real printed roman-numeral pages whose headers are
   visible in ALTO but whose canvas labels are `'-'`. The data exists,
   it's just not surfaced in the structured field. A v1.5 backfill
   could scan top/bottom of `text_blocks` for an isolated roman token
   and write it into `book_page_number` — but v1 stores `NULL` and the
   user navigates by `leaf_num`.
2. **Non-monotonic transitions exist.** Cunningham Manual had 7,
   Spalteholz vols 1 & 2 had 1 each. Causes: plate insertions, volume
   boundaries mid-pagination, or genuine printer errors.
3. **In Collection-of-Manifests works, `book_page_number` is not
   unique.** Spalteholz vol 1 ends at p.257; vol 2 starts at p.255
   (overlap). Use `(canvas_id, book_page_number)` as the join key
   across volumes.
