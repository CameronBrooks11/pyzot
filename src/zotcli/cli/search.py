"""CLI — `zot search` subcommand."""

from __future__ import annotations

import click

from zotcli.cli.main import pass_ctx, Context
from zotcli.cli.render import make_console, items_table
from zotcli.queries.search import (
    search_items,
    search_fulltext,
    search_by_doi,
    search_by_author,
    search_by_year_range,
)
from zotcli.queries.tags import get_items_by_tag


@click.command("search")
@click.argument("query", required=False, default=None)
@click.option("--field", "fields", multiple=True, help="Restrict search to field(s) e.g. title, abstract")
@click.option("--author", default=None, help="Search by author name (first or last, partial match)")
@click.option("--type", "item_type", default=None, help="Restrict to item type")
@click.option("--doi", default=None, help="Search by DOI")
@click.option("--tag", default=None, help="Search by tag")
@click.option("--year", default=None, help="Year range e.g. 2020-2024 or 2022")
@click.option("--fulltext", is_flag=True, help="Use full-text index instead of field search")
@pass_ctx
def search(
    ctx: Context,
    query: str | None,
    fields: tuple[str, ...],
    author: str | None,
    item_type: str | None,
    doi: str | None,
    tag: str | None,
    year: str | None,
    fulltext: bool,
):
    """Search items across fields, authors, tags, DOIs, or years.

    \b
    Examples:
      zot search "bayesian" --field title
      zot search --author "Numair"
      zot search "power flow" --type journalArticle
      zot search --doi 10.1038/example
      zot search --tag "machine-learning"
      zot search --year 2020-2024
    """
    console = make_console(ctx.color)

    if doi:
        item = search_by_doi(ctx.db, doi)
        items = [item] if item else []
    elif tag:
        items = get_items_by_tag(ctx.db, tag)
    elif author:
        items = search_by_author(ctx.db, author)
        if item_type:
            items = [i for i in items if i.item_type.lower() == item_type.lower()]
    elif year:
        if "-" in year:
            start_s, end_s = year.split("-", 1)
            start, end = int(start_s), int(end_s)
        else:
            start = end = int(year)
        items = search_by_year_range(ctx.db, start, end)
    elif query:
        if fulltext:
            items = search_fulltext(ctx.db, query)
        else:
            items = search_items(ctx.db, query, fields=list(fields) or None, item_type=item_type)
    else:
        raise click.UsageError("Provide a query, --author, --doi, --tag, or --year.")

    if not items:
        console.print("[dim]No results.[/dim]")
        return

    t = items_table(items, title=f"{len(items)} result(s)")
    console.print(t)
