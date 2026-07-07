"""Markdown export — human-readable report."""

from __future__ import annotations

from typing import IO

from pyzot.models import Collection, Item


def items_to_markdown(
    items: list[Item],
    collection: Collection | None = None,
    include_notes: bool = False,
    fp: IO[str] | None = None,
) -> str:
    lines: list[str] = []

    if collection:
        lines.append(f"# {collection.name}")
        lines.append(f"\n*{len(items)} items*\n")
    else:
        lines.append(f"# Zotero Export\n\n*{len(items)} items*\n")

    # Table header
    lines.append("| # | Title | Authors | Year | Type | DOI |")
    lines.append("|---|-------|---------|------|------|-----|")

    for i, item in enumerate(items, start=1):
        title = item.title.replace("|", "\\|")
        authors = "; ".join(item.authors[:3])
        if len(item.authors) > 3:
            authors += " et al."
        year = item.year or ""
        doi_cell = f"[{item.doi}](https://doi.org/{item.doi})" if item.doi else ""
        lines.append(
            f"| {i} | {title} | {authors} | {year} | {item.item_type} | {doi_cell} |"
        )

    if include_notes:
        for item in items:
            if item.notes:
                lines.append(f"\n## {item.title}\n")
                for note in item.notes:
                    lines.append(f"### {note.title or 'Note'}\n")
                    lines.append(note.plain_text)
                    lines.append("")

    output = "\n".join(lines) + "\n"
    if fp is not None:
        fp.write(output)
    return output
