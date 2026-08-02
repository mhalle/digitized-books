"""Main CLI entry point for iiif-utils."""
from __future__ import annotations

import click

from iiif_utils import __version__
from iiif_utils.commands.create_index import create_index
from iiif_utils.commands.get_figure import get_figure
from iiif_utils.commands.get_info import get_info
from iiif_utils.commands.get_page import get_page
from iiif_utils.commands.get_pages import get_pages
from iiif_utils.commands.get_pdf import get_pdf
from iiif_utils.commands.get_region import get_region
from iiif_utils.commands.get_text import get_text
from iiif_utils.commands.get_url import get_url
from iiif_utils.commands.info import info
from iiif_utils.commands.list_figures import list_figures
from iiif_utils.commands.list_files import list_files
from iiif_utils.commands.ocr_page import ocr_page
from iiif_utils.commands.outline_clear import outline_clear
from iiif_utils.commands.outline_import import outline_import
from iiif_utils.commands.outline_list import outline_list
from iiif_utils.commands.outline_status import outline_status
from iiif_utils.commands.rebuild_index import rebuild_index
from iiif_utils.commands.search_catalog import search_catalog
from iiif_utils.commands.render_page import render_page
from iiif_utils.commands.search_index import search_index


@click.group()
@click.version_option(version=__version__, prog_name="iiif-utils")
@click.option("-v", "--verbose", is_flag=True, help="Verbose output to stderr.")
@click.pass_context
def cli(ctx: click.Context, verbose: bool) -> None:
    """Tools for indexing IIIF digitized collections.

    \b
    Typical workflow:
      1. info <manifest_url|b-number>             # peek at a work
      2. create-index <manifest_url|b-number>     # build a SQLite index
      3. search-index -i index.sqlite -q femur    # full-text search
      4. get-figure / get-region / get-page       # pull cropped images
    """
    ctx.ensure_object(dict)
    ctx.obj["verbose"] = verbose


cli.add_command(info)
cli.add_command(list_files)
cli.add_command(ocr_page)
cli.add_command(create_index)
cli.add_command(rebuild_index)
cli.add_command(search_catalog)
cli.add_command(search_catalog, name="search-cat")  # alias
cli.add_command(search_index)
cli.add_command(render_page)
cli.add_command(get_info)
cli.add_command(get_page)
cli.add_command(get_pages)
cli.add_command(get_pdf)
cli.add_command(get_figure)
cli.add_command(get_region)
cli.add_command(get_text)
cli.add_command(get_url)
cli.add_command(list_figures)
cli.add_command(outline_import)
cli.add_command(outline_list)
cli.add_command(outline_status)
cli.add_command(outline_clear)


if __name__ == "__main__":
    cli()
