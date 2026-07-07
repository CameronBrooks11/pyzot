"""Item queries — the core denormalised fetch."""

from __future__ import annotations

import re
from pathlib import Path

from zotcli.db import ZoteroDatabase
from zotcli.models import Attachment, Creator, Item, Note

# SQL for fetching item fields (EAV join)
_ITEM_FIELDS_SQL = """
    SELECT i.itemID, i.key, it.typeName, i.dateAdded, i.dateModified,
           i.libraryID, f.fieldName, idv.value
    FROM items i
    JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
    LEFT JOIN itemData id ON i.itemID = id.itemID
    LEFT JOIN fields f ON id.fieldID = f.fieldID
    LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
    WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
      AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
"""

_CREATORS_SQL = """
    SELECT ic.itemID, c.creatorID, c.firstName, c.lastName,
           ct.creatorType, ic.orderIndex
    FROM itemCreators ic
    JOIN creators c ON ic.creatorID = c.creatorID
    JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
    WHERE ic.itemID IN ({placeholders})
    ORDER BY ic.itemID, ic.orderIndex
"""

_TAGS_SQL = """
    SELECT it.itemID, t.name
    FROM itemTags it
    JOIN tags t ON it.tagID = t.tagID
    WHERE it.itemID IN ({placeholders})
"""

_COLLECTIONS_SQL = """
    SELECT itemID, collectionID
    FROM collectionItems
    WHERE itemID IN ({placeholders})
"""

_ATTACHMENTS_SQL = """
    SELECT i.itemID AS att_id, i.key AS att_key,
           ia.parentItemID, ia.linkMode, ia.contentType, ia.path
    FROM itemAttachments ia
    JOIN items i ON ia.itemID = i.itemID
    WHERE ia.parentItemID IN ({placeholders})
"""

_NOTES_SQL = """
    SELECT i.itemID AS note_id, n.parentItemID, n.title, n.note
    FROM itemNotes n
    JOIN items i ON n.itemID = i.itemID
    WHERE n.parentItemID IN ({placeholders})
"""


def _chunk(lst: list, n: int = 900):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _resolve_path(att_key: str, link_mode: int, path: str | None, data_dir: Path) -> Path | None:
    """Resolve an attachment's absolute path without touching the filesystem."""
    if link_mode in (0, 1):  # imported_file / imported_url → storage/{key}/{filename}
        if path:
            filename = path.removeprefix("storage:")
            return data_dir / "storage" / att_key / filename
        # No stored path: guess by listing the storage directory
        storage_dir = data_dir / "storage" / att_key
        if storage_dir.exists():
            files = [f for f in storage_dir.iterdir() if f.is_file()]
            return files[0] if files else None
        return None
    elif link_mode == 2:  # linked_file: absolute path on disk
        return Path(path) if path else None
    # link_mode 3 = linked_url: no local file
    return None


def _build_items(db: ZoteroDatabase, item_ids: list[int]) -> list[Item]:
    """Fetch fully populated Item objects for a list of item IDs."""
    if not item_ids:
        return []

    data_dir = db.path.parent

    # Step 1: fields (EAV)
    items_map: dict[int, dict] = {}
    for chunk in _chunk(item_ids):
        ph = ",".join("?" * len(chunk))
        sql = f"{_ITEM_FIELDS_SQL} AND i.itemID IN ({ph})"
        for row in db.fetchall(sql, tuple(chunk)):
            iid = row["itemID"]
            if iid not in items_map:
                items_map[iid] = {
                    "item_id": iid,
                    "key": row["key"],
                    "item_type": row["typeName"],
                    "library_id": row["libraryID"],
                    "date_added": row["dateAdded"],
                    "date_modified": row["dateModified"],
                    "fields": {},
                }
            if row["fieldName"] and row["value"] is not None:
                items_map[iid]["fields"][row["fieldName"]] = str(row["value"])

    if not items_map:
        return []

    fetched_ids = list(items_map.keys())

    # Step 2: creators
    creators_map: dict[int, list[Creator]] = {iid: [] for iid in fetched_ids}
    for chunk in _chunk(fetched_ids):
        ph = ",".join("?" * len(chunk))
        for row in db.fetchall(_CREATORS_SQL.format(placeholders=ph), tuple(chunk)):
            creators_map[row["itemID"]].append(
                Creator(
                    creator_id=row["creatorID"],
                    first_name=row["firstName"] or "",
                    last_name=row["lastName"] or "",
                    creator_type=row["creatorType"],
                    order_index=row["orderIndex"],
                )
            )

    # Step 3: tags
    tags_map: dict[int, list[str]] = {iid: [] for iid in fetched_ids}
    for chunk in _chunk(fetched_ids):
        ph = ",".join("?" * len(chunk))
        for row in db.fetchall(_TAGS_SQL.format(placeholders=ph), tuple(chunk)):
            tags_map[row["itemID"]].append(row["name"])

    # Step 4: collection memberships
    coll_map: dict[int, list[int]] = {iid: [] for iid in fetched_ids}
    for chunk in _chunk(fetched_ids):
        ph = ",".join("?" * len(chunk))
        for row in db.fetchall(_COLLECTIONS_SQL.format(placeholders=ph), tuple(chunk)):
            coll_map[row["itemID"]].append(row["collectionID"])

    # Step 5: attachments
    att_map: dict[int, list[Attachment]] = {iid: [] for iid in fetched_ids}
    for chunk in _chunk(fetched_ids):
        ph = ",".join("?" * len(chunk))
        for row in db.fetchall(_ATTACHMENTS_SQL.format(placeholders=ph), tuple(chunk)):
            pid = row["parentItemID"]
            link_mode = row["linkMode"] if row["linkMode"] is not None else 0
            att_path = row["path"]
            abs_path = _resolve_path(row["att_key"], link_mode, att_path, data_dir)
            att_map[pid].append(
                Attachment(
                    item_id=row["att_id"],
                    key=row["att_key"],
                    parent_item_id=pid,
                    link_mode=link_mode,
                    content_type=row["contentType"] or "",
                    path=att_path,
                    absolute_path=abs_path,
                    file_exists=abs_path is not None and abs_path.exists(),
                )
            )

    # Step 6: notes
    note_map: dict[int, list[Note]] = {iid: [] for iid in fetched_ids}
    for chunk in _chunk(fetched_ids):
        ph = ",".join("?" * len(chunk))
        for row in db.fetchall(_NOTES_SQL.format(placeholders=ph), tuple(chunk)):
            pid = row["parentItemID"]
            html = row["note"] or ""
            plain = re.sub(r"<[^>]+>", "", html).strip()
            note_map[pid].append(
                Note(
                    item_id=row["note_id"],
                    parent_item_id=pid,
                    title=row["title"] or "",
                    note=html,
                    plain_text=plain,
                )
            )

    # Assemble
    results: list[Item] = []
    for iid in item_ids:
        if iid not in items_map:
            continue
        d = items_map[iid]
        results.append(
            Item(
                item_id=d["item_id"],
                key=d["key"],
                item_type=d["item_type"],
                library_id=d["library_id"],
                date_added=d["date_added"],
                date_modified=d["date_modified"],
                fields=d["fields"],
                creators=creators_map.get(iid, []),
                tags=tags_map.get(iid, []),
                collections=coll_map.get(iid, []),
                attachments=att_map.get(iid, []),
                notes=note_map.get(iid, []),
            )
        )
    return results


def get_item(db: ZoteroDatabase, item_id_or_key: int | str) -> Item | None:
    if isinstance(item_id_or_key, int):
        row = db.fetchone("SELECT itemID FROM items WHERE itemID = ?", (item_id_or_key,))
    else:
        row = db.fetchone("SELECT itemID FROM items WHERE key = ?", (item_id_or_key,))
    if row is None:
        return None
    items = _build_items(db, [row["itemID"]])
    return items[0] if items else None


def get_items(
    db: ZoteroDatabase,
    library_id: int | None = None,
    item_type: str | None = None,
    limit: int | None = None,
) -> list[Item]:
    sql = """
        SELECT i.itemID FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
    """
    params: list = []
    if library_id is not None:
        sql += " AND i.libraryID = ?"
        params.append(library_id)
    if item_type is not None:
        sql += " AND it.typeName = ?"
        params.append(item_type)
    sql += " ORDER BY i.dateAdded DESC"
    if limit is not None:
        sql += f" LIMIT {int(limit)}"

    rows = db.fetchall(sql, tuple(params))
    return _build_items(db, [r["itemID"] for r in rows])


def get_top_level_items(db: ZoteroDatabase, library_id: int | None = None) -> list[Item]:
    """Items not in any collection (top-level unfiled items)."""
    sql = """
        SELECT i.itemID FROM items i
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
          AND i.itemID NOT IN (SELECT itemID FROM collectionItems)
    """
    params: list = []
    if library_id is not None:
        sql += " AND i.libraryID = ?"
        params.append(library_id)
    rows = db.fetchall(sql, tuple(params))
    return _build_items(db, [r["itemID"] for r in rows])


def get_item_fields(db: ZoteroDatabase, item_id: int) -> dict[str, str]:
    rows = db.fetchall(
        """
        SELECT f.fieldName, idv.value
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE id.itemID = ?
        """,
        (item_id,),
    )
    return {r["fieldName"]: str(r["value"]) for r in rows}


def get_item_creators(db: ZoteroDatabase, item_id: int) -> list[Creator]:
    rows = db.fetchall(
        """
        SELECT c.creatorID, c.firstName, c.lastName, ct.creatorType, ic.orderIndex
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
        WHERE ic.itemID = ?
        ORDER BY ic.orderIndex
        """,
        (item_id,),
    )
    return [
        Creator(
            creator_id=r["creatorID"],
            first_name=r["firstName"] or "",
            last_name=r["lastName"] or "",
            creator_type=r["creatorType"],
            order_index=r["orderIndex"],
        )
        for r in rows
    ]


def get_item_tags(db: ZoteroDatabase, item_id: int) -> list[str]:
    rows = db.fetchall(
        "SELECT t.name FROM itemTags it JOIN tags t ON it.tagID = t.tagID WHERE it.itemID = ?",
        (item_id,),
    )
    return [r["name"] for r in rows]
