"""Unit tests for pyzot.write.attach_existing.

The DB tests run against a fresh in-memory-style SQLite file with a minimal
Zotero schema — they do not touch the user's real Zotero library.
"""

from __future__ import annotations

import sqlite3

import pytest

_MIN_SCHEMA = """
CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT);

CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
INSERT INTO itemTypes VALUES (1, 'book'), (2, 'journalArticle'), (3, 'attachment');

CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
INSERT INTO fields VALUES (1, 'title'), (2, 'url');

CREATE TABLE items (
    itemID INTEGER PRIMARY KEY,
    itemTypeID INT NOT NULL,
    dateAdded TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    dateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    clientDateModified TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    libraryID INT NOT NULL,
    key TEXT NOT NULL,
    version INT NOT NULL DEFAULT 0,
    synced INT NOT NULL DEFAULT 0,
    UNIQUE (libraryID, key)
);

CREATE TABLE itemAttachments (
    itemID INTEGER PRIMARY KEY,
    parentItemID INT,
    linkMode INT,
    contentType TEXT,
    charsetID INT,
    path TEXT,
    syncState INT DEFAULT 0,
    storageModTime INT,
    storageHash TEXT,
    lastProcessedModificationTime INT,
    lastRead INT,
    FOREIGN KEY (itemID) REFERENCES items(itemID) ON DELETE CASCADE,
    FOREIGN KEY (parentItemID) REFERENCES items(itemID) ON DELETE CASCADE
);

CREATE TABLE itemDataValues (
    valueID INTEGER PRIMARY KEY,
    value TEXT UNIQUE
);

CREATE TABLE itemData (
    itemID INT,
    fieldID INT,
    valueID INT,
    PRIMARY KEY (itemID, fieldID)
);
"""


@pytest.fixture
def fixture_zotero(tmp_path):
    """Create a tiny DB + storage layout with one parent item, returns (db_path, data_dir, parent_key)."""
    data_dir = tmp_path / "Zotero"
    storage_dir = data_dir / "storage"
    storage_dir.mkdir(parents=True)
    db_path = data_dir / "zotero.sqlite"

    conn = sqlite3.connect(str(db_path))
    try:
        conn.executescript(_MIN_SCHEMA)
        conn.execute("INSERT INTO libraries (libraryID, type) VALUES (1, 'user')")
        conn.execute(
            "INSERT INTO items (itemID, itemTypeID, libraryID, key) VALUES (?, ?, ?, ?)",
            (100, 2, 1, "PARENT01"),
        )
        conn.commit()
    finally:
        conn.close()

    return db_path, data_dir, "PARENT01"


def test_generate_key_correct_alphabet_and_length():
    from pyzot.write.attach_existing import _KEY_ALPHABET, _KEY_LENGTH, _generate_key

    for _ in range(20):
        k = _generate_key()
        assert len(k) == _KEY_LENGTH
        assert all(c in _KEY_ALPHABET for c in k)


def test_attach_to_existing_inserts_rows_and_copies_file(fixture_zotero, tmp_path):
    from pyzot.write.attach_existing import attach_to_existing

    db_path, data_dir, parent_key = fixture_zotero
    src = tmp_path / "sample.pdf"
    src.write_bytes(b"%PDF-1.4\nfake pdf content")

    result = attach_to_existing(
        db_path=db_path,
        data_dir=data_dir,
        parent_key=parent_key,
        source_file=src,
        title="My Test Title",
        source_url="https://example.org/sample.pdf",
    )

    assert result.inserted is True
    assert result.parent_key == parent_key
    assert result.stored_path.exists()
    assert result.stored_path.read_bytes() == src.read_bytes()

    # Verify DB state
    conn = sqlite3.connect(str(db_path))
    try:
        att = conn.execute(
            "SELECT i.key, i.itemTypeID, ia.parentItemID, ia.contentType, ia.path, ia.linkMode "
            "FROM items i JOIN itemAttachments ia ON i.itemID = ia.itemID "
            "WHERE i.key = ?",
            (result.attachment_key,),
        ).fetchone()
        assert att is not None
        assert att[1] == 3  # itemTypeID for attachment
        assert att[2] == 100  # parentItemID
        assert att[3] == "application/pdf"
        assert att[4] == "storage:sample.pdf"
        assert att[5] == 1  # imported_file

        title_row = conn.execute(
            "SELECT v.value FROM itemData d "
            "JOIN itemDataValues v ON d.valueID = v.valueID "
            "JOIN items i ON i.itemID = d.itemID "
            "JOIN fields f ON f.fieldID = d.fieldID "
            "WHERE i.key = ? AND f.fieldName = 'title'",
            (result.attachment_key,),
        ).fetchone()
        assert title_row is not None
        assert title_row[0] == "My Test Title"

        url_row = conn.execute(
            "SELECT v.value FROM itemData d "
            "JOIN itemDataValues v ON d.valueID = v.valueID "
            "JOIN items i ON i.itemID = d.itemID "
            "JOIN fields f ON f.fieldID = d.fieldID "
            "WHERE i.key = ? AND f.fieldName = 'url'",
            (result.attachment_key,),
        ).fetchone()
        assert url_row[0] == "https://example.org/sample.pdf"

        # Parent should be marked unsynced
        synced = conn.execute("SELECT synced FROM items WHERE key = ?", (parent_key,)).fetchone()[0]
        assert synced == 0
    finally:
        conn.close()


def test_attach_idempotent_when_same_filename(fixture_zotero, tmp_path):
    """Calling attach with the same filename twice returns the existing key."""
    from pyzot.write.attach_existing import attach_to_existing

    db_path, data_dir, parent_key = fixture_zotero
    src = tmp_path / "twin.pdf"
    src.write_bytes(b"%PDF-1.4\nfoo")
    r1 = attach_to_existing(
        db_path=db_path,
        data_dir=data_dir,
        parent_key=parent_key,
        source_file=src,
    )
    r2 = attach_to_existing(
        db_path=db_path,
        data_dir=data_dir,
        parent_key=parent_key,
        source_file=src,
    )
    assert r1.inserted is True
    assert r2.inserted is False
    assert r1.attachment_key == r2.attachment_key


def test_attach_raises_when_parent_missing(fixture_zotero, tmp_path):
    from pyzot.write.attach_existing import attach_to_existing

    db_path, data_dir, _ = fixture_zotero
    src = tmp_path / "x.pdf"
    src.write_bytes(b"%PDF-1.4\n")
    with pytest.raises(ValueError, match="Parent item not found"):
        attach_to_existing(
            db_path=db_path,
            data_dir=data_dir,
            parent_key="DOESNTEXIST",
            source_file=src,
        )


def test_attach_raises_when_source_missing(fixture_zotero, tmp_path):
    from pyzot.write.attach_existing import attach_to_existing

    db_path, data_dir, parent_key = fixture_zotero
    with pytest.raises(ValueError, match="Source file does not exist"):
        attach_to_existing(
            db_path=db_path,
            data_dir=data_dir,
            parent_key=parent_key,
            source_file=tmp_path / "nope.pdf",
        )
