"""Unit tests for src/pyzot/write/recognize.py.

Uses an in-memory SQLite DB (temp file) to simulate the Zotero database.
Tests the wait_for_recognized_parent polling function.

No real Zotero process is needed — we manipulate the DB file directly to
simulate what Zotero would do when it sets a parentItemID on an attachment.
"""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from pyzot.write.recognize import wait_for_recognized_parent

# ---------------------------------------------------------------------------
# DB setup helpers
# ---------------------------------------------------------------------------

def _create_test_db(db_path: Path, has_parent: bool = False) -> None:
    """Create a minimal Zotero-shaped DB at db_path.

    If has_parent=True, the attachment already has a parentItemID set.
    """
    conn = sqlite3.connect(str(db_path))
    conn.executescript("""
        CREATE TABLE version (schema TEXT, version INTEGER);
        INSERT INTO version VALUES ('userdata', 147);

        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER DEFAULT 1,
            libraryID INTEGER DEFAULT 1,
            key TEXT,
            dateAdded TEXT DEFAULT '2023-01-01 00:00:00',
            dateModified TEXT DEFAULT '2023-01-01 00:00:00'
        );
        -- Parent item (journalArticle)
        INSERT INTO items VALUES (1, 1, 1, 'PARENTKEY', '2023-01-01', '2023-01-01');
        -- Standalone attachment
        INSERT INTO items VALUES (10, 1, 1, 'ATTKEY001', '2023-01-01', '2023-01-01');

        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        INSERT INTO fields VALUES (1, 'title');

        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        INSERT INTO itemDataValues VALUES (1, 'My Recognised Paper');

        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        INSERT INTO itemData VALUES (1, 1, 1);

        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            linkMode INTEGER DEFAULT 0,
            contentType TEXT DEFAULT 'application/pdf',
            path TEXT DEFAULT ''
        );
    """)
    if has_parent:
        conn.execute(
            "INSERT INTO itemAttachments VALUES (10, 1, 0, 'application/pdf', '')"
        )
    else:
        conn.execute(
            "INSERT INTO itemAttachments VALUES (10, NULL, 0, 'application/pdf', '')"
        )
    conn.commit()
    conn.close()


def _set_parent(db_path: Path, attachment_item_id: int, parent_item_id: int) -> None:
    """Simulate Zotero setting a parent on an attachment."""
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        "UPDATE itemAttachments SET parentItemID = ? WHERE itemID = ?",
        (parent_item_id, attachment_item_id),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Tests: parent already present
# ---------------------------------------------------------------------------

def test_parent_already_set(tmp_path: Path):
    """If parentItemID is already set, returns immediately without waiting."""
    db_path = tmp_path / "zotero.sqlite"
    _create_test_db(db_path, has_parent=True)

    start = time.monotonic()
    ref = wait_for_recognized_parent(
        db_path, "ATTKEY001", timeout_s=5.0, poll_interval_s=0.1
    )
    elapsed = time.monotonic() - start

    assert ref is not None
    assert ref.key == "PARENTKEY"
    assert ref.title == "My Recognised Paper"
    assert ref.item_id == 1
    # Should complete much faster than the timeout
    assert elapsed < 3.0


# ---------------------------------------------------------------------------
# Tests: parent appears after a short delay
# ---------------------------------------------------------------------------

def test_parent_appears_after_delay(tmp_path: Path):
    """Returns the parent ref once Zotero sets it, before the timeout."""
    db_path = tmp_path / "zotero.sqlite"
    _create_test_db(db_path, has_parent=False)

    # Set the parent after 0.3 seconds in a background thread
    def _set_after_delay():
        time.sleep(0.3)
        _set_parent(db_path, attachment_item_id=10, parent_item_id=1)

    t = threading.Thread(target=_set_after_delay, daemon=True)
    t.start()

    ref = wait_for_recognized_parent(
        db_path, "ATTKEY001", timeout_s=5.0, poll_interval_s=0.1
    )

    assert ref is not None
    assert ref.key == "PARENTKEY"
    assert ref.item_id == 1
    t.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Tests: timeout (no parent ever set)
# ---------------------------------------------------------------------------

def test_timeout_returns_none(tmp_path: Path):
    """Returns None when no parent appears within timeout_s."""
    db_path = tmp_path / "zotero.sqlite"
    _create_test_db(db_path, has_parent=False)

    start = time.monotonic()
    ref = wait_for_recognized_parent(
        db_path, "ATTKEY001", timeout_s=0.5, poll_interval_s=0.1
    )
    elapsed = time.monotonic() - start

    assert ref is None
    # Should not run much longer than timeout
    assert elapsed < 2.0


# ---------------------------------------------------------------------------
# Tests: attachment key not found (wrong key)
# ---------------------------------------------------------------------------

def test_attachment_key_not_found(tmp_path: Path):
    """Returns None if the attachment key does not exist in the DB."""
    db_path = tmp_path / "zotero.sqlite"
    _create_test_db(db_path, has_parent=True)

    ref = wait_for_recognized_parent(
        db_path, "NOEXIST1", timeout_s=0.3, poll_interval_s=0.1
    )
    assert ref is None


# ---------------------------------------------------------------------------
# Tests: missing DB file
# ---------------------------------------------------------------------------

def test_missing_db_returns_none(tmp_path: Path):
    """Returns None gracefully when the DB file does not exist."""
    db_path = tmp_path / "nonexistent.sqlite"

    ref = wait_for_recognized_parent(
        db_path, "ATTKEY001", timeout_s=0.3, poll_interval_s=0.1
    )
    assert ref is None


# ---------------------------------------------------------------------------
# Tests: DB re-opened every poll (WAL freshness)
# ---------------------------------------------------------------------------

def test_parent_visible_after_external_write(tmp_path: Path):
    """Demonstrates that the poll sees changes made by another connection."""
    db_path = tmp_path / "zotero.sqlite"
    _create_test_db(db_path, has_parent=False)

    # Use a tight loop so the test is fast: delay 0.15s, poll every 0.05s
    results = []

    def _poll():
        ref = wait_for_recognized_parent(
            db_path, "ATTKEY001", timeout_s=3.0, poll_interval_s=0.05
        )
        results.append(ref)

    t = threading.Thread(target=_poll, daemon=True)
    t.start()

    # Write the parent from the test thread after 0.15s
    time.sleep(0.15)
    _set_parent(db_path, attachment_item_id=10, parent_item_id=1)
    t.join(timeout=4.0)

    assert len(results) == 1
    assert results[0] is not None
    assert results[0].key == "PARENTKEY"
