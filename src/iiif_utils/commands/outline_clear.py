"""`iiif-utils outline-clear` — delete all rows from derived_outline."""
from __future__ import annotations

from pathlib import Path

import click

from iiif_utils.core import database as db_mod
from iiif_utils.core import outline as outline_mod


@click.command(name="outline-clear")
@click.argument("index_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--yes", is_flag=True, default=False, help="Skip the confirmation prompt."
)
def outline_clear(index_path: Path, yes: bool) -> None:
    """Delete all rows from derived_outline.

    The table itself is kept; only its contents are wiped. Use before
    re-importing an outline. Other tables (page_numbers, text_blocks,
    illustrations, ranges, …) are untouched.
    """
    db = db_mod.open_db(index_path)
    if outline_mod.OUTLINE_TABLE not in db.table_names():
        click.echo("(no derived_outline table; nothing to clear)", err=True)
        return

    n = db.execute(
        f"SELECT COUNT(*) FROM {outline_mod.OUTLINE_TABLE}"
    ).fetchone()[0]
    if n == 0:
        click.echo("(derived_outline already empty)", err=True)
        return

    if not yes:
        click.confirm(
            f"Delete {n} outline rows from {index_path}?", abort=True
        )

    with db.conn:
        db.execute(f"DELETE FROM {outline_mod.OUTLINE_TABLE}")
    click.echo(f"deleted {n} rows from {index_path}")
