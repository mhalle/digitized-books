"""Slug helpers for output filenames."""
from __future__ import annotations

import re

_WORD = re.compile(r"[^\w\s-]")
_SPACES = re.compile(r"[-\s]+")


def slugify(text: str, max_len: int = 60) -> str:
    """Lowercase, hyphenate, strip punctuation. Stable across runs."""
    text = _WORD.sub("", text.lower()).strip()
    text = _SPACES.sub("-", text).strip("-")
    if max_len and len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "untitled"
