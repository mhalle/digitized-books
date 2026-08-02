"""Reading-order reconstruction from word geometry (WORD_GEOMETRY_PLAN §5).

Three modes, and the choice between them is *explicit* — never inferred
silently (§3.2). Detection exists, but only as a labeled hint: silent
auto-detection converts a wrong guess into invisible corruption, which
is the failure class this whole feature exists to prevent.

  raw      OCR order, verbatim. The default. `quotable`.
  columns  Cluster by x into columns, read each top-to-bottom. Fixes
           newspaper prose braided line-by-line across a gutter.
  table    Cluster by y into rows, read each left-to-right. Fixes
           tabular matter that OCR columnized into disconnected stacks.

Same geometry, inverted grouping axis: one algorithm cannot serve both,
and applying the wrong one produces fluent, plausible, wrong text.
Reconstructed output therefore carries `quotable=False` (§3.4) — it is
evidence of what is on the page, not a transcription.

The clustering is deliberately dumb (§8: "resist making it clever").
The dumb version recovered 32k records in the field; keep it
inspectable.
"""
from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from iiif_utils.core.wordgeom import PageWords, Word

LAYOUTS = ("raw", "columns", "table")

# §5 table step 2: row-break tolerance as a fraction of median word
# height, self-calibrating per page. 0.7 matched the field report's
# hand-found ±30px on a volume whose median height was ~27px.
_ROW_TOL_FACTOR = 0.7
_ROW_TOL_FLOOR = 6
# §5 table step 1: only nearest-right-neighbours within this vertical
# distance contribute to the skew estimate.
_SKEW_MAX_DY = 25
# §5 columns step 1: a gutter must be at least this fraction of page
# width to count as a confident word-free interval.
_MIN_GUTTER_FRAC = 0.003


@dataclass(frozen=True)
class Rendering:
    """Result of rendering a page in some layout."""
    layout: str
    lines: list[str]
    quotable: bool

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


# §7 requires ~40 labeled pages before a confidence number ships, and
# that exercise has NOT been run. Until it is, `detect` reports signals
# for a human to read and `contradiction_warning` stays silent — an
# uncalibrated detector contradicting a deliberate configuration would
# push users toward the wrong layout, which is the exact failure this
# feature exists to prevent. Known miss: on the poll-book fixture
# (assessedpollscit1965newt leaf 533, a genuine table) it reports
# 'raw' at 0.67 — defensible at line granularity, since hOCR's own
# ocr_line grouping already yields correct rows there, but wrong as a
# page-level verdict.
DETECTOR_CALIBRATED = False


@dataclass(frozen=True)
class LayoutHint:
    """Detector output. A hint — never applied on its own (§3.2)."""
    layout_hint: str
    confidence: float
    signals: dict[str, object]
    calibrated: bool = DETECTOR_CALIBRATED


def _cy(wd: Word) -> float:
    return wd.y + wd.h / 2.0


def _cx(wd: Word) -> float:
    return wd.x + wd.w / 2.0


def estimate_skew(words: list[Word]) -> float:
    """Median slope of nearest-right-neighbour word pairs (§5 table 1).

    Deskewing first matters more than tuning tolerance: the field
    report's ±22px fragmentation turned out to be skew, not noise.
    After correction, even half the tolerance did not fragment rows.
    """
    if len(words) < 2:
        return 0.0
    by_x = sorted(words, key=_cx)
    slopes: list[float] = []
    for i, wd in enumerate(by_x):
        wx, wy = _cx(wd), _cy(wd)
        for other in by_x[i + 1:i + 6]:
            dx = _cx(other) - wx
            if dx <= 0:
                continue
            dy = _cy(other) - wy
            if abs(dy) <= _SKEW_MAX_DY:
                slopes.append(dy / dx)
            break
    if not slopes:
        return 0.0
    return median(slopes)


def row_tolerance(words: list[Word]) -> float:
    """Self-calibrating row-break tolerance (§5 table 2, §7)."""
    if not words:
        return float(_ROW_TOL_FLOOR)
    med_h = median([wd.h for wd in words if wd.h > 0] or [0])
    return max(float(_ROW_TOL_FLOOR), _ROW_TOL_FACTOR * med_h)


def render_table(page: PageWords) -> Rendering:
    """Row-cluster by corrected y, emit rows left-to-right (§5 table).

    Deskew → sort by corrected y-centre → new row when the gap exceeds
    the self-calibrated tolerance, tracking a running-mean row centre so
    a slowly drifting baseline doesn't accumulate into a false break.
    """
    words = page.words
    if not words:
        return Rendering(layout="table", lines=[], quotable=False)

    slope = estimate_skew(words)
    corrected = [(_cy(wd) - slope * _cx(wd), wd) for wd in words]
    corrected.sort(key=lambda t: t[0])
    tol = row_tolerance(words)

    rows: list[list[Word]] = []
    row: list[Word] = []
    centre = 0.0
    for cy, wd in corrected:
        if row and abs(cy - centre) > tol:
            rows.append(row)
            row, centre = [wd], cy
            continue
        row.append(wd)
        # running mean keeps the centre honest as the row fills
        centre = centre + (cy - centre) / len(row) if len(row) > 1 else cy
    if row:
        rows.append(row)

    lines = [" ".join(wd.text for wd in sorted(r, key=_cx) if wd.text)
             for r in rows]
    return Rendering(layout="table",
                      lines=[ln for ln in lines if ln.strip()],
                      quotable=False)


def _free_intervals(line: list[Word], min_gap: float) -> list[float]:
    """x positions of word-free gaps inside a line, wider than min_gap."""
    if len(line) < 2:
        return []
    ordered = sorted(line, key=lambda wd: wd.x)
    out: list[float] = []
    for a, b in zip(ordered, ordered[1:]):
        gap = b.x - (a.x + a.w)
        if gap >= min_gap:
            out.append((a.x + a.w + b.x) / 2.0)
    return out


def render_columns(page: PageWords, *, page_width: int | None = None
                    ) -> Rendering:
    """Split braided lines at a learned gutter, emit column by column (§5).

    Two passes, because real gutters can be *narrower than word
    spacing* (26px vs 38-41px on the proving page) — only alignment
    with the page's column grid finds those. Pass 1 collects confident
    wide gaps; pass 2 accepts a narrower gap only where the grid
    predicts one.

    No-regression rule: a line with no gutter found is never split. It
    stays braided, exactly as it is today.
    """
    lines = page.lines()
    if not lines:
        return Rendering(layout="columns", lines=[], quotable=False)

    width = page_width or max(
        (wd.x + wd.w for wd in page.words), default=0)
    min_gap = max(1.0, _MIN_GUTTER_FRAC * width) if width else 1.0

    # Pass 1 — confident gutters vote for the page's column grid.
    votes: list[float] = []
    for line in lines:
        if len(line) >= 3:
            votes.extend(_free_intervals(line, min_gap * 4))
    grid: list[float] = []
    for v in sorted(votes):
        if not grid or v - grid[-1] > min_gap * 4:
            grid.append(v)

    def split_at(line: list[Word]) -> float | None:
        cands = _free_intervals(line, min_gap * 4)
        if cands:
            return cands[0]
        if not grid:
            return None
        # Pass 2: narrow gap, but only where the grid predicts one.
        for g in _free_intervals(line, min_gap):
            if any(abs(g - gv) <= min_gap * 4 for gv in grid):
                return g
        return None

    left_out: list[str] = []
    right_out: list[str] = []
    unsplit: list[str] = []
    for line in lines:
        ordered = sorted(line, key=lambda wd: wd.x)
        cut = split_at(ordered) if len(ordered) >= 2 else None
        if cut is None:
            unsplit.append(" ".join(wd.text for wd in ordered if wd.text))
            continue
        left = [wd for wd in ordered if _cx(wd) < cut]
        right = [wd for wd in ordered if _cx(wd) >= cut]
        if left:
            left_out.append(" ".join(wd.text for wd in left if wd.text))
        if right:
            right_out.append(" ".join(wd.text for wd in right if wd.text))

    out = [ln for ln in (left_out + right_out + unsplit) if ln.strip()]
    return Rendering(layout="columns", lines=out, quotable=False)


def render_raw(page: PageWords) -> Rendering:
    """OCR order, verbatim — the only quotable rendering."""
    return Rendering(
        layout="raw",
        lines=[" ".join(wd.text for wd in line if wd.text)
               for line in page.lines()
               if any(wd.text for wd in line)],
        quotable=True,
    )


def render(page: PageWords, layout: str, *, page_width: int | None = None
            ) -> Rendering:
    if layout == "table":
        return render_table(page)
    if layout == "columns":
        return render_columns(page, page_width=page_width)
    if layout == "raw":
        return render_raw(page)
    raise ValueError(f"unknown layout {layout!r}; expected one of {LAYOUTS}")


def detect(page: PageWords) -> LayoutHint:
    """Classify a page's layout — a HINT ONLY, never auto-applied (§3.2).

    Signals (§5 detect):
      a. left_edge_peaks — tables produce many aligned left edges;
         n-column prose produces about n margin peaks.
      b. width_variance  — justified prose lines are near-constant
         width; table rows are short and ragged.
      c. stacked_columns — the smoking gun for a columnized table: tall
         one-token-per-line stacks sitting side by side with
         interleaved y-ranges.

    Confidence is the share of signals agreeing with the verdict. It is
    uncalibrated until the §7 labeling exercise runs; treat it as
    ordinal, not as a probability.
    """
    words = page.words
    lines = [ln for ln in page.lines() if ln]
    if not words or not lines:
        return LayoutHint("raw", 0.0, {"reason": "no words"})

    # a. left-edge histogram
    tol = max(4.0, row_tolerance(words))
    edges = sorted(wd.x for wd in words)
    peaks = 1
    for a, b in zip(edges, edges[1:]):
        if b - a > tol * 2:
            peaks += 1
    left_edge_peaks = peaks

    # b. line-width variance (normalized)
    widths = [max(wd.x + wd.w for wd in ln) - min(wd.x for wd in ln)
              for ln in lines]
    mean_w = sum(widths) / len(widths) if widths else 0.0
    width_cv = ((median([abs(w - mean_w) for w in widths]) / mean_w)
                if mean_w else 0.0)

    # c. one-token-per-line stacks
    short_lines = sum(1 for ln in lines if len(ln) == 1)
    stacked_frac = short_lines / len(lines)

    table_votes = 0
    total = 3
    if left_edge_peaks >= 4:
        table_votes += 1
    if width_cv > 0.35:
        table_votes += 1
    if stacked_frac > 0.4:
        table_votes += 1

    signals: dict[str, object] = {
        "left_edge_peaks": left_edge_peaks,
        "width_cv": round(width_cv, 3),
        "stacked_frac": round(stacked_frac, 3),
    }
    if table_votes >= 2:
        return LayoutHint("table", table_votes / total, signals)
    return LayoutHint("columns" if left_edge_peaks in (2, 3) else "raw",
                       (total - table_votes) / total, signals)


def contradiction_warning(configured: str, hint: LayoutHint,
                           *, threshold: float = 0.66) -> str | None:
    """Config wins, but a confident disagreement is never silent (§3.3).

    Returns None while the detector is uncalibrated (§7): a warning
    sourced from an unvalidated classifier is worse than no warning,
    because acting on it means switching to the wrong layout.
    """
    if not hint.calibrated:
        return None
    if hint.layout_hint == configured or hint.confidence < threshold:
        return None
    return (f"layout={configured} configured; geometry suggests "
            f"{hint.layout_hint} ({hint.confidence:.2f}) — "
            f"signals {hint.signals}")
