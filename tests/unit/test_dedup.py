"""Tests for src/pyzot/write/dedup.py.

Uses the in-memory DB fixture from tests/conftest.py.
The seeded DB has:
  item 1: key=AABB0001, DOI=10.1038/example, title="Deep Learning for NLP"
  item 2: key=CCDD0002, ISBN field not seeded (we'll patch as needed)
  item 3: key=EEFF0003, no DOI

We add Extra-field rows for PMID and arXiv tests.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from pyzot.db import ZoteroDatabase
from pyzot.write.dedup import ItemRef, find_by_arxiv, find_by_doi, find_by_isbn, find_by_pmid

# ---------------------------------------------------------------------------
# Helpers to extend the seeded DB
# ---------------------------------------------------------------------------


def _add_doi_to_item(db_path: Path, item_id: int, doi: str) -> None:
    """Add a DOI field row to the seeded DB for testing."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT OR IGNORE INTO fields VALUES (4, 'DOI')")
    # Get a new valueID
    row = conn.execute("SELECT MAX(valueID) FROM itemDataValues").fetchone()
    vid = (row[0] or 0) + 1
    conn.execute("INSERT INTO itemDataValues VALUES (?, ?)", (vid, doi))
    conn.execute("INSERT INTO itemData VALUES (?, 4, ?)", (item_id, vid))
    conn.commit()
    conn.close()


def _add_isbn_to_item(db_path: Path, item_id: int, isbn: str) -> None:
    """Add an ISBN field row to the seeded DB."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT OR IGNORE INTO fields VALUES (6, 'ISBN')")
    row = conn.execute("SELECT MAX(valueID) FROM itemDataValues").fetchone()
    vid = (row[0] or 0) + 1
    conn.execute("INSERT INTO itemDataValues VALUES (?, ?)", (vid, isbn))
    conn.execute("INSERT INTO itemData VALUES (?, 6, ?)", (item_id, vid))
    conn.commit()
    conn.close()


def _add_extra_to_item(db_path: Path, item_id: int, extra: str) -> None:
    """Add an 'extra' field row to the seeded DB."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("INSERT OR IGNORE INTO fields VALUES (7, 'extra')")
    row = conn.execute("SELECT MAX(valueID) FROM itemDataValues").fetchone()
    vid = (row[0] or 0) + 1
    conn.execute("INSERT INTO itemDataValues VALUES (?, ?)", (vid, extra))
    conn.execute("INSERT INTO itemData VALUES (?, 7, ?)", (item_id, vid))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# find_by_doi
# ---------------------------------------------------------------------------


class TestFindByDOI:
    def test_found_exact(self, db, tmp_path):
        """Should find item 1 which has DOI 10.1038/example in the seeded DB."""
        result = find_by_doi(db, "10.1038/example")
        assert result is not None
        assert isinstance(result, ItemRef)
        assert result.key == "AABB0001"
        assert result.item_id == 1

    def test_found_case_insensitive(self, db):
        """DOI lookup is case-insensitive."""
        result = find_by_doi(db, "10.1038/EXAMPLE")
        assert result is not None
        assert result.key == "AABB0001"

    def test_not_found(self, db):
        """Returns None when no item has the given DOI."""
        result = find_by_doi(db, "10.9999/nonexistent")
        assert result is None

    def test_itemref_has_title(self, db):
        """ItemRef.title is populated from the title field."""
        result = find_by_doi(db, "10.1038/example")
        assert result is not None
        assert "Deep Learning" in result.title


# ---------------------------------------------------------------------------
# find_by_arxiv
# ---------------------------------------------------------------------------


class TestFindByArXiv:
    def test_found_in_extra(self, tmp_path):
        """Should find an item that has arXiv ID in the extra field."""
        # Create a new DB with the extra field populated
        db_path = tmp_path / "zotero.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE version (schema TEXT, version INTEGER);
            INSERT INTO version VALUES ('userdata', 147);
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
            INSERT INTO libraries VALUES (1, 'user', 1);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            INSERT INTO itemTypes VALUES (5, 'preprint');
            CREATE TABLE items (
                itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER DEFAULT 1,
                key TEXT, dateAdded TEXT, dateModified TEXT
            );
            INSERT INTO items VALUES (20, 5, 1, 'PRNT0001', '2024-01-01 00:00:00', '2024-01-01 00:00:00');
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO fields VALUES (7, 'extra');
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO itemDataValues VALUES (100, 'Attention Is All You Need');
            INSERT INTO itemDataValues VALUES (101, 'arXiv: 1706.03762\narchive ID: 1706.03762');
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            INSERT INTO itemData VALUES (20, 1, 100);
            INSERT INTO itemData VALUES (20, 7, 101);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, note TEXT, title TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, libraryID INTEGER DEFAULT 1, key TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        """)
        conn.commit()
        conn.close()

        arxiv_db = ZoteroDatabase(db_path, warn_if_open=False)
        result = find_by_arxiv(arxiv_db, "1706.03762")
        assert result is not None
        assert result.key == "PRNT0001"

    def test_not_found(self, db):
        """Returns None when no item has the given arXiv ID."""
        result = find_by_arxiv(db, "9999.99999")
        assert result is None

    def test_version_stripped_for_match(self, tmp_path):
        """arXiv ID with version suffix still matches the base ID."""
        db_path = tmp_path / "zotero.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE version (schema TEXT, version INTEGER);
            INSERT INTO version VALUES ('userdata', 147);
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
            INSERT INTO libraries VALUES (1, 'user', 1);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            INSERT INTO itemTypes VALUES (5, 'preprint');
            CREATE TABLE items (
                itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER DEFAULT 1,
                key TEXT, dateAdded TEXT, dateModified TEXT
            );
            INSERT INTO items VALUES (21, 5, 1, 'PRNT0002', '2024-01-01 00:00:00', '2024-01-01 00:00:00');
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO fields VALUES (7, 'extra');
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO itemDataValues VALUES (200, 'Some Preprint');
            INSERT INTO itemDataValues VALUES (201, 'arXiv: 2401.12345');
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            INSERT INTO itemData VALUES (21, 1, 200);
            INSERT INTO itemData VALUES (21, 7, 201);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, note TEXT, title TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, libraryID INTEGER DEFAULT 1, key TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        """)
        conn.commit()
        conn.close()
        arxiv_db = ZoteroDatabase(db_path, warn_if_open=False)
        # Query with version suffix — should still match
        result = find_by_arxiv(arxiv_db, "2401.12345v2")
        assert result is not None
        assert result.key == "PRNT0002"


# ---------------------------------------------------------------------------
# find_by_pmid
# ---------------------------------------------------------------------------


class TestFindByPMID:
    def test_found(self, tmp_path):
        """Should find an item with PMID in extra field."""
        db_path = tmp_path / "zotero.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE version (schema TEXT, version INTEGER);
            INSERT INTO version VALUES ('userdata', 147);
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
            INSERT INTO libraries VALUES (1, 'user', 1);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            INSERT INTO itemTypes VALUES (1, 'journalArticle');
            CREATE TABLE items (
                itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER DEFAULT 1,
                key TEXT, dateAdded TEXT, dateModified TEXT
            );
            INSERT INTO items VALUES (30, 1, 1, 'JOURN001', '2024-01-01 00:00:00', '2024-01-01 00:00:00');
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO fields VALUES (7, 'extra');
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO itemDataValues VALUES (300, 'Some Journal Article');
            INSERT INTO itemDataValues VALUES (301, 'PMID: 31452104');
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            INSERT INTO itemData VALUES (30, 1, 300);
            INSERT INTO itemData VALUES (30, 7, 301);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, note TEXT, title TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, libraryID INTEGER DEFAULT 1, key TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        """)
        conn.commit()
        conn.close()
        pmid_db = ZoteroDatabase(db_path, warn_if_open=False)
        result = find_by_pmid(pmid_db, "31452104")
        assert result is not None
        assert result.key == "JOURN001"

    def test_not_found(self, db):
        result = find_by_pmid(db, "99999999")
        assert result is None


# ---------------------------------------------------------------------------
# find_by_isbn
# ---------------------------------------------------------------------------


class TestFindByISBN:
    def test_found_exact(self, tmp_path):
        """Should find a book item with a matching ISBN."""
        db_path = tmp_path / "zotero.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE version (schema TEXT, version INTEGER);
            INSERT INTO version VALUES ('userdata', 147);
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
            INSERT INTO libraries VALUES (1, 'user', 1);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            INSERT INTO itemTypes VALUES (2, 'book');
            CREATE TABLE items (
                itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER DEFAULT 1,
                key TEXT, dateAdded TEXT, dateModified TEXT
            );
            INSERT INTO items VALUES (40, 2, 1, 'BOOK0001', '2024-01-01 00:00:00', '2024-01-01 00:00:00');
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO fields VALUES (6, 'ISBN');
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO itemDataValues VALUES (400, 'Introduction to Algorithms');
            INSERT INTO itemDataValues VALUES (401, '978-0-262-03384-8');
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            INSERT INTO itemData VALUES (40, 1, 400);
            INSERT INTO itemData VALUES (40, 6, 401);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, note TEXT, title TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, libraryID INTEGER DEFAULT 1, key TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        """)
        conn.commit()
        conn.close()
        isbn_db = ZoteroDatabase(db_path, warn_if_open=False)
        # Query with hyphens stripped
        result = find_by_isbn(isbn_db, "9780262033848")
        assert result is not None
        assert result.key == "BOOK0001"
        assert "Introduction" in result.title

    def test_found_with_hyphens_in_db(self, tmp_path):
        """ISBN stored with hyphens in DB should match query without hyphens."""
        db_path = tmp_path / "zotero.sqlite"
        conn = sqlite3.connect(str(db_path))
        conn.executescript("""
            CREATE TABLE version (schema TEXT, version INTEGER);
            INSERT INTO version VALUES ('userdata', 147);
            CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
            INSERT INTO libraries VALUES (1, 'user', 1);
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            INSERT INTO itemTypes VALUES (2, 'book');
            CREATE TABLE items (
                itemID INTEGER PRIMARY KEY, itemTypeID INTEGER, libraryID INTEGER DEFAULT 1,
                key TEXT, dateAdded TEXT, dateModified TEXT
            );
            INSERT INTO items VALUES (41, 2, 1, 'BOOK0002', '2024-01-01 00:00:00', '2024-01-01 00:00:00');
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            INSERT INTO fields VALUES (1, 'title');
            INSERT INTO fields VALUES (6, 'ISBN');
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            INSERT INTO itemDataValues VALUES (410, 'Some Book');
            INSERT INTO itemDataValues VALUES (411, '978-0-262-03384-8');
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            INSERT INTO itemData VALUES (41, 1, 410);
            INSERT INTO itemData VALUES (41, 6, 411);
            CREATE TABLE itemNotes (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, note TEXT, title TEXT);
            CREATE TABLE itemAttachments (itemID INTEGER PRIMARY KEY, parentItemID INTEGER, linkMode INTEGER, contentType TEXT, path TEXT);
            CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
            CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, collectionName TEXT, parentCollectionID INTEGER, libraryID INTEGER DEFAULT 1, key TEXT);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
            CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        """)
        conn.commit()
        conn.close()
        isbn_db = ZoteroDatabase(db_path, warn_if_open=False)
        result = find_by_isbn(isbn_db, "9780262033848")
        assert result is not None
        assert result.key == "BOOK0002"

    def test_not_found(self, db):
        result = find_by_isbn(db, "9999999999999")
        assert result is None


# ---------------------------------------------------------------------------
# ItemRef dataclass
# ---------------------------------------------------------------------------


class TestItemRef:
    def test_itemref_fields(self):
        ref = ItemRef(key="AABB0001", title="My Title", item_id=42)
        assert ref.key == "AABB0001"
        assert ref.title == "My Title"
        assert ref.item_id == 42
