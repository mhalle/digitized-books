"""`iiif-utils rebuild-index` — recreate FTS without re-fetching ALTO."""
from __future__ import annotations

from pathlib import Path

import click

from iiif_utils.core import database as db_mod
from iiif_utils.utils.logger import Logger


@click.command(name="rebuild-index")
@click.argument("index_path", type=click.Path(exists=True, path_type=Path))
@click.pass_context
def rebuild_index(ctx: click.Context, index_path: Path) -> None:
    """Drop and recreate the FTS5 indexes on an existing SQLite.

    Useful after upgrading iiif-utils or if the FTS tables drift out of
    sync with text_blocks. Does not re-fetch any source files.
    """
    verbose = bool(ctx.obj.get("verbose")) if ctx.obj else False
    log = Logger(verbose=verbose)
    db = db_mod.open_db(index_path)
    log.info(f"rebuilding FTS in {index_path}")
    db_mod.build_fts(db)
    size_mb = index_path.stat().st_size / 1024 / 1024
    click.echo(f"FTS rebuilt in {index_path}  ({size_mb:.1f} MB)")
