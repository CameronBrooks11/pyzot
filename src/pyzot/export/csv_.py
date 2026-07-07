"""CSV export — one row per item, creators flattened."""

from __future__ import annotations

import csv
import io
from typing import IO

from pyzot.models import Item

_MAX_AUTHORS = 5


def items_to_csv(items: list[Item], fp: IO[str] | None = None) -> str:
    buf = fp or io.StringIO()

    fieldnames = [
        "item_id",
        "key",
        "item_type",
        "title",
        "year",
        "doi",
        "journal",
        "publisher",
        "place",
        "volume",
        "issue",
        "pages",
        "date_added",
        "date_modified",
    ]
    for i in range(1, _MAX_AUTHORS + 1):
        fieldnames.append(f"author_{i}")
    fieldnames.append("tags")
    fieldnames.append("collections")

    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()

    for item in items:
        row: dict = {
            "item_id": item.item_id,
            "key": item.key,
            "item_type": item.item_type,
            "title": item.title,
            "year": item.year or "",
            "doi": item.doi or "",
            "journal": item.fields.get("publicationTitle", ""),
            "publisher": item.fields.get("publisher", ""),
            "place": item.fields.get("place", ""),
            "volume": item.fields.get("volume", ""),
            "issue": item.fields.get("issue", ""),
            "pages": item.fields.get("pages", ""),
            "date_added": str(item.date_added),
            "date_modified": str(item.date_modified),
            "tags": "; ".join(item.tags),
            "collections": "; ".join(str(c) for c in item.collections),
        }
        for i, author in enumerate(item.authors[:_MAX_AUTHORS], start=1):
            row[f"author_{i}"] = author
        writer.writerow(row)

    result = buf.getvalue() if isinstance(buf, io.StringIO) else ""
    return result
