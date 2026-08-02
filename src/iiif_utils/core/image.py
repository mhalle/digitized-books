"""Image post-processing for downloaded page images.

Ported from `ia-utils/core/image.py::process_image`. Scans of old
letterpress are frequently flat and grey — autocontrast is what makes
them legible, and on plates it is often the difference between seeing
an engraving's hatching and not.

Deliberately narrow: this is the ia-utils feature set (autocontrast
with cutoff / preserve-tone, plus JPEG quality), not a general image
pipeline.
"""
from __future__ import annotations

from io import BytesIO

from PIL import Image, ImageOps


def wants_processing(*, autocontrast: bool, cutoff: int | None,
                      preserve_tone: bool, quality: int | None) -> bool:
    """True when any option would actually change the bytes."""
    return bool(autocontrast or cutoff is not None or preserve_tone
                or quality is not None)


def process_image(image_bytes: bytes, *, output_format: str = "jpg",
                   quality: int | None = None, autocontrast: bool = False,
                   cutoff: int | None = None,
                   preserve_tone: bool = False) -> bytes:
    """Apply optional autocontrast / format / quality; return new bytes.

    Passing `--cutoff` or `--preserve-tone` implies autocontrast — they
    are meaningless otherwise, and requiring the extra flag only ever
    produced silently-unprocessed output (ia-utils made the same call).
    Default cutoff is 2%, which is what suits the scans in practice.

    JP2 with nothing to do is returned untouched: Pillow cannot write
    JP2, so re-encoding would mean silently changing the format.
    """
    apply_ac = autocontrast or cutoff is not None or preserve_tone
    if output_format.lower() == "jp2" and not apply_ac and quality is None:
        return image_bytes

    img: Image.Image = Image.open(BytesIO(image_bytes))
    if apply_ac:
        img = ImageOps.autocontrast(
            img,
            cutoff=cutoff if cutoff is not None else 2,
            preserve_tone=preserve_tone,
        )

    save_format = output_format.upper()
    save_kwargs: dict[str, object] = {}
    if output_format.lower() in ("jpg", "jpeg"):
        save_format = "JPEG"
        if img.mode in ("RGBA", "LA", "P"):
            # JPEG has no alpha — flatten onto white rather than letting
            # Pillow raise, which is what a scan with a transparency
            # channel would otherwise do.
            if img.mode == "P":
                img = img.convert("RGBA")
            background = Image.new("RGB", img.size, (255, 255, 255))
            background.paste(
                img, mask=img.split()[-1] if img.mode == "RGBA" else None)
            img = background
        if quality is not None:
            save_kwargs["quality"] = quality

    out = BytesIO()
    img.save(out, format=save_format, **save_kwargs)
    return out.getvalue()
