"""CLI — `zot items` subcommands."""

from __future__ import annotations

import click
from rich.panel import Panel
from rich.table import Table

from pyzot.cli.main import Context, pass_ctx
from pyzot.cli.render import item_panel, items_table, make_console
from pyzot.config import get_library_auth
from pyzot.queries.collections import get_collection_by_name, get_items_in_collection
from pyzot.queries.items import get_item, get_items
from pyzot.queries.search import get_item_fulltext_with_strategy


@click.group()
def items():
    """Browse Zotero items."""


@items.command("list")
@click.option("--type", "item_type", default=None, help="Filter by item type")
@click.option("--collection", "col_name", default=None, help="Filter by collection name/ID")
@click.option("--limit", default=50, show_default=True, help="Max items to show")
@pass_ctx
def list_items(ctx: Context, item_type: str | None, col_name: str | None, limit: int):
    """List items (paginated)."""
    console = make_console(ctx.color)

    if col_name:
        if col_name.isdigit():
            from pyzot.queries.collections import get_collection_by_id

            col = get_collection_by_id(ctx.db, int(col_name))
        else:
            matches = get_collection_by_name(ctx.db, col_name, fuzzy=True)
            col = matches[0] if matches else None
        if col is None:
            raise click.ClickException(f"Collection not found: {col_name!r}")
        result = get_items_in_collection(ctx.db, col.collection_id)
        if item_type:
            result = [i for i in result if i.item_type.lower() == item_type.lower()]
        result = result[:limit]
        title = f"{col.name} — {len(result)} items"
    else:
        result = get_items(ctx.db, library_id=ctx.library_id, item_type=item_type, limit=limit)
        title = f"{len(result)} items"

    if not result:
        console.print("[dim]No items found.[/dim]")
        return
    console.print(items_table(result, title=title))


@items.command("show")
@click.argument("id_or_key")
@pass_ctx
def show_item(ctx: Context, id_or_key: str):
    """Show full details for an item."""
    console = make_console(ctx.color)
    item_id = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(ctx.db, item_id)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    from pyzot.queries.collections import get_collection_by_id

    cols = []
    if item.collections:
        for cid in item.collections:
            c = get_collection_by_id(ctx.db, cid)
            if c:
                cols.append(c)

    # attachments and notes already populated by _build_items
    console.print(item_panel(item, collections=cols))


@items.command("attachments")
@click.argument("id_or_key")
@pass_ctx
def item_attachments(ctx: Context, id_or_key: str):
    """List attachments for an item."""
    console = make_console(ctx.color)
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(ctx.db, item_id_val)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    if not item.attachments:
        console.print("[dim]No attachments.[/dim]")
        return

    t = Table(title=f"Attachments for {item.key}")
    t.add_column("Key", style="cyan")
    t.add_column("Type")
    t.add_column("Mode")
    t.add_column("Exists")
    t.add_column("Path")
    for att in item.attachments:
        exists = "[green]✓[/green]" if att.file_exists else "[red]✗[/red]"
        path_str = str(att.absolute_path) if att.absolute_path else att.path or ""
        t.add_row(att.key, att.content_type, att.link_mode_name, exists, path_str[:80])
    console.print(t)


@items.command("notes")
@click.argument("id_or_key")
@pass_ctx
def item_notes(ctx: Context, id_or_key: str):
    """Show notes attached to an item."""
    console = make_console(ctx.color)
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(ctx.db, item_id_val)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    if not item.notes:
        console.print("[dim]No notes.[/dim]")
        return

    for note in item.notes:
        console.print(Panel(note.plain_text[:2000], title=note.title or "Note"))


@items.command("fulltext")
@click.argument("id_or_key")
@click.option(
    "--max-chars", default=10000, show_default=True, help="Maximum number of characters to print"
)
@click.option(
    "--offline", is_flag=True, help="Skip network/auth retrieval and only use local Zotero data"
)
@pass_ctx
def item_fulltext(
    ctx: Context,
    id_or_key: str,
    max_chars: int,
    offline: bool,
):
    """Retrieve full text for an item with network/auth/local fallback."""
    console = make_console(ctx.color)
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    auth = get_library_auth(ctx.library_id)

    text, source = get_item_fulltext_with_strategy(
        ctx.db,
        item_id_val,
        prefer_network=not offline,
        auth=auth,
    )
    if text is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    title = f"Full text for {id_or_key}"
    console.print(f"[dim]Source: {source}[/dim]")
    console.print(Panel(text[:max_chars], title=title))
