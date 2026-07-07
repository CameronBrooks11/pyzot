"""Poll the read-only Zotero database for a recognised parent item.

After ``/connector/saveStandaloneAttachment`` is called, Zotero runs
``RecognizeDocument`` in the background. This module polls the read-only
SQLite database until the attachment's ``parentItemID`` is populated, then
returns an ``ItemRef`` describing the recognised parent.

The DB is re-opened on every poll to pick up changes made by Zotero (WAL
freshness: re-opening is the safest pattern for read-only cross-process
polling).
"""

from __future__ import annotations

import time
from pathlib import Path

from pyzot.write.dedup import ItemRef


# SQL: look up an attachment by its Zotero key and return parentItemID + parent title.
_ATTACHMENT_BY_KEY_SQL = """
    SELECT
        att.itemID        AS attachment_item_id,
        att.parentItemID  AS parent_item_id,
        i.key             AS parent_key,
        title_idv.value   AS parent_title
    FROM itemAttachments att
    JOIN items self_i ON att.itemID = self_i.itemID
    LEFT JOIN items i ON att.parentItemID = i.itemID
    LEFT JOIN itemData id_title ON i.itemID = id_title.itemID
    LEFT JOIN fields f_title ON id_title.fieldID = f_title.fieldID
        AND f_title.fieldName = 'title'
    LEFT JOIN itemDataValues title_idv ON id_title.valueID = title_idv.valueID
    WHERE self_i.key = ?
"""


def wait_for_recognized_parent(
    db_path: Path | str,
    attachment_key: str,
    *,
    timeout_s: float = 30.0,
    poll_interval_s: float = 1.0,
) -> ItemRef | None:
    """Poll the read-only DB until Zotero sets a parent on the attachment.

    Opens a fresh ``ZoteroDatabase`` connection on every poll so that WAL
    changes written by the running Zotero process are visible.

    Parameters
    ----------
    db_path:
        Path to ``zotero.sqlite``. Must be a valid path (not None).
    attachment_key:
        The 8-character Zotero key returned by ``saveStandaloneAttachment``.
    timeout_s:
        Maximum seconds to wait (default 30).
    poll_interval_s:
        How long to sleep between polls (default 1 second).

    Returns
    -------
    ItemRef or None
        An ``ItemRef`` for the recognised parent item, or ``None`` if no parent
        appeared within ``timeout_s`` seconds.
    """
    from pyzot.db import ZoteroDatabase

    db_path = Path(db_path)
    deadline = time.monotonic() + timeout_s

    while time.monotonic() < deadline:
        try:
            # Re-open every iteration so WAL changes are visible
            with ZoteroDatabase(db_path, warn_if_open=False) as db:
                row = db.fetchone(_ATTACHMENT_BY_KEY_SQL, (attachment_key,))
        except Exception:
            # DB temporarily locked or unavailable — wait and retry
            time.sleep(poll_interval_s)
            continue

        if row is not None and row["parent_item_id"] is not None:
            return ItemRef(
                key=row["parent_key"] or attachment_key,
                title=row["parent_title"] or "",
                item_id=row["parent_item_id"],
            )

        time.sleep(poll_interval_s)

    return None
