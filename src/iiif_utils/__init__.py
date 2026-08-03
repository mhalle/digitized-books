"""iiif-utils — CLI for indexing IIIF digitized collections."""

# Version resolution, most authoritative first.
#
# `_version.py` is written by hatch-vcs at BUILD time and baked into the
# wheel, so an installed or bundled copy is self-describing with no git
# and no network. In a checkout it is a disposable build side-effect —
# gitignored, and deliberately deleted by scripts/build-skill.sh, because
# a stale one will happily report a version that was true for a tree
# state that no longer exists.
#
# Installed-package metadata is the next best thing: also snapshotted at
# install time, but it cannot linger in a working tree.
#
# Nothing here consults git at runtime. Only a build does. A checkout's
# reported version is therefore approximate by design, which is why
# release artifacts are built by CI from a clean checkout at a tag —
# see docs/RELEASING.md.
try:
    from iiif_utils._version import __version__ as __version__
except ImportError:  # pragma: no cover - depends on install shape
    try:
        from importlib.metadata import PackageNotFoundError, version

        __version__ = version("iiif-utils")
    except PackageNotFoundError:  # running from source, never installed
        __version__ = "0+unknown"

__all__ = ["__version__"]
