"""`iiif-utils check-update` — is a newer release available?

This repository ships as both a Python package and an Agent Skill, so
an installed copy can drift behind the published one with nothing to
signal it. `--version` says what is running; this says whether that is
current, and where to get the newer bundle.

Version comparison is deliberately conservative: a release tag is a
plain `MAJOR.MINOR.PATCH`, and anything the running build appends
(`.dev40+g58296f48`, from hatch-vcs on an untagged checkout) marks it
as a development build *of* that release rather than a newer one.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click

from iiif_utils import __version__
from iiif_utils.core import http as http_
from iiif_utils.utils import output as output_

REPO = "mhalle/digitized-books"
LATEST_RELEASE_API = f"https://api.github.com/repos/{REPO}/releases/latest"
SKILL_DOWNLOAD = (
    f"https://github.com/{REPO}/releases/latest/download/digitized-books.skill"
)

_RELEASE_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


def parse_version(text: str) -> tuple[tuple[int, int, int], bool] | None:
    """Return ((major, minor, patch), is_dev) or None if unparseable.

    `is_dev` marks anything trailing the release triple — hatch-vcs
    emits `0.0.1.dev40+g58296f48` for an untagged checkout, which is a
    build *before* 0.0.1, not after it.
    """
    m = _RELEASE_RE.match(text.strip())
    if not m:
        return None
    triple = (int(m.group(1)), int(m.group(2)), int(m.group(3)))
    rest = text.strip()[m.end():]
    return triple, bool(rest)


def compare(running: str, latest: str) -> str:
    """'current' | 'behind' | 'ahead' | 'unknown'."""
    a, b = parse_version(running), parse_version(latest)
    if a is None or b is None:
        return "unknown"
    (a_triple, a_dev), (b_triple, _) = a, b
    if a_triple < b_triple:
        return "behind"
    if a_triple > b_triple:
        return "ahead"
    # Same triple: a dev build is pre-release, so it trails the tag.
    return "behind" if a_dev else "current"


@click.command(name="check-update")
@output_.format_option(default="records")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None)
def check_update(fmt: str, config_path: Path | None) -> None:
    """Check whether a newer release is published."""
    from iiif_utils.config import load_config
    cfg = load_config(config_path)

    try:
        payload = http_.fetch_json(LATEST_RELEASE_API,
                                    cfg_http=cfg.get("http", {}))
    except Exception as e:
        raise click.ClickException(
            f"Could not reach the GitHub releases API ({e}). "
            f"Check manually: https://github.com/{REPO}/releases/latest"
        ) from e

    latest = str(payload.get("tag_name") or "").strip()
    if not latest:
        raise click.ClickException(
            f"No tag_name in the release payload — has {REPO} published a "
            f"release yet? https://github.com/{REPO}/releases")

    status = compare(__version__, latest)
    rec: dict[str, Any] = {
        "running": __version__,
        "latest": latest,
        "status": status,
        "published": payload.get("published_at"),
        "download": SKILL_DOWNLOAD,
    }
    output_.write_records([rec], fmt)

    if fmt in ("table", "records"):
        if status == "behind":
            click.echo(f"\n  Update available: {__version__} → {latest}\n"
                       f"  {SKILL_DOWNLOAD}", err=True)
        elif status == "current":
            click.echo("\n  Up to date.", err=True)
        elif status == "ahead":
            click.echo("\n  Running a build newer than the latest release.",
                       err=True)
        else:
            click.echo("\n  Could not compare versions.", err=True)
