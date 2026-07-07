"""Tests for the export layer."""

import csv
import io
import json

from pyzot.db import ZoteroDatabase
from pyzot.export.bibtex import item_to_bibtex, items_to_bibtex
from pyzot.export.csv_ import items_to_csv
from pyzot.export.json_ import items_to_json
from pyzot.export.markdown import items_to_markdown
from pyzot.queries.items import get_items


def test_json_export(db: ZoteroDatabase):
    items = get_items(db)
    output = items_to_json(items)
    data = json.loads(output)
    assert isinstance(data, list)
    assert len(data) == 3
    assert any(d["key"] == "AABB0001" for d in data)


def test_csv_export(db: ZoteroDatabase):
    items = get_items(db)
    output = items_to_csv(items)
    reader = csv.DictReader(io.StringIO(output))
    rows = list(reader)
    assert len(rows) == 3
    titles = {r["title"] for r in rows}
    assert "Deep Learning for NLP" in titles


def test_bibtex_export(db: ZoteroDatabase):
    items = get_items(db)
    output = items_to_bibtex(items)
    assert "@article" in output
    assert "Deep Learning for NLP" in output


def test_bibtex_citation_key(db: ZoteroDatabase):
    from pyzot.queries.items import get_item

    item = get_item(db, 1)
    assert item is not None
    bib = item_to_bibtex(item)
    # Key should contain Smith and 2023
    assert "Smith" in bib
    assert "2023" in bib


def test_markdown_export(db: ZoteroDatabase):
    items = get_items(db)
    output = items_to_markdown(items)
    assert "# Zotero Export" in output
    assert "Deep Learning for NLP" in output
    assert "| #" in output  # table header
