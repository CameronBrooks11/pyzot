"""Tests for the database layer."""

import pytest
from zotcli.db import ZoteroDatabase


def test_db_opens(db: ZoteroDatabase):
    assert db.schema_version == 147


def test_db_is_readonly(db: ZoteroDatabase):
    import sqlite3
    with pytest.raises(Exception):
        db.execute("INSERT INTO tags(name) VALUES ('x')")


def test_fetchone(db: ZoteroDatabase):
    # items table includes attachment/note rows; count only regular items
    row = db.fetchone(
        "SELECT COUNT(*) as n FROM items WHERE itemID NOT IN "
        "(SELECT itemID FROM itemNotes) AND itemID NOT IN "
        "(SELECT itemID FROM itemAttachments)"
    )
    assert row["n"] == 3


def test_fetchall(db: ZoteroDatabase):
    rows = db.fetchall(
        "SELECT itemID FROM items WHERE itemID NOT IN "
        "(SELECT itemID FROM itemNotes) AND itemID NOT IN "
        "(SELECT itemID FROM itemAttachments) ORDER BY itemID"
    )
    assert [r["itemID"] for r in rows] == [1, 2, 3]


def test_context_manager(tmp_path):
    import sqlite3
    db_path = tmp_path / "test.sqlite"
    from tests.conftest import _seed_db
    conn = sqlite3.connect(str(db_path))
    _seed_db(conn)
    conn.commit()
    conn.close()

    with ZoteroDatabase(db_path, warn_if_open=False) as db:
        assert db.schema_version == 147
