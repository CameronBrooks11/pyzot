"""Direct SQLite write for collection membership.

updateSession only works for current-session items; for existing items the
only path is a direct INSERT into the collectionItems join table.

collectionItems schema: (collectionID INTEGER, itemID INTEGER, orderIndex FLOAT)
PRIMARY KEY (collectionID, itemID)

This is additive-only — no rows are deleted or updated.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


def is_item_in_collection(db, item_id: int, collection_id: int) -> bool:
    """Read-only check: return True if (collection_id, item_id) already in collectionItems."""
    row = db.fetchone(
        "SELECT 1 FROM collectionItems WHERE collectionID = ? AND itemID = ?",
        (collection_id, item_id),
    )
    return row is not None


def assign_item_to_collection(db_path: Path | str, item_id: int, collection_id: int) -> bool:
    """Insert (collection_id, item_id) into collectionItems if not already present.

    Opens the DB in write mode. Safe to call while Zotero is open — SQLite WAL
    mode allows concurrent writes; Zotero will see the change on next UI refresh.

    Returns True if the row was inserted, False if it was already present.
    """
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        # Force WAL mode to match Zotero's. Default Python sqlite3 uses
        # rollback-journal mode which is incompatible with WAL and can
        # leave a hot ``-journal`` file that blocks all subsequent reads
        # until something with write permission opens the DB.
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        cursor = conn.execute(
            "SELECT 1 FROM collectionItems WHERE collectionID = ? AND itemID = ?",
            (collection_id, item_id),
        )
        if cursor.fetchone() is not None:
            return False

        cursor = conn.execute(
            "SELECT COALESCE(MAX(orderIndex), -1) FROM collectionItems WHERE collectionID = ?",
            (collection_id,),
        )
        max_order = cursor.fetchone()[0]

        conn.execute(
            "INSERT INTO collectionItems (collectionID, itemID, orderIndex) VALUES (?, ?, ?)",
            (collection_id, item_id, max_order + 1),
        )
        conn.commit()
        return True
    finally:
        conn.close()
