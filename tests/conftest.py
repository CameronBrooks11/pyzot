"""Shared test fixtures — in-memory Zotero-like SQLite database."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from zotcli.db import ZoteroDatabase


def _seed_db(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE version (schema TEXT, version INTEGER);
        INSERT INTO version VALUES ('userdata', 147);

        CREATE TABLE libraries (libraryID INTEGER PRIMARY KEY, type TEXT, editable INTEGER);
        INSERT INTO libraries VALUES (1, 'user', 1);

        CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
        INSERT INTO itemTypes VALUES (1, 'journalArticle');
        INSERT INTO itemTypes VALUES (2, 'book');
        INSERT INTO itemTypes VALUES (3, 'conferencePaper');

        CREATE TABLE items (
            itemID INTEGER PRIMARY KEY,
            itemTypeID INTEGER,
            libraryID INTEGER DEFAULT 1,
            key TEXT,
            dateAdded TEXT,
            dateModified TEXT
        );
        INSERT INTO items VALUES (1, 1, 1, 'AABB0001', '2023-01-01 00:00:00', '2023-01-01 00:00:00');
        INSERT INTO items VALUES (2, 2, 1, 'CCDD0002', '2022-06-15 00:00:00', '2022-06-15 00:00:00');
        INSERT INTO items VALUES (3, 3, 1, 'EEFF0003', '2021-03-20 00:00:00', '2021-03-20 00:00:00');

        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        INSERT INTO fields VALUES (1, 'title');
        INSERT INTO fields VALUES (2, 'date');
        INSERT INTO fields VALUES (3, 'publicationTitle');
        INSERT INTO fields VALUES (4, 'DOI');
        INSERT INTO fields VALUES (5, 'author');

        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        INSERT INTO itemDataValues VALUES (1, 'Deep Learning for NLP');
        INSERT INTO itemDataValues VALUES (2, '2023');
        INSERT INTO itemDataValues VALUES (3, 'Nature ML');
        INSERT INTO itemDataValues VALUES (4, '10.1038/example');
        INSERT INTO itemDataValues VALUES (5, 'Python Programming');
        INSERT INTO itemDataValues VALUES (6, '2022');
        INSERT INTO itemDataValues VALUES (7, 'Transformers in CV');
        INSERT INTO itemDataValues VALUES (8, '2021');

        CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
        INSERT INTO itemData VALUES (1, 1, 1);
        INSERT INTO itemData VALUES (1, 2, 2);
        INSERT INTO itemData VALUES (1, 3, 3);
        INSERT INTO itemData VALUES (1, 4, 4);
        INSERT INTO itemData VALUES (2, 1, 5);
        INSERT INTO itemData VALUES (2, 2, 6);
        INSERT INTO itemData VALUES (3, 1, 7);
        INSERT INTO itemData VALUES (3, 2, 8);

        CREATE TABLE creatorTypes (creatorTypeID INTEGER PRIMARY KEY, creatorType TEXT);
        INSERT INTO creatorTypes VALUES (1, 'author');
        INSERT INTO creatorTypes VALUES (2, 'editor');

        CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
        INSERT INTO creators VALUES (1, 'John', 'Smith');
        INSERT INTO creators VALUES (2, 'Alice', 'Doe');

        CREATE TABLE itemCreators (
            itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER
        );
        INSERT INTO itemCreators VALUES (1, 1, 1, 0);
        INSERT INTO itemCreators VALUES (1, 2, 1, 1);
        INSERT INTO itemCreators VALUES (2, 1, 1, 0);

        CREATE TABLE tags (tagID INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO tags VALUES (1, 'machine-learning');
        INSERT INTO tags VALUES (2, 'nlp');
        INSERT INTO tags VALUES (3, 'python');

        CREATE TABLE itemTags (itemID INTEGER, tagID INTEGER, type INTEGER DEFAULT 0);
        INSERT INTO itemTags VALUES (1, 1, 0);
        INSERT INTO itemTags VALUES (1, 2, 0);
        INSERT INTO itemTags VALUES (2, 3, 0);

        CREATE TABLE collections (
            collectionID INTEGER PRIMARY KEY,
            collectionName TEXT,
            parentCollectionID INTEGER,
            libraryID INTEGER DEFAULT 1,
            key TEXT
        );
        INSERT INTO collections VALUES (1, 'PhD', NULL, 1, 'COLL0001');
        INSERT INTO collections VALUES (2, 'NLP', 1, 1, 'COLL0002');

        CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
        INSERT INTO collectionItems VALUES (2, 1);
        INSERT INTO collectionItems VALUES (2, 3);

        CREATE TABLE itemAttachments (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            linkMode INTEGER,
            contentType TEXT,
            path TEXT
        );
        -- Attachment for item 1: imported PDF (link_mode=0)
        INSERT INTO items VALUES (10, 1, 1, 'ATTKEY001', '2023-01-01 00:00:00', '2023-01-01 00:00:00');
        INSERT INTO itemAttachments VALUES (10, 1, 0, 'application/pdf', 'storage:Smith2023.pdf');

        CREATE TABLE itemNotes (
            itemID INTEGER PRIMARY KEY,
            parentItemID INTEGER,
            note TEXT,
            title TEXT
        );
        -- Note for item 1
        INSERT INTO items VALUES (11, 1, 1, 'NOTEKEY01', '2023-01-01 00:00:00', '2023-01-01 00:00:00');
        INSERT INTO itemNotes VALUES (11, 1, '<p>This is a <b>test note</b>.</p>', 'My Note');

        CREATE TABLE fulltextWords (wordID INTEGER PRIMARY KEY, word TEXT);
        CREATE TABLE fulltextItems (wordID INTEGER, itemID INTEGER, tokenCount INTEGER, version INTEGER);
        -- Indexed tokens for item 1 ("Deep Learning for NLP"); tokenCount stores frequency.
        INSERT INTO fulltextWords VALUES (1, 'deep');
        INSERT INTO fulltextWords VALUES (2, 'learning');
        INSERT INTO fulltextWords VALUES (3, 'nlp');
        INSERT INTO fulltextItems VALUES (1, 1, 2, 1);
        INSERT INTO fulltextItems VALUES (2, 1, 1, 1);
        INSERT INTO fulltextItems VALUES (3, 1, 1, 1);
        """
    )


@pytest.fixture
def db(tmp_path: Path) -> ZoteroDatabase:
    """Return a ZoteroDatabase backed by a seeded in-memory-like temp file."""
    db_path = tmp_path / "zotero.sqlite"
    conn = sqlite3.connect(str(db_path))
    _seed_db(conn)
    conn.commit()
    conn.close()
    return ZoteroDatabase(db_path, warn_if_open=False)
