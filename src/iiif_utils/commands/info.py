"""`iiif-utils info` — show metadata about a manifest or an index."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import click

from iiif_utils.config import load_config
from iiif_utils.core import http as http_
from iiif_utils.core import manifest as manifest_mod
from iiif_utils.providers import resolve


@click.command()
@click.argument("ref", required=False)
@click.option("-i", "--index", type=click.Path(exists=True, path_type=Path),
              help="Read metadata from an existing index SQLite instead.")
@click.option("-P", "--provider", default=None,
              help="Override provider (e.g. wellcome).")
@click.option("--config", "config_path", type=click.Path(path_type=Path),
              default=None, help="Override config file path.")
@click.pass_context
def info(ctx: click.Context, ref: str | None, index: Path | None,
          provider: str | None, config_path: Path | None) -> None:
    """Show metadata about an index file or a remote manifest.

    Examples:

      iiif-utils info path/to/index.sqlite
      iiif-utils info https://iiif.wellcomecollection.org/presentation/b21212600
      iiif-utils info b22396147 -P wellcome
    """
    if index and not ref:
        _info_from_index(index)
        return
    if not ref:
        raise click.UsageError("Provide either a manifest URL/identifier or -i INDEX.")

    cfg = load_config(config_path)
    cache_dir = Path(cfg.get("http", {}).get("cache_dir", "./.iiif-cache")).expanduser()

    ref_obj = resolve(ref, cfg=cfg, explicit_provider=provider, cache_dir=cache_dir)
    m = http_.fetch_json(ref_obj.manifest_url, cfg_http=cfg.get("http", {}),
                          cache_dir=cache_dir)

    _print_kv("manifest_url", ref_obj.manifest_url)
    _print_kv("provider", ref_obj.provider_key)
    _print_kv("type", manifest_mod.manifest_type(m))
    _print_kv("presentation_api_version", manifest_mod.presentation_version(m))
    _print_kv("label", manifest_mod.label_string(m.get("label")))

    if manifest_mod.manifest_type(m) == "Collection":
        children = m.get("items", [])
        _print_kv("collection_members", str(len(children)))
        for c in children[:10]:
            _print_kv("  member", c.get("id") or c.get("@id", ""))
        return

    canvases = manifest_mod.canvases(m)
    _print_kv("canvas_count", str(len(canvases)))
    n_alto = sum(1 for c in canvases if c.alto_url)
    _print_kv("canvases_with_alto", f"{n_alto}/{len(canvases)}")
    _print_kv("first_image_service", canvases[0].image_service_url
                                       if canvases else None)

    renderings = manifest_mod.renderings(m)
    if renderings:
        click.echo("renderings:")
        for r in renderings:
            click.echo(f"  {r.format or '?':<24}  {r.url}")

    md = manifest_mod.metadata_entries(m)
    if md:
        click.echo("manifest_metadata:")
        for k, v in md.items():
            click.echo(f"  {k[len('manifest_metadata:'):]:<24}  {v[:100]}")

    for k, v in ref_obj.extra_metadata.items():
        _print_kv(k, v)


def _print_kv(k: str, v: Any) -> None:
    if v is None:
        return
    click.echo(f"{k:<28}  {v}")


def _info_from_index(index: Path) -> None:
    conn = sqlite3.connect(f"file:{index}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    click.echo(f"# {index.name}")
    for table in ("index_metadata", "document_metadata"):
        try:
            rows = list(conn.execute(f"SELECT key, value FROM {table}"))
        except sqlite3.OperationalError:
            continue
        if not rows:
            continue
        click.echo(f"\n## {table}")
        for r in rows:
            v = (r["value"] or "")
            if len(v) > 100:
                v = v[:100] + "…"
            click.echo(f"  {r['key']:<32}  {v}")
    # Counts
    try:
        n_canvases = conn.execute(
            "SELECT COUNT(*) FROM page_numbers"
        ).fetchone()[0]
        n_blocks = conn.execute(
            "SELECT COUNT(*) FROM text_blocks"
        ).fetchone()[0]
        n_illus = conn.execute(
            "SELECT COUNT(*) FROM illustrations"
        ).fetchone()[0]
        click.echo("\n## counts")
        click.echo(f"  canvases:      {n_canvases}")
        click.echo(f"  text_blocks:   {n_blocks}")
        click.echo(f"  illustrations: {n_illus}")
    except sqlite3.OperationalError:
        pass
