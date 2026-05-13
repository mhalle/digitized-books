"""`iiif-utils outline-import` — bulk-load a derived navigation outline."""
from __future__ import annotations

import json
from pathlib import Path

import click

from iiif_utils.core import database as db_mod
from iiif_utils.core import outline as outline_mod
from iiif_utils.utils.logger import Logger


@click.command(name="outline-import")
@click.argument("index_path", type=click.Path(exists=True, path_type=Path))
@click.argument("payload_path", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--replace",
    is_flag=True,
    default=False,
    help="Clear existing derived_outline rows before importing.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Validate the payload without writing to the db.",
)
@click.pass_context
def outline_import(
    ctx: click.Context,
    index_path: Path,
    payload_path: Path,
    replace: bool,
    dry_run: bool,
) -> None:
    """Bulk-load a derived navigation outline into a work's sqlite index.

    The payload is a JSON document. See docs/OUTLINE.md for the schema; a
    machine-validatable JSON Schema lives at docs/OUTLINE_SCHEMA.json.

    Atomic: validation errors or insertion failures roll back the
    transaction. Refuses to import over an existing outline unless
    --replace is given.
    """
    verbose = bool(ctx.obj.get("verbose")) if ctx.obj else False
    log = Logger(verbose=verbose)

    try:
        payload = json.loads(payload_path.read_text())
    except json.JSONDecodeError as exc:
        raise click.ClickException(f"{payload_path}: invalid JSON — {exc}") from exc

    db = db_mod.open_db(index_path)

    work = outline_mod.work_id(db)
    if not work:
        raise click.ClickException(
            f"{index_path}: no work id in document_metadata — "
            f"is this a real iiif-utils index?"
        )

    errors = outline_mod.validate_payload(
        payload,
        expected_work=work,
        max_canvas_idx=outline_mod.max_canvas(db),
    )
    if errors:
        msg = "validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
        raise click.ClickException(msg)

    total = outline_mod.count_entries(payload["entries"])

    if dry_run:
        click.echo(f"OK (dry-run): {total} entries valid for {work}")
        return

    outline_mod.ensure_table(db)

    existing = db.execute(
        f"SELECT COUNT(*) FROM {outline_mod.OUTLINE_TABLE}"
    ).fetchone()[0]
    if existing and not replace:
        raise click.ClickException(
            f"{outline_mod.OUTLINE_TABLE} already has {existing} rows. "
            f"Pass --replace to overwrite."
        )

    with db.conn:
        if existing and replace:
            db.execute(f"DELETE FROM {outline_mod.OUTLINE_TABLE}")
            log.info(f"cleared {existing} existing rows")
        n = outline_mod.insert_tree(db, payload["entries"])

    click.echo(f"imported {n} outline entries into {index_path}")
