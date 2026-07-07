"""Tests for the query layer."""

from zotcli.db import ZoteroDatabase
from zotcli.queries import search as search_queries
from zotcli.queries.collections import (
    get_all_collections,
    get_collection_tree,
    get_items_in_collection,
)
from zotcli.queries.items import get_item, get_items
from zotcli.queries.search import (
    get_item_fulltext,
    get_item_fulltext_with_strategy,
    search_by_doi,
    search_by_year_range,
    search_items,
)
from zotcli.queries.tags import get_all_tags, get_items_by_tag


def test_get_items(db: ZoteroDatabase):
    items = get_items(db)
    assert len(items) == 3
    titles = {i.title for i in items}
    assert "Deep Learning for NLP" in titles


def test_get_item_by_id(db: ZoteroDatabase):
    item = get_item(db, 1)
    assert item is not None
    assert item.title == "Deep Learning for NLP"
    assert item.year == "2023"
    assert item.doi == "10.1038/example"


def test_get_item_by_key(db: ZoteroDatabase):
    item = get_item(db, "AABB0001")
    assert item is not None
    assert item.item_type == "journalArticle"


def test_item_authors(db: ZoteroDatabase):
    item = get_item(db, 1)
    assert item is not None
    assert "Smith, John" in item.authors
    assert "Doe, Alice" in item.authors


def test_item_tags(db: ZoteroDatabase):
    item = get_item(db, 1)
    assert item is not None
    assert "machine-learning" in item.tags
    assert "nlp" in item.tags


def test_item_not_found(db: ZoteroDatabase):
    assert get_item(db, 9999) is None


def test_get_all_collections(db: ZoteroDatabase):
    cols = get_all_collections(db)
    names = {c.name for c in cols}
    assert "PhD" in names
    assert "NLP" in names


def test_collection_tree(db: ZoteroDatabase):
    roots = get_collection_tree(db)
    assert len(roots) == 1
    assert roots[0].name == "PhD"
    assert len(roots[0].children) == 1
    assert roots[0].children[0].name == "NLP"


def test_items_in_collection(db: ZoteroDatabase):
    # NLP collection (ID=2) has items 1 and 3
    items = get_items_in_collection(db, 2)
    ids = {i.item_id for i in items}
    assert 1 in ids
    assert 3 in ids


def test_items_in_collection_recursive(db: ZoteroDatabase):
    # PhD (ID=1) has no direct items but NLP (sub) has items 1,3
    items = get_items_in_collection(db, 1, recursive=True)
    ids = {i.item_id for i in items}
    assert 1 in ids
    assert 3 in ids


def test_get_all_tags(db: ZoteroDatabase):
    tags = get_all_tags(db)
    names = [t[0] for t in tags]
    assert "machine-learning" in names


def test_get_items_by_tag(db: ZoteroDatabase):
    items = get_items_by_tag(db, "nlp")
    assert any(i.item_id == 1 for i in items)


def test_search_items(db: ZoteroDatabase):
    results = search_items(db, "Deep Learning")
    assert any(i.title == "Deep Learning for NLP" for i in results)


def test_search_by_doi(db: ZoteroDatabase):
    item = search_by_doi(db, "10.1038/example")
    assert item is not None
    assert item.item_id == 1


def test_search_by_doi_with_prefix(db: ZoteroDatabase):
    item = search_by_doi(db, "https://doi.org/10.1038/example")
    assert item is not None


def test_item_has_attachments(db: ZoteroDatabase):
    item = get_item(db, 1)
    assert item is not None
    assert len(item.attachments) == 1
    att = item.attachments[0]
    assert att.content_type == "application/pdf"
    assert att.key == "ATTKEY001"
    assert att.link_mode == 0


def test_item_has_notes(db: ZoteroDatabase):
    item = get_item(db, 1)
    assert item is not None
    assert len(item.notes) == 1
    note = item.notes[0]
    assert note.title == "My Note"
    assert "test note" in note.plain_text
    assert "<b>" not in note.plain_text  # HTML stripped


def test_search_by_year_range(db: ZoteroDatabase):
    results = search_by_year_range(db, 2022, 2023)
    ids = {i.item_id for i in results}
    assert 1 in ids  # 2023
    assert 2 in ids  # 2022
    assert 3 not in ids  # 2021


def test_get_item_fulltext_returns_metadata_when_no_cache(db: ZoteroDatabase):
    """Without a .zotero-ft-cache file the function returns title + abstract + notes.

    The previous implementation reconstructed a bag-of-words pseudo-text from
    the fulltext index (using a nonexistent ``tokenCount`` column). With the
    fix that path is gone — when the on-disk cache is missing, we fall back
    to the item's own metadata.
    """
    text = get_item_fulltext(db, 1)
    assert text is not None
    # Title + abstract + notes are all included in the metadata fallback
    assert "Deep Learning for NLP" in text


def test_get_item_fulltext_fallback_to_title_when_not_indexed(db: ZoteroDatabase):
    text = get_item_fulltext(db, 2)
    assert text is not None
    assert "Python Programming" in text


def test_fulltext_strategy_prefers_network(db: ZoteroDatabase, monkeypatch):
    monkeypatch.setattr(search_queries, "_fetch_url_text", lambda *args, **kwargs: "network text")

    text, source = get_item_fulltext_with_strategy(db, 1, auth={"username": "u", "password": "p"})
    assert text == "network text"
    assert source == "network"


def test_fulltext_strategy_uses_config_auth_after_network_fail(db: ZoteroDatabase, monkeypatch):
    def mock_fetch(url: str, username: str | None = None, password: str | None = None):
        if username == "u" and password == "p":
            return "config text"
        return None

    monkeypatch.setattr(search_queries, "_fetch_url_text", mock_fetch)

    text, source = get_item_fulltext_with_strategy(db, 1, auth={"username": "u", "password": "p"})
    assert text == "config text"
    assert source == "config_auth"


def test_fulltext_strategy_uses_playwright_after_config_fail(db: ZoteroDatabase, monkeypatch):
    monkeypatch.setattr(search_queries, "_fetch_url_text", lambda *args, **kwargs: None)

    text, source = get_item_fulltext_with_strategy(
        db,
        1,
        auth={"username": "u", "password": "p"},
        playwright_fetcher=lambda _url: "playwright text",
    )
    assert text == "playwright text"
    assert source == "playwright_auth"


def test_fulltext_strategy_offline_skips_network(db: ZoteroDatabase, monkeypatch):
    monkeypatch.setattr(search_queries, "_fetch_url_text", lambda *args, **kwargs: "network text")
    text, source = get_item_fulltext_with_strategy(db, 1, prefer_network=False)
    assert text is not None
    # With prefer_network=False and no .zotero-ft-cache on disk, the metadata
    # fallback runs and returns title + abstract + notes.
    assert "Deep Learning for NLP" in text
    assert source == "metadata"
