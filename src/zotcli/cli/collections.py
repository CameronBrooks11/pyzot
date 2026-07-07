"""CLI — `zot collections` subcommands."""

from __future__ import annotations

import click
from rich.table import Table

from zotcli.cli.main import pass_ctx, Context
from zotcli.cli.render import make_console, collection_tree, items_table
from zotcli.queries.collections import (
    get_all_collections,
    get_collection_tree,
    get_collection_by_id,
    get_collection_by_name,
    get_items_in_collection,
)


@click.group()
def collections():
    """Browse Zotero collections."""


@collections.command("list")
@click.option("--flat", is_flag=True, help="Flat list with IDs instead of tree view")
@pass_ctx
def list_collections(ctx: Context, flat: bool):
    """Print the collection tree."""
    console = make_console(ctx.color)
    if flat:
        cols = get_all_collections(ctx.db, ctx.library_id)
        t = Table(show_header=True)
        t.add_column("ID", style="dim", width=8)
        t.add_column("Key", style="cyan", width=10)
        t.add_column("Name")
        t.add_column("Parent", width=8)
        t.add_column("Items", width=7)
        for c in cols:
            t.add_row(
                str(c.collection_id),
                c.key,
                c.name,
                str(c.parent_collection_id or ""),
                str(c.item_count),
            )
        console.print(t)
    else:
        roots = get_collection_tree(ctx.db, ctx.library_id)
        tree = collection_tree(roots)
        console.print(tree)


@collections.command("show")
@click.argument("id_or_name")
@pass_ctx
def show_collection(ctx: Context, id_or_name: str):
    """Show details for a collection."""
    console = make_console(ctx.color)
    col = _resolve_collection(ctx, id_or_name)
    if col is None:
        raise click.ClickException(f"Collection not found: {id_or_name!r}")
    console.print(f"[bold]{col.name}[/bold]  ID={col.collection_id}  Key={col.key}")
    console.print(f"Parent: {col.parent_collection_id or '(root)'}")
    console.print(f"Items: {col.item_count}")


@collections.command("items")
@click.argument("id_or_name")
@click.option("--recursive", "-r", is_flag=True, help="Include sub-collections")
@click.option("--type", "item_type", default=None, help="Filter to item type (e.g. journalArticle)")
@pass_ctx
def collection_items(ctx: Context, id_or_name: str, recursive: bool, item_type: str | None):
    """List items in a collection."""
    console = make_console(ctx.color)
    col = _resolve_collection(ctx, id_or_name)
    if col is None:
        raise click.ClickException(f"Collection not found: {id_or_name!r}")

    items = get_items_in_collection(ctx.db, col.collection_id, recursive=recursive)
    if item_type:
        items = [i for i in items if i.item_type.lower() == item_type.lower()]

    if not items:
        console.print(f"[dim]No items in collection {col.name!r}[/dim]")
        return

    t = items_table(items, title=f"{col.name} ({len(items)} items)")
    console.print(t)


def _resolve_collection(ctx: Context, id_or_name: str):
    """Resolve a collection ID (int) or name (str)."""
    from zotcli.queries.collections import get_collection_by_id, get_collection_by_name

    if id_or_name.isdigit():
        return get_collection_by_id(ctx.db, int(id_or_name))
    matches = get_collection_by_name(ctx.db, id_or_name, fuzzy=False)
    if not matches:
        matches = get_collection_by_name(ctx.db, id_or_name, fuzzy=True)
    return matches[0] if matches else None


@collections.command("assign")
@click.argument("item_key")
@click.argument("collection_name")
@pass_ctx
def assign_collection(ctx: Context, item_key: str, collection_name: str):
    """Assign an existing item to a collection.

    Does not remove the item from any existing collections (additive only).

    Examples:

    \b
        zot collection assign AB3CD7EF "Smart Grid"
        zot collection assign AB3CD7EF "[Paper] LV_UG_Cable_Models_DSSE"
    """
    from zotcli.queries.collections import get_collection_by_name
    from zotcli.queries.items import get_item
    from zotcli.write.collection_assign import assign_item_to_collection, is_item_in_collection

    item = get_item(ctx.db, item_key)
    if item is None:
        raise click.ClickException(f"Item not found: {item_key!r}")

    matches = get_collection_by_name(ctx.db, collection_name, fuzzy=False)
    if not matches:
        matches = get_collection_by_name(ctx.db, collection_name, fuzzy=True)
    if not matches:
        raise click.ClickException(f"Collection not found: {collection_name!r}")
    col = matches[0]

    if is_item_in_collection(ctx.db, item.item_id, col.collection_id):
        click.echo(f"Item {item_key} is already in collection {col.name!r}.")
        return

    assigned = assign_item_to_collection(ctx.db.path, item.item_id, col.collection_id)
    if assigned:
        click.echo(f"Assigned {item_key} — {item.title!r} to collection {col.name!r}.")
    else:
        click.echo(f"Item {item_key} is already in collection {col.name!r}.")
