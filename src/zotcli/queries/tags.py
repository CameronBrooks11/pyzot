"""Tag queries."""

from __future__ import annotations

from zotcli.db import ZoteroDatabase
from zotcli.models import Item
from zotcli.queries.items import _build_items


def get_all_tags(db: ZoteroDatabase) -> list[tuple[str, int]]:
    """Return (tag_name, item_count) sorted by count descending."""
    rows = db.fetchall(
        """
        SELECT t.name, COUNT(it.itemID) as cnt
        FROM tags t
        JOIN itemTags it ON t.tagID = it.tagID
        GROUP BY t.tagID, t.name
        ORDER BY cnt DESC, t.name ASC
        """
    )
    return [(r["name"], r["cnt"]) for r in rows]


def get_tags_for_item(db: ZoteroDatabase, item_id: int) -> list[str]:
    rows = db.fetchall(
        "SELECT t.name FROM itemTags it JOIN tags t ON it.tagID = t.tagID WHERE it.itemID = ?",
        (item_id,),
    )
    return [r["name"] for r in rows]


def get_items_by_tag(db: ZoteroDatabase, tag_name: str) -> list[Item]:
    rows = db.fetchall(
        """
        SELECT it.itemID FROM itemTags it
        JOIN tags t ON it.tagID = t.tagID
        WHERE t.name = ?
        """,
        (tag_name,),
    )
    return _build_items(db, [r["itemID"] for r in rows])
