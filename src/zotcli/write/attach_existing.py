"""Attach a local file to an existing Zotero item via direct SQLite+filesystem.

Background
----------
Zotero's connector API (``/connector/saveAttachment``) is session-bound — it
only attaches files to items saved in the same connector session. There is
**no connector or local-API endpoint** that attaches an arbitrary file to an
arbitrary pre-existing item.

This module is therefore the second exception to zotcli's "no direct SQLite
writes for item data" rule (the first being :mod:`zotcli.write.collection_assign`).
It mirrors what Zotero itself does when ``Find Available PDFs`` adds a file:

  1. Generate a new 8-character Zotero key (alphabet matches Zotero's own).
  2. ``INSERT`` an ``items`` row with itemTypeID=3 (attachment).
  3. ``INSERT`` an ``itemAttachments`` row with linkMode=1 (imported_file)
     and path ``storage:<filename>``.
  4. ``INSERT`` an ``itemDataValues`` + ``itemData`` row for the title field.
  5. Copy the file to ``<zotero-data-dir>/storage/<key>/<filename>``.
  6. Set the parent item's ``synced=0`` so Zotero's sync engine notices.

Safety
------
- Designed to run while Zotero is open (WAL mode tolerates concurrent reads).
- Idempotency: if a file with the same name already exists under the same
  parent, the existing attachment key is returned without inserting again.
- All writes happen in a single SQLite transaction.
- On any exception, the transaction rolls back and the copied file is
  removed (best-effort).

After a successful attach, Zotero picks up the new attachment on its next
UI refresh and queues it for background full-text indexing automatically.
"""

from __future__ import annotations

import logging
import random
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("zotcli.attach_existing")

# Zotero's object-key alphabet (per dataObjectUtilities.js):
# 33 characters, omitting 0/1/O to avoid visual confusion in 8-char keys.
_KEY_ALPHABET = "23456789ABCDEFGHIJKLMNPQRSTUVWXYZ"
_KEY_LENGTH = 8

# Zotero itemType ID for attachments (verified against current schema)
_ATTACHMENT_ITEM_TYPE_ID = 3

# Zotero linkMode values
LINK_MODE_IMPORTED_FILE = 1
LINK_MODE_IMPORTED_URL = 0
LINK_MODE_LINKED_FILE = 2
LINK_MODE_LINKED_URL = 3

# Sync state for new attachments (TO_PROCESS — Zotero will pick up and process)
_SYNC_STATE_TO_PROCESS = 1


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AttachResult:
    """Outcome of a successful attach operation."""

    attachment_key: str
    attachment_item_id: int
    parent_item_id: int
    parent_key: str
    stored_path: Path
    title: str
    inserted: bool  # False if returned an existing matching attachment


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def attach_to_existing(
    *,
    db_path: Path | str,
    data_dir: Path | str,
    parent_key: str,
    source_file: Path | str,
    title: str | None = None,
    content_type: str | None = None,
    source_url: str | None = None,
    library_id: int = 1,
) -> AttachResult:
    """Attach *source_file* as a child of the item with key *parent_key*.

    Parameters
    ----------
    db_path:
        Path to ``zotero.sqlite``.
    data_dir:
        Path to the Zotero data directory (parent of ``storage/``).
        Usually the same directory that contains ``zotero.sqlite``.
    parent_key:
        8-character Zotero key of the parent item.
    source_file:
        Local PDF/EPUB/etc. file to attach. It is COPIED into Zotero's
        storage directory — the original is left untouched.
    title:
        Display title for the attachment. Defaults to source_file.stem.
    content_type:
        MIME type. Auto-sniffed from magic bytes if not given.
    source_url:
        Optional URL recorded as the attachment's provenance (Zotero's
        ``url`` field on the attachment item).
    library_id:
        Zotero library ID. Default 1 (personal library).

    Returns
    -------
    AttachResult
        Includes the new attachment key, parent item info, and the storage path.

    Raises
    ------
    ValueError
        If the parent key is not found or the source file is unreadable.
    sqlite3.Error
        If the SQLite write fails (transaction is rolled back automatically).
    """
    db_path = Path(db_path)
    data_dir = Path(data_dir)
    source_file = Path(source_file)

    if not source_file.is_file():
        raise ValueError(f"Source file does not exist or is not a regular file: {source_file}")

    if content_type is None:
        from zotcli.write.pdf import sniff_mime
        content_type = sniff_mime(source_file) or "application/octet-stream"

    if title is None:
        title = source_file.stem

    # --- Pre-flight: look up parent itemID ---
    # Zotero uses WAL journal mode. If we connect with Python's default
    # rollback-journal mode and crash mid-transaction, the hot ``-journal``
    # file is incompatible with Zotero's WAL state and blocks ALL further
    # reads until something with write permission opens the DB and rolls
    # the journal back. Force WAL on every connection to avoid this.
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except sqlite3.Error as exc:
        logger.warning("Could not set WAL pragmas: %s", exc)
    try:
        cur = conn.execute(
            "SELECT itemID, libraryID FROM items WHERE key = ? AND libraryID = ?",
            (parent_key, library_id),
        )
        row = cur.fetchone()
        if row is None:
            raise ValueError(
                f"Parent item not found: key={parent_key!r} library={library_id}"
            )
        parent_item_id, parent_lib = row[0], row[1]

        # --- Idempotency: check for an existing attachment with the same filename ---
        existing_key = _find_existing_attachment(
            conn, parent_item_id, source_file.name, content_type
        )
        if existing_key is not None:
            storage = _storage_path(data_dir, existing_key) / source_file.name
            cur = conn.execute(
                "SELECT itemID FROM items WHERE key = ?",
                (existing_key,),
            )
            att_id = cur.fetchone()[0]
            logger.info("Attachment %s already exists for %s; skipping insert", existing_key, parent_key)
            return AttachResult(
                attachment_key=existing_key,
                attachment_item_id=att_id,
                parent_item_id=parent_item_id,
                parent_key=parent_key,
                stored_path=storage,
                title=title,
                inserted=False,
            )

        # --- Generate a unique key ---
        new_key = _generate_unique_key(conn, parent_lib)

        # --- Storage dir + file copy (do this first so we can rollback on copy failure) ---
        storage_dir = _storage_path(data_dir, new_key)
        storage_dir.mkdir(parents=True, exist_ok=True)
        dest_path = storage_dir / source_file.name
        try:
            shutil.copy2(str(source_file), str(dest_path))
        except Exception:
            # Cleanup partial directory and re-raise
            try:
                if dest_path.exists():
                    dest_path.unlink()
                if storage_dir.exists() and not any(storage_dir.iterdir()):
                    storage_dir.rmdir()
            except Exception:
                pass
            raise

        # --- DB inserts inside a single transaction ---
        try:
            with conn:
                now_iso = datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")

                # 1) items row
                conn.execute(
                    "INSERT INTO items "
                    "(itemTypeID, dateAdded, dateModified, clientDateModified, libraryID, key, version, synced) "
                    "VALUES (?, ?, ?, ?, ?, ?, 0, 0)",
                    (_ATTACHMENT_ITEM_TYPE_ID, now_iso, now_iso, now_iso, parent_lib, new_key),
                )
                att_item_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

                # 2) itemAttachments row
                conn.execute(
                    "INSERT INTO itemAttachments "
                    "(itemID, parentItemID, linkMode, contentType, path, syncState) "
                    "VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        att_item_id,
                        parent_item_id,
                        LINK_MODE_IMPORTED_FILE,
                        content_type,
                        f"storage:{source_file.name}",
                        _SYNC_STATE_TO_PROCESS,
                    ),
                )

                # 3) title field on the attachment
                _set_item_field(conn, att_item_id, "title", title)

                # 4) Optional URL provenance
                if source_url:
                    _set_item_field(conn, att_item_id, "url", source_url)

                # 5) Mark parent unsynced so Zotero's sync engine re-uploads it
                conn.execute(
                    "UPDATE items SET synced = 0, dateModified = ?, clientDateModified = ? "
                    "WHERE itemID = ?",
                    (now_iso, now_iso, parent_item_id),
                )

                logger.info(
                    "Attached %s (%d bytes) to %s as %s",
                    source_file.name, source_file.stat().st_size, parent_key, new_key,
                )

            return AttachResult(
                attachment_key=new_key,
                attachment_item_id=att_item_id,
                parent_item_id=parent_item_id,
                parent_key=parent_key,
                stored_path=dest_path,
                title=title,
                inserted=True,
            )
        except Exception:
            # Roll back the file copy too
            try:
                if dest_path.exists():
                    dest_path.unlink()
                if storage_dir.exists() and not any(storage_dir.iterdir()):
                    storage_dir.rmdir()
            except Exception:
                pass
            raise
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------

def _generate_key(rng: random.Random | None = None) -> str:
    """Return a fresh 8-char Zotero object key."""
    r = rng or random
    return "".join(r.choice(_KEY_ALPHABET) for _ in range(_KEY_LENGTH))


def _generate_unique_key(conn: sqlite3.Connection, library_id: int) -> str:
    """Pick a random key that isn't already used in *library_id*.

    Collision probability is ~1 in 33^8 = ~1.4e12, so a single attempt
    almost always succeeds; we cap retries at 16.
    """
    for _ in range(16):
        candidate = _generate_key()
        cur = conn.execute(
            "SELECT 1 FROM items WHERE libraryID = ? AND key = ?",
            (library_id, candidate),
        )
        if cur.fetchone() is None:
            return candidate
    raise RuntimeError("Could not generate a unique Zotero key after 16 attempts")


def _storage_path(data_dir: Path, key: str) -> Path:
    """Return the storage directory for an attachment key."""
    return data_dir / "storage" / key


def _find_existing_attachment(
    conn: sqlite3.Connection,
    parent_item_id: int,
    filename: str,
    content_type: str,
) -> str | None:
    """Return the key of an existing child attachment matching *filename*, or None."""
    cur = conn.execute(
        """
        SELECT i.key
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID = ?
          AND ia.path = ?
          AND COALESCE(ia.contentType, '') = ?
        LIMIT 1
        """,
        (parent_item_id, f"storage:{filename}", content_type),
    )
    row = cur.fetchone()
    return row[0] if row else None


def _set_item_field(conn: sqlite3.Connection, item_id: int, field_name: str, value: str) -> None:
    """Set a single field on an item via the itemData / itemDataValues join.

    Handles both the data-value de-duplication (``itemDataValues``) and the
    field-to-value link (``itemData``).
    """
    # Look up fieldID
    cur = conn.execute("SELECT fieldID FROM fields WHERE fieldName = ?", (field_name,))
    row = cur.fetchone()
    if row is None:
        # Unknown field — skip silently rather than fail the whole insert
        logger.debug("Field %r not in schema; skipping", field_name)
        return
    field_id = row[0]

    # Intern the value in itemDataValues
    cur = conn.execute("SELECT valueID FROM itemDataValues WHERE value = ?", (value,))
    row = cur.fetchone()
    if row is None:
        conn.execute("INSERT INTO itemDataValues (value) VALUES (?)", (value,))
        value_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    else:
        value_id = row[0]

    # Link
    conn.execute(
        "INSERT OR REPLACE INTO itemData (itemID, fieldID, valueID) VALUES (?, ?, ?)",
        (item_id, field_id, value_id),
    )
