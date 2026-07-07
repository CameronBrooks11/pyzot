"""Shared Rich rendering helpers."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from pyzot.models import Collection, Item


def make_console(color: bool = True, width: int = 160) -> Console:
    return (
        Console(highlight=False, markup=True, width=width)
        if color
        else Console(highlight=False, no_color=True, width=width)
    )


def items_table(items: list[Item], title: str = "Items") -> Table:
    t = Table(title=title, show_lines=False, highlight=False)
    t.add_column("#", style="dim", no_wrap=True, width=6)
    t.add_column("Key", style="cyan", no_wrap=True, width=9)
    t.add_column("Type", style="magenta", no_wrap=True, width=18)
    t.add_column("Title")
    t.add_column("Authors", width=24)
    t.add_column("Year", width=6)

    for i, item in enumerate(items, start=1):
        t.add_row(
            str(i),
            item.key,
            item.item_type,
            item.title[:80],
            item.authors_short,
            item.year or "",
        )
    return t


def item_panel(item: Item, collections: list[Collection] | None = None) -> Panel:
    lines: list[str] = []
    lines.append(f"[bold]Title[/bold]    {item.title}")
    if item.authors:
        lines.append(f"[bold]Authors[/bold]  {'; '.join(item.authors[:5])}")
    if item.year:
        lines.append(f"[bold]Year[/bold]     {item.year}")
    if "publicationTitle" in item.fields:
        lines.append(f"[bold]Journal[/bold]  {item.fields['publicationTitle']}")
    if item.doi:
        lines.append(f"[bold]DOI[/bold]      {item.doi}")
    if item.citation_key:
        lines.append(f"[bold]CiteKey[/bold]  {item.citation_key}")
    if collections:
        col_str = ", ".join(f"{c.name}" for c in collections)
        lines.append(f"[bold]Colls[/bold]    {col_str}")
    if item.tags:
        tag_str = " ".join(f"[{t}]" for t in item.tags[:10])
        lines.append(f"[bold]Tags[/bold]     {tag_str}")

    for field, value in sorted(item.fields.items()):
        if field in ("title", "DOI", "publicationTitle", "date", "citationKey"):
            continue
        if value:
            lines.append(f"[dim]{field:12}[/dim] {value[:80]}")

    if item.attachments:
        lines.append("\n[bold]Attachments[/bold]")
        for att in item.attachments:
            icon = "[green]✓[/green]" if att.file_exists else "[red]✗[/red]"
            name = att.filename or att.content_type or "?"
            lines.append(f"  {icon} {name}  [dim]({att.link_mode_name})[/dim]")

    if item.notes:
        lines.append(f"\n[bold]Notes[/bold] ({len(item.notes)})")
        for note in item.notes[:3]:
            snippet = (note.plain_text or "")[:120].replace("\n", " ")
            lines.append(f"  • {snippet}")

    body = "\n".join(lines)
    return Panel(
        body,
        title=f"[bold cyan]{item.item_type}[/bold cyan] [dim]#{item.item_id}[/dim]  [bold]{item.key}[/bold]",
        expand=False,
    )


def collection_tree(roots: list[Collection], tree: Tree | None = None) -> Tree:
    if tree is None:
        tree = Tree("[bold blue]Collections[/bold blue]")
    for col in roots:
        label = f"[green]{col.name}[/green] [dim]({col.item_count})[/dim]"
        branch = tree.add(label)
        if col.children:
            collection_tree(col.children, branch)
    return tree
