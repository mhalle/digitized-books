"""iiif-utils — CLI for indexing IIIF digitized collections."""

try:
    from iiif_utils._version import __version__ as __version__
except ImportError:
    __version__ = "0.0.0"

__all__ = ["__version__"]
