"""CLI — `zot export` subcommands."""

from __future__ import annotations

import sys

import click
from rich.progress import Progress, SpinnerColumn, TextColumn

from pyzot.cli.main import pass_ctx, Context
from pyzot.cli.render import make_console
from pyzot.queries.items import get_items, get_item
from pyzot.queries.collections import get_collection_by_name, get_collection_by_id, get_items_in_collection


def _get_items(ctx: Context, collection: str | None, all_items: bool, item_key: str | None = None) -> tuple[list, object | None]:
    """Return (items, collection_obj|None)."""
    if item_key:
        item_id = int(item_key) if item_key.isdigit() else item_key
        item = get_item(ctx.db, item_id)
        if item is None:
            raise click.ClickException(f"Item not found: {item_key!r}")
        return [item], None
    if collection:
        if collection.isdigit():
            col = get_collection_by_id(ctx.db, int(collection))
        else:
            matches = get_collection_by_name(ctx.db, collection, fuzzy=True)
            col = matches[0] if matches else None
        if col is None:
            raise click.ClickException(f"Collection not found: {collection!r}")
        return get_items_in_collection(ctx.db, col.collection_id), col
    if all_items:
        return get_items(ctx.db, library_id=ctx.library_id), None
    raise click.UsageError("Provide --collection NAME, --item KEY/ID, or --all.")


@click.group("export")
def export():
    """Export items to various formats."""


@export.command("json")
@click.option("--collection", "-c", default=None, help="Export a specific collection")
@click.option("--item", "-i", default=None, help="Export a specific item by ID or Key")
@click.option("--all", "all_items", is_flag=True, help="Export entire library")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@pass_ctx
def export_json(ctx: Context, collection: str | None, item: str | None, all_items: bool, output: str | None):
    """Export items as JSON."""
    from pyzot.export.json_ import items_to_json
    items, _ = _get_items(ctx, collection, all_items, item)
    fp = open(output, "w", encoding="utf-8") if output else sys.stdout
    try:
        items_to_json(items, fp)
        if output:
            make_console(ctx.color).print(f"[green]Exported {len(items)} items to {output}[/green]")
    finally:
        if output:
            fp.close()


@export.command("csv")
@click.option("--collection", "-c", default=None, help="Export a specific collection")
@click.option("--item", "-i", default=None, help="Export a specific item by ID or Key")
@click.option("--all", "all_items", is_flag=True, help="Export entire library")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@pass_ctx
def export_csv(ctx: Context, collection: str | None, item: str | None, all_items: bool, output: str | None):
    """Export items as CSV."""
    from pyzot.export.csv_ import items_to_csv
    items, _ = _get_items(ctx, collection, all_items, item)
    fp = open(output, "w", newline="", encoding="utf-8") if output else sys.stdout
    try:
        items_to_csv(items, fp)
        if output:
            make_console(ctx.color).print(f"[green]Exported {len(items)} items to {output}[/green]")
    finally:
        if output:
            fp.close()


@export.command("bib")
@click.option("--collection", "-c", default=None, help="Export a specific collection")
@click.option("--item", "-i", default=None, help="Export a specific item by ID or Key")
@click.option("--all", "all_items", is_flag=True, help="Export entire library")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@pass_ctx
def export_bib(ctx: Context, collection: str | None, item: str | None, all_items: bool, output: str | None):
    """Export items as BibTeX."""
    from pyzot.export.bibtex import items_to_bibtex
    items, _ = _get_items(ctx, collection, all_items, item)
    fp = open(output, "w", encoding="utf-8") if output else sys.stdout
    try:
        items_to_bibtex(items, fp)
        if output:
            make_console(ctx.color).print(f"[green]Exported {len(items)} items to {output}[/green]")
    finally:
        if output:
            fp.close()


@export.command("markdown")
@click.option("--collection", "-c", default=None, help="Export a specific collection")
@click.option("--item", "-i", default=None, help="Export a specific item by ID or Key")
@click.option("--all", "all_items", is_flag=True, help="Export entire library")
@click.option("--output", "-o", default=None, help="Output file (default: stdout)")
@click.option("--notes", is_flag=True, help="Include notes sections")
@pass_ctx
def export_markdown(ctx: Context, collection: str | None, item: str | None, all_items: bool, output: str | None, notes: bool):
    """Export items as a Markdown report."""
    from pyzot.export.markdown import items_to_markdown
    items, col = _get_items(ctx, collection, all_items, item)
    fp = open(output, "w", encoding="utf-8") if output else sys.stdout
    try:
        items_to_markdown(items, collection=col, include_notes=notes, fp=fp)
        if output:
            make_console(ctx.color).print(f"[green]Exported {len(items)} items to {output}[/green]")
    finally:
        if output:
            fp.close()
