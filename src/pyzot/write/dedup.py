"""Duplicate detection against the existing read-only Zotero database.

All functions are read-only and never modify the database.

Uses the existing ZoteroDatabase.fetchone / fetchall interface.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ItemRef:
    """Lightweight reference to an existing Zotero item."""

    key: str
    title: str
    item_id: int


# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

# The DOI field in Zotero is stored in itemData with fieldName='DOI'.
_DOI_LOOKUP_SQL = """
    SELECT i.itemID, i.key, idv.value AS doi_val, title_idv.value AS title
    FROM items i
    JOIN itemData id_doi ON i.itemID = id_doi.itemID
    JOIN fields f_doi ON id_doi.fieldID = f_doi.fieldID AND f_doi.fieldName = 'DOI'
    JOIN itemDataValues idv ON id_doi.valueID = idv.valueID
    LEFT JOIN itemData id_title ON i.itemID = id_title.itemID
    LEFT JOIN fields f_title ON id_title.fieldID = f_title.fieldID AND f_title.fieldName = 'title'
    LEFT JOIN itemDataValues title_idv ON id_title.valueID = title_idv.valueID
    WHERE LOWER(idv.value) = LOWER(?)
      AND i.itemID NOT IN (SELECT itemID FROM itemNotes)
      AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
"""

_ISBN_LOOKUP_SQL = """
    SELECT i.itemID, i.key, idv.value AS isbn_val, title_idv.value AS title
    FROM items i
    JOIN itemData id_isbn ON i.itemID = id_isbn.itemID
    JOIN fields f_isbn ON id_isbn.fieldID = f_isbn.fieldID AND f_isbn.fieldName = 'ISBN'
    JOIN itemDataValues idv ON id_isbn.valueID = idv.valueID
    LEFT JOIN itemData id_title ON i.itemID = id_title.itemID
    LEFT JOIN fields f_title ON id_title.fieldID = f_title.fieldID AND f_title.fieldName = 'title'
    LEFT JOIN itemDataValues title_idv ON id_title.valueID = title_idv.valueID
    WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
      AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
"""

# arXiv IDs and PMIDs are typically stored in the 'Extra' field of Zotero items,
# or in the 'archiveID' field for preprints.
_EXTRA_LOOKUP_SQL = """
    SELECT i.itemID, i.key, idv.value AS extra_val, title_idv.value AS title
    FROM items i
    JOIN itemData id_extra ON i.itemID = id_extra.itemID
    JOIN fields f_extra ON id_extra.fieldID = f_extra.fieldID AND f_extra.fieldName IN ('extra', 'archiveID')
    JOIN itemDataValues idv ON id_extra.valueID = idv.valueID
    LEFT JOIN itemData id_title ON i.itemID = id_title.itemID
    LEFT JOIN fields f_title ON id_title.fieldID = f_title.fieldID AND f_title.fieldName = 'title'
    LEFT JOIN itemDataValues title_idv ON id_title.valueID = title_idv.valueID
    WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
      AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
"""


def find_by_doi(db, doi: str) -> ItemRef | None:
    """Search the read-only DB for an item matching the given DOI.

    Comparison is case-insensitive.

    Parameters
    ----------
    db:
        A ``ZoteroDatabase`` instance (read-only).
    doi:
        A normalised DOI string (e.g. ``"10.1038/example"``).

    Returns
    -------
    ItemRef or None
        The first matching item, or None if not found.
    """
    row = db.fetchone(_DOI_LOOKUP_SQL, (doi,))
    if row is None:
        return None
    return ItemRef(
        key=row["key"],
        title=row["title"] or "",
        item_id=row["itemID"],
    )


def find_by_arxiv(db, arxiv_id: str) -> ItemRef | None:
    """Search the read-only DB for an item matching the given arXiv ID.

    Checks the 'Extra' and 'archiveID' fields.

    Parameters
    ----------
    db:
        A ``ZoteroDatabase`` instance (read-only).
    arxiv_id:
        A normalised arXiv ID string (e.g. ``"2401.12345"``).

    Returns
    -------
    ItemRef or None
    """
    # Strip version suffix for matching (2401.12345v2 → 2401.12345)
    base_id = arxiv_id.split("v")[0] if "v" in arxiv_id else arxiv_id

    rows = db.fetchall(_EXTRA_LOOKUP_SQL, ())
    for row in rows:
        extra_val = (row["extra_val"] or "").lower()
        if base_id.lower() in extra_val:
            return ItemRef(
                key=row["key"],
                title=row["title"] or "",
                item_id=row["itemID"],
            )
    return None


def find_by_pmid(db, pmid: str) -> ItemRef | None:
    """Search the read-only DB for an item matching the given PMID.

    Checks the 'Extra' field for patterns like "PMID: 12345678".

    Parameters
    ----------
    db:
        A ``ZoteroDatabase`` instance (read-only).
    pmid:
        A normalised PMID string (digits only).

    Returns
    -------
    ItemRef or None
    """
    rows = db.fetchall(_EXTRA_LOOKUP_SQL, ())
    for row in rows:
        extra_val = (row["extra_val"] or "").lower()
        # Match "pmid: 12345" or "pubmed:12345" or just the bare number
        if (
            f"pmid: {pmid}" in extra_val
            or f"pubmed:{pmid}" in extra_val
            or f"pmid:{pmid}" in extra_val
        ):
            return ItemRef(
                key=row["key"],
                title=row["title"] or "",
                item_id=row["itemID"],
            )
    return None


def find_by_isbn(db, isbn: str) -> ItemRef | None:
    """Search the read-only DB for an item matching the given ISBN.

    Strips hyphens before comparison.

    Parameters
    ----------
    db:
        A ``ZoteroDatabase`` instance (read-only).
    isbn:
        A normalised ISBN string (digits, possibly with hyphens).

    Returns
    -------
    ItemRef or None
    """
    import re

    stripped_target = re.sub(r"[\s\-]", "", isbn)

    rows = db.fetchall(_ISBN_LOOKUP_SQL, ())
    for row in rows:
        isbn_val = row["isbn_val"] or ""
        stripped_db = re.sub(r"[\s\-]", "", isbn_val)
        if stripped_db == stripped_target:
            return ItemRef(
                key=row["key"],
                title=row["title"] or "",
                item_id=row["itemID"],
            )
    return None
