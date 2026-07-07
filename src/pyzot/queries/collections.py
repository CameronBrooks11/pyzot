"""Collection queries."""

from __future__ import annotations

from pyzot.db import ZoteroDatabase
from pyzot.models import Collection, Item
from pyzot.queries.items import _build_items


def get_all_collections(db: ZoteroDatabase, library_id: int | None = None) -> list[Collection]:
    sql = """
        SELECT c.collectionID, c.key, c.collectionName, c.parentCollectionID, c.libraryID
        FROM collections c
    """
    params: tuple = ()
    if library_id is not None:
        sql += " WHERE c.libraryID = ?"
        params = (library_id,)
    sql += " ORDER BY c.collectionName"

    rows = db.fetchall(sql, params)
    cols = [
        Collection(
            collection_id=r["collectionID"],
            key=r["key"],
            name=r["collectionName"],
            parent_collection_id=r["parentCollectionID"],
            library_id=r["libraryID"],
        )
        for r in rows
    ]
    # Attach item counts
    count_rows = db.fetchall(
        "SELECT collectionID, COUNT(*) as cnt FROM collectionItems GROUP BY collectionID"
    )
    count_map = {r["collectionID"]: r["cnt"] for r in count_rows}
    for c in cols:
        c.item_count = count_map.get(c.collection_id, 0)
    return cols


def get_collection_tree(db: ZoteroDatabase, library_id: int | None = None) -> list[Collection]:
    """Return root-level collections with children nested recursively."""
    all_cols = get_all_collections(db, library_id)
    by_id = {c.collection_id: c for c in all_cols}
    roots: list[Collection] = []
    for c in all_cols:
        if c.parent_collection_id is None:
            roots.append(c)
        elif c.parent_collection_id in by_id:
            by_id[c.parent_collection_id].children.append(c)
    return roots


def get_collection_by_id(db: ZoteroDatabase, collection_id: int) -> Collection | None:
    row = db.fetchone(
        "SELECT collectionID, key, collectionName, parentCollectionID, libraryID "
        "FROM collections WHERE collectionID = ?",
        (collection_id,),
    )
    if row is None:
        return None
    return Collection(
        collection_id=row["collectionID"],
        key=row["key"],
        name=row["collectionName"],
        parent_collection_id=row["parentCollectionID"],
        library_id=row["libraryID"],
    )


def get_collection_by_name(
    db: ZoteroDatabase, name: str, fuzzy: bool = False
) -> list[Collection]:
    if fuzzy:
        rows = db.fetchall(
            "SELECT collectionID, key, collectionName, parentCollectionID, libraryID "
            "FROM collections WHERE collectionName LIKE ?",
            (f"%{name}%",),
        )
    else:
        rows = db.fetchall(
            "SELECT collectionID, key, collectionName, parentCollectionID, libraryID "
            "FROM collections WHERE collectionName = ?",
            (name,),
        )
    return [
        Collection(
            collection_id=r["collectionID"],
            key=r["key"],
            name=r["collectionName"],
            parent_collection_id=r["parentCollectionID"],
            library_id=r["libraryID"],
        )
        for r in rows
    ]


def get_items_in_collection(
    db: ZoteroDatabase, collection_id: int, recursive: bool = False
) -> list[Item]:
    if recursive:
        # Gather all descendant collection IDs first
        col_ids = _collect_descendant_ids(db, collection_id)
        col_ids.add(collection_id)
        placeholders = ",".join("?" * len(col_ids))
        item_ids = [
            r["itemID"]
            for r in db.fetchall(
                f"SELECT DISTINCT itemID FROM collectionItems WHERE collectionID IN ({placeholders})",
                tuple(col_ids),
            )
        ]
    else:
        item_ids = [
            r["itemID"]
            for r in db.fetchall(
                "SELECT itemID FROM collectionItems WHERE collectionID = ?",
                (collection_id,),
            )
        ]

    if not item_ids:
        return []
    return _build_items(db, item_ids)


def _collect_descendant_ids(db: ZoteroDatabase, parent_id: int) -> set[int]:
    ids: set[int] = set()
    rows = db.fetchall(
        "SELECT collectionID FROM collections WHERE parentCollectionID = ?", (parent_id,)
    )
    for r in rows:
        child_id = r["collectionID"]
        ids.add(child_id)
        ids.update(_collect_descendant_ids(db, child_id))
    return ids
