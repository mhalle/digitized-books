"""Word-level geometry: the `page_words` blob codec.

Implements WORD_GEOMETRY_PLAN §4. OCR reading order is a lossy
*rendering*, not data — so we retain per-word boxes at index time and
make reading order a derived view (§3.1). A miscoded book is then a
wrong rendering, recoverable by flipping one metadata value, never a
corrupted index.

Coordinate space: native scan pixels, top-left origin, x/y/w/h boxes.
All coords observed in the corpora fit uint16 (max page dim seen:
10,176); anything larger is clamped rather than allowed to wrap.

## Divergence from the plan's codec, and why

The plan (§4, §9.2) specifies geometry-only columns plus a `tpl` table
for the ~1.5% of lines whose text-token count differs from their
word-box count. That shape exists because in the newton deployment the
*text* lives in a separate store, so blob and text must be re-paired at
read time.

Here the blob carries its own tokens. That removes `tpl` entirely —
there is nothing to re-pair, so no divergence to record — and it means
`page_words` cannot be silently desynchronized from `text_blocks` by
any later change to block filtering or ordering. The cost is the token
bytes, which zlib takes down to roughly the size of the geometry
columns; §9.3's "always-on is affordable" conclusion still holds
comfortably. `index_metadata.words_schema` versions the format.
"""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass, field

_MAGIC = b"IWG1"
_VERSION = 1
WORDS_SCHEMA = "1"

_U16_MAX = 65535
_CONF_NULL = 255      # u8 sentinel
_FSIZE_NULL = 0       # u16 sentinel


@dataclass(frozen=True)
class Word:
    """One OCR word box. `conf`/`fsize` are None when the source lacks them.

    DjVu gives coords only; ALTO gives coords + confidence; hOCR gives
    all three. `fsize` makes heading detection structural rather than
    regex-based (§3.6).
    """
    text: str
    x: int
    y: int
    w: int
    h: int
    conf: int | None = None
    fsize: int | None = None


@dataclass
class PageWords:
    """Words of one page, plus the OCR's own line grouping.

    `words_per_line` sums to len(words); it preserves the source's line
    structure so column mode can split lines at a gutter without
    re-deriving lines from geometry.
    """
    words: list[Word] = field(default_factory=list)
    words_per_line: list[int] = field(default_factory=list)

    def lines(self) -> list[list[Word]]:
        out: list[list[Word]] = []
        i = 0
        for n in self.words_per_line:
            out.append(self.words[i:i + n])
            i += n
        if i < len(self.words):          # tolerate a truncated line map
            out.append(self.words[i:])
        return out


def _clamp(v: int) -> int:
    return 0 if v < 0 else (_U16_MAX if v > _U16_MAX else v)


def encode(page: PageWords) -> bytes:
    """Pack a page's words into a compressed blob.

    Columnar layout (all x, then all y, ...) rather than interleaved:
    adjacent values within a column are highly similar, which is what
    zlib exploits.
    """
    words = page.words
    n = len(words)
    lines = page.words_per_line
    parts: list[bytes] = [
        _MAGIC,
        struct.pack("<BII", _VERSION, n, len(lines)),
    ]
    for attr in ("x", "y", "w", "h"):
        parts.append(struct.pack(
            f"<{n}H", *(_clamp(getattr(wd, attr)) for wd in words)))
    parts.append(struct.pack(f"<{len(lines)}H",
                              *(_clamp(v) for v in lines)))
    parts.append(struct.pack(
        f"<{n}B",
        *((_CONF_NULL if wd.conf is None else max(0, min(254, wd.conf)))
          for wd in words)))
    parts.append(struct.pack(
        f"<{n}H",
        *((_FSIZE_NULL if wd.fsize is None else _clamp(wd.fsize))
          for wd in words)))
    blob = b"\x00".join(wd.text.encode("utf-8") for wd in words)
    parts.append(struct.pack("<I", len(blob)))
    parts.append(blob)
    return zlib.compress(b"".join(parts), 6)


def decode(data: bytes) -> PageWords:
    """Unpack a blob written by `encode`. Raises ValueError if unreadable."""
    try:
        raw = zlib.decompress(data)
    except zlib.error as e:
        raise ValueError(f"page_words blob is not zlib data: {e}") from e
    if raw[:4] != _MAGIC:
        raise ValueError("page_words blob has wrong magic")
    version, n, n_lines = struct.unpack_from("<BII", raw, 4)
    if version != _VERSION:
        raise ValueError(f"page_words schema {version} unsupported "
                         f"(this build reads {_VERSION})")
    off = 4 + struct.calcsize("<BII")

    cols: dict[str, tuple[int, ...]] = {}
    for attr in ("x", "y", "w", "h"):
        cols[attr] = struct.unpack_from(f"<{n}H", raw, off)
        off += 2 * n
    lines = list(struct.unpack_from(f"<{n_lines}H", raw, off))
    off += 2 * n_lines
    confs = struct.unpack_from(f"<{n}B", raw, off)
    off += n
    fsizes = struct.unpack_from(f"<{n}H", raw, off)
    off += 2 * n
    (text_len,) = struct.unpack_from("<I", raw, off)
    off += 4
    text_blob = raw[off:off + text_len]
    tokens = text_blob.split(b"\x00") if text_len else []

    words = [
        Word(
            text=tokens[i].decode("utf-8", errors="replace") if i < len(tokens)
                 else "",
            x=cols["x"][i], y=cols["y"][i],
            w=cols["w"][i], h=cols["h"][i],
            conf=None if confs[i] == _CONF_NULL else confs[i],
            fsize=None if fsizes[i] == _FSIZE_NULL else fsizes[i],
        )
        for i in range(n)
    ]
    return PageWords(words=words, words_per_line=lines)
