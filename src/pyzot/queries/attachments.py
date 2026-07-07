"""Attachment queries and path resolution."""

from __future__ import annotations

from pathlib import Path

from pyzot.db import ZoteroDatabase
from pyzot.models import Attachment, Item
from pyzot.queries.items import _build_items


def get_attachments_for_item(db: ZoteroDatabase, parent_item_id: int) -> list[Attachment]:
    rows = db.fetchall(
        """
        SELECT i.itemID, i.key, ia.parentItemID, ia.linkMode,
               ia.contentType, ia.path
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID = ?
        """,
        (parent_item_id,),
    )
    return [
        Attachment(
            item_id=r["itemID"],
            key=r["key"],
            parent_item_id=r["parentItemID"],
            link_mode=r["linkMode"] if r["linkMode"] is not None else 0,
            content_type=r["contentType"] or "",
            path=r["path"],
        )
        for r in rows
    ]


def resolve_attachment_path(
    attachment: Attachment, data_dir: Path
) -> Path | None:
    """Resolve the absolute path of an attachment file."""
    if attachment.link_mode == 0:  # imported_file: storage/{key}/{filename}
        if attachment.path:
            # Zotero stores "storage:filename" for imported files
            filename = attachment.path.removeprefix("storage:")
            p = data_dir / "storage" / attachment.key / filename
        else:
            # Try to find any file under the storage key directory
            storage_dir = data_dir / "storage" / attachment.key
            if storage_dir.exists():
                files = list(storage_dir.iterdir())
                return files[0] if files else None
            return None
        return p
    elif attachment.link_mode == 2:  # linked_file: absolute path
        if attachment.path:
            return Path(attachment.path)
    elif attachment.link_mode == 1:  # imported_url: same as imported_file
        if attachment.path:
            filename = attachment.path.removeprefix("storage:")
            return data_dir / "storage" / attachment.key / filename
    # linked_url (3) has no local file
    return None


def enrich_attachment_paths(
    attachments: list[Attachment], data_dir: Path
) -> list[Attachment]:
    """Resolve and check existence of attachment paths in place."""
    for att in attachments:
        p = resolve_attachment_path(att, data_dir)
        att.absolute_path = p
        att.file_exists = p is not None and p.exists()
    return attachments


def get_all_pdfs(db: ZoteroDatabase, data_dir: Path) -> list[tuple[Item, Attachment]]:
    """Return all (item, attachment) pairs where the attachment is a PDF."""
    rows = db.fetchall(
        """
        SELECT ia.parentItemID, i.itemID, i.key, ia.linkMode,
               ia.contentType, ia.path
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE LOWER(ia.contentType) = 'application/pdf'
          AND ia.parentItemID IS NOT NULL
        """
    )
    # Group by parent item
    from collections import defaultdict
    parent_ids: list[int] = []
    att_by_parent: dict[int, list[Attachment]] = defaultdict(list)
    for r in rows:
        parent_id = r["parentItemID"]
        att = Attachment(
            item_id=r["itemID"],
            key=r["key"],
            parent_item_id=parent_id,
            link_mode=r["linkMode"] if r["linkMode"] is not None else 0,
            content_type=r["contentType"] or "",
            path=r["path"],
        )
        p = resolve_attachment_path(att, data_dir)
        att.absolute_path = p
        att.file_exists = p is not None and p.exists()
        att_by_parent[parent_id].append(att)
        if parent_id not in parent_ids:
            parent_ids.append(parent_id)

    items = {item.item_id: item for item in _build_items(db, parent_ids)}
    result: list[tuple[Item, Attachment]] = []
    for pid in parent_ids:
        item = items.get(pid)
        if item:
            for att in att_by_parent[pid]:
                result.append((item, att))
    return result
