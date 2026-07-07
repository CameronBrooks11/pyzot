"""CLI — `zot stats` subcommands."""

from __future__ import annotations

import click
from rich.table import Table

from pyzot.cli.main import pass_ctx, Context
from pyzot.cli.render import make_console


@click.group("stats", invoke_without_command=True)
@click.pass_context
def stats(ctx: click.Context):
    """Library statistics dashboard."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(_summary)


@stats.command("summary")
@pass_ctx
def _summary(ctx: Context):
    """Overall counts."""
    console = make_console(ctx.color)
    db = ctx.db

    item_count = db.fetchone(
        "SELECT COUNT(*) as n FROM items i "
        "WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes) "
        "AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)"
    )["n"]
    col_count = db.fetchone("SELECT COUNT(*) as n FROM collections")["n"]
    tag_count = db.fetchone("SELECT COUNT(*) as n FROM tags")["n"]
    creator_count = db.fetchone("SELECT COUNT(*) as n FROM creators")["n"]

    t = Table(title="Library Summary", show_header=False)
    t.add_column("Metric", style="bold")
    t.add_column("Value", style="cyan")
    t.add_row("Items", str(item_count))
    t.add_row("Collections", str(col_count))
    t.add_row("Tags", str(tag_count))
    t.add_row("Creators", str(creator_count))
    console.print(t)

    # Item types breakdown
    rows = db.fetchall(
        """
        SELECT it.typeName, COUNT(*) as cnt
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
        GROUP BY it.typeName
        ORDER BY cnt DESC
        """
    )
    t2 = Table(title="Items by Type", show_header=True)
    t2.add_column("Type", style="magenta")
    t2.add_column("Count", style="cyan")
    for r in rows:
        t2.add_row(r["typeName"], str(r["cnt"]))
    console.print(t2)


@stats.command("tags")
@click.option("--top", default=20, show_default=True, help="Number of top tags to show")
@pass_ctx
def _tags(ctx: Context, top: int):
    """Top N tags by frequency."""
    console = make_console(ctx.color)
    from pyzot.queries.tags import get_all_tags
    tags = get_all_tags(ctx.db)[:top]
    t = Table(title=f"Top {top} Tags")
    t.add_column("Tag")
    t.add_column("Items", style="cyan")
    for name, count in tags:
        t.add_row(name, str(count))
    console.print(t)


@stats.command("types")
@pass_ctx
def _types(ctx: Context):
    """Items per item type."""
    console = make_console(ctx.color)
    rows = ctx.db.fetchall(
        """
        SELECT it.typeName, COUNT(*) as cnt
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
        GROUP BY it.typeName
        ORDER BY cnt DESC
        """
    )
    t = Table(title="Items per Type")
    t.add_column("Type", style="magenta")
    t.add_column("Count", style="cyan")
    for r in rows:
        t.add_row(r["typeName"], str(r["cnt"]))
    console.print(t)


@stats.command("years")
@pass_ctx
def _years(ctx: Context):
    """Publication year histogram."""
    console = make_console(ctx.color)
    rows = ctx.db.fetchall(
        """
        SELECT SUBSTR(idv.value, 1, 4) as year, COUNT(*) as cnt
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE f.fieldName = 'date'
          AND CAST(SUBSTR(idv.value, 1, 4) AS INTEGER) > 1900
        GROUP BY year
        ORDER BY year DESC
        """
    )
    t = Table(title="Publications by Year")
    t.add_column("Year", style="bold")
    t.add_column("Count", style="cyan")
    t.add_column("Bar")
    if rows:
        max_cnt = max(r["cnt"] for r in rows)
        for r in rows[:30]:
            bar = "█" * int(r["cnt"] / max_cnt * 30)
            t.add_row(r["year"], str(r["cnt"]), f"[blue]{bar}[/blue]")
    console.print(t)


@stats.command("collections")
@click.option("--top", default=20, show_default=True)
@pass_ctx
def _collections(ctx: Context, top: int):
    """Items per collection (top N)."""
    console = make_console(ctx.color)
    rows = ctx.db.fetchall(
        """
        SELECT c.collectionName, COUNT(ci.itemID) as cnt
        FROM collections c
        LEFT JOIN collectionItems ci ON c.collectionID = ci.collectionID
        GROUP BY c.collectionID, c.collectionName
        ORDER BY cnt DESC
        LIMIT ?
        """,
        (top,),
    )
    t = Table(title=f"Top {top} Collections by Item Count")
    t.add_column("Collection")
    t.add_column("Items", style="cyan")
    for r in rows:
        t.add_row(r["collectionName"], str(r["cnt"]))
    console.print(t)
