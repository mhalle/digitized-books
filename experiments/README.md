# Experiments

Throwaway / exploratory code that informs design decisions for `iiif-utils`.
Nothing in this tree is part of the shipped tool. Each subdirectory is a
self-contained experiment with its own scripts, cached data, and results.

| Experiment | Question | Status |
|---|---|---|
| [alto_vs_ia](alto_vs_ia/) | How does Wellcome ALTO compare to Internet Archive hOCR for the same work? Drives §3.5 of `docs/DESIGN.md`. | active |

Each experiment uses `uv` for its environment, with its own `pyproject.toml`
isolated from the (eventual) `src/iiif_utils/` package. `data/` and `results/`
inside each experiment are gitignored — re-runnable from scripts.
