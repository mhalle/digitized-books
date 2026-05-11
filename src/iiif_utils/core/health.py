"""Manifest health checks (DESIGN.md §5).

Detect the three Wellcome pathologies surfaced in CORPUS.md / morris_index:

- Zero canvases (bibliographic-only record).
- Partial digitisation (e.g. "Section 2 only").
- Within-manifest concatenation of multiple physical volumes (Cunningham
  Manual case — second 'Cover' Range marks the volume break).

Each check returns a `(flag_value, reason)` tuple. Reason is a short
human-readable string suitable for inclusion in `index_metadata`.
"""
from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from iiif_utils.core import manifest as manifest_mod


@dataclass(frozen=True)
class HealthFlags:
    partial_digitization: str | None
    contains_multiple_volumes: str | None


_PARTIAL_RE = re.compile(
    r"\b(section|part|vol(?:ume)?|fragment)\s*\d*\b\s*(only|alone)?|"
    r"\bfragment\b|\bsupplement\b",
    re.IGNORECASE,
)


def detect_partial_digitization(manifest: dict[str, Any]) -> str | None:
    """Return a reason string if heuristically partial, else None.

    Signals:
      - title or label contains 'Section N only', 'Part N only', 'fragment',
        'supplement'
      - manifest_metadata.Physical description says 'volumes' (plural) but
        there is only one structural Range whose label looks like 'Cover'
        (i.e. apparent volume count == 1 against bibliographic plural)
    """
    title = manifest_mod.label_string(manifest.get("label")) or ""
    if _PARTIAL_RE.search(title):
        return f"label contains a partial-digitisation marker: {title[:100]!r}"

    md = manifest_mod.metadata_entries(manifest)
    pd = md.get("manifest_metadata:Physical description") or ""
    if pd:
        if _PARTIAL_RE.search(pd):
            return ("Physical description contains partial-digitisation marker: "
                    f"{pd[:100]!r}")
    return None


def detect_multiple_volumes(manifest: dict[str, Any]) -> str | None:
    """Detect within-manifest concatenation of multiple physical volumes.

    Heuristic (DESIGN.md §3.7): two-or-more top-level Ranges whose labels
    are identical and look structural (case-insensitive 'Cover',
    'Frontispiece', 'Title page'). Cunningham Manual reference case:
    second 'Cover' Range marks the volume break.
    """
    ranges = manifest_mod.ranges(manifest)
    top_level_labels = [r.label for r in ranges if r.depth == 0 and r.label]
    if not top_level_labels:
        return None

    counts = Counter((lbl or "").strip().lower() for lbl in top_level_labels)
    structural = {"cover", "frontispiece", "title page"}
    for label, n in counts.items():
        if label in structural and n >= 2:
            return (f"top-level Range labelled {label!r} appears {n} times — "
                    "looks like concatenated volumes")
    return None


def manifest_health(manifest: dict[str, Any]) -> HealthFlags:
    return HealthFlags(
        partial_digitization=detect_partial_digitization(manifest),
        contains_multiple_volumes=detect_multiple_volumes(manifest),
    )
