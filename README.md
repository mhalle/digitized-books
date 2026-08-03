# digitized-books / iiif-utils

One tool for scanned books held by the **Internet Archive** and by IIIF
libraries — **Wellcome Collection**, **Library of Congress**, **Gallica
(BnF)**, **Munich MDZ**, **Heidelberg**. Index a book's OCR into SQLite,
search inside it, read a page, crop a figure, or reconstruct pages whose
reading order the OCR scrambled — with the same commands and the same
index schema whatever the source.

This repository is both the Python package (`iiif-utils`) and the Agent
Skill (`digitized-books`). Same thing, one repo.

Supersedes [`ia-utils`](https://github.com/mhalle/ia-utils), now in
maintenance mode; `migrate-index` reads its indexes.

## Quick start

```bash
uv sync --extra dev
uv run iiif-utils --version

# Internet Archive
uv run iiif-utils create-index https://archive.org/details/anatomyofhumanbo1918gray
uv run iiif-utils search-index -i ia_anatomyofhumanbo1918gray.sqlite -q "lymphatic vessels"
uv run iiif-utils get-text -i ia_anatomyofhumanbo1918gray.sqlite -b 687

# Wellcome, by b-number
uv run iiif-utils create-index b22396147
```

Indexes are named `{provider}_{identifier}.sqlite`.

`-l/--leaf` is the 0-based scan index; `-b/--book` is the number printed
on the page. They differ by the front-matter offset — see
[CLAUDE.md](CLAUDE.md#gotchas).

## As a skill

```bash
sh scripts/build-skill.sh          # -> dist/digitized-books.skill
```

Installed, it runs from a bundled wheel in an ephemeral uv environment —
no persistent install, and it works from a read-only directory. In a
checkout it runs from source instead, so edits take effect immediately.
`iiif-utils check-update` reports whether a newer release exists.

## What's here

| Path | What |
|---|---|
| `SKILL.md` | The skill: what it does, when to use it, how to invoke it. |
| `CLAUDE.md` | Developing in this repo — commands, invariants, gotchas. |
| `docs/DESIGN.md` | Schema and design rationale, empirically grounded. |
| `docs/RELEASING.md` | How releases work, and why versions drift in a checkout. |
| `docs/OUTLINE.md` | The `derived_outline` navigation schema. |
| `docs/WELLCOME_NOTES.md` | Field notes on Wellcome's APIs. |
| `src/iiif_utils/` | The package. |
| `references/` | Loaded on demand by the skill; outline-building lives here. |
| `scripts/` | `iiif-utils` launcher, `build-skill.sh`, `release.sh`, `resolve_outline.py`. |

The corpus catalogue and recon experiments moved to the sibling
`medical-library` repository; this one is tooling.

## Development

```bash
uv sync --extra dev            # `--dev` alone omits pytest/ruff/mypy
uv run pytest -q
uv run ruff check src/ tests/  # not `.` — scripts/ holds scratch files
uv run mypy src/
```

## Releasing

```bash
sh scripts/release.sh X.Y.Z --push
```

Refuses on a dirty tree, an existing tag, failing checks, or a missing
CHANGELOG entry. CI builds the bundle from a clean checkout at the tag —
the only state where the embedded version is right. Never ship a locally
built artifact. Details and rationale in
[docs/RELEASING.md](docs/RELEASING.md).

## Licence

Apache-2.0. See [LICENSE](LICENSE).
