"""Convert CSL-JSON records to Zotero connector saveItems item shape.

Reference: PLAN_WRITE.md §2.1 — connector's saveItems item shape.

Only csl_to_connector_item() is public. The inverse is not required for M2.
"""

from __future__ import annotations

import logging
import warnings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# CSL type → Zotero itemType mapping
# ---------------------------------------------------------------------------

_CSL_TYPE_MAP: dict[str, str] = {
    "journal-article": "journalArticle",
    "article-journal": "journalArticle",  # alias seen in some records
    "proceedings-article": "conferencePaper",
    "paper-conference": "conferencePaper",   # another common alias
    "book": "book",
    "book-chapter": "bookSection",
    "chapter": "bookSection",
    "report": "report",
    "thesis": "thesis",
    "dataset": "dataset",
    "posted-content": "preprint",           # Zotero ≥ 7; fallback below
    "preprint": "preprint",
    "webpage": "webpage",
    "article": "journalArticle",
    "editorial": "journalArticle",
    "review-article": "journalArticle",
    "review": "journalArticle",
    "letter": "journalArticle",
    "erratum": "journalArticle",
    "other": "journalArticle",
}

# Creator role mapping: CSL role → Zotero creatorType
_CREATOR_ROLE_MAP: dict[str, str] = {
    "author": "author",
    "editor": "editor",
    "translator": "translator",
    "chair": "editor",
    "collection-editor": "editor",
    "series-editor": "editor",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _map_type(csl_type: str) -> str:
    """Map a CSL type string to a Zotero itemType string.

    Unknown types fall back to 'journalArticle' with a warning.
    """
    z_type = _CSL_TYPE_MAP.get(csl_type)
    if z_type is None:
        warnings.warn(
            f"Unknown CSL type '{csl_type}'; defaulting to 'journalArticle'.",
            stacklevel=3,
        )
        z_type = "journalArticle"
    return z_type


def _extract_creators(csl: dict) -> list[dict]:
    """Extract creators from a CSL-JSON record.

    Handles 'author', 'editor', 'translator' lists.
    Returns a list of Zotero creator dicts with keys:
        firstName, lastName, creatorType
    or (for institutional names):
        name, creatorType
    """
    creators: list[dict] = []
    for csl_role, zot_role in _CREATOR_ROLE_MAP.items():
        for person in csl.get(csl_role, []):
            if isinstance(person, dict):
                if "literal" in person:
                    creators.append(
                        {"name": person["literal"], "creatorType": zot_role}
                    )
                else:
                    creators.append(
                        {
                            "firstName": person.get("given", ""),
                            "lastName": person.get("family", ""),
                            "creatorType": zot_role,
                        }
                    )
    return creators


def _extract_date(csl: dict) -> str:
    """Extract the date string from CSL 'issued' field.

    Returns an ISO-style date or empty string.
    """
    issued = csl.get("issued")
    if not issued:
        return ""
    date_parts = issued.get("date-parts")
    if date_parts and isinstance(date_parts, list) and date_parts[0]:
        parts = date_parts[0]
        # parts = [year] or [year, month] or [year, month, day]
        parts_str = [str(p) for p in parts if p is not None]
        return "-".join(parts_str) if parts_str else ""
    # Fallback: literal date string if present
    return issued.get("literal", "")


def _scalar(csl: dict, *keys: str) -> str:
    """Return the first non-empty value from csl for any of the given keys.

    If the value is a list (as Crossref returns for title), return the first element.
    """
    for k in keys:
        v = csl.get(k)
        if v is None or v == "":
            continue
        if isinstance(v, list):
            # Crossref returns title, container-title etc. as lists
            return str(v[0]) if v else ""
        return str(v)
    return ""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def csl_to_connector_item(csl: dict) -> dict:
    """Convert a CSL-JSON record to a Zotero connector saveItems item shape.

    The output dict can be placed directly in the ``items`` list of a
    ``POST /connector/saveItems`` request body.

    Parameters
    ----------
    csl:
        A CSL-JSON record (e.g. from Crossref, arXiv, PubMed, or OpenLibrary).

    Returns
    -------
    dict
        A Zotero-connector-shaped item dict.
    """
    csl_type = csl.get("type", "journal-article")
    item_type = _map_type(csl_type)

    # 'preprint' may not be supported in Zotero < 7; safest to keep it as-is
    # and let Zotero demote to journalArticle if needed (its own fallback).

    item: dict = {
        "itemType": item_type,
        "title": _scalar(csl, "title", "original-title"),
        "creators": _extract_creators(csl),
        "date": _extract_date(csl),
        "abstractNote": _scalar(csl, "abstract"),
        "language": _scalar(csl, "language"),
        "url": _scalar(csl, "URL", "url"),
        "accessDate": "",
        "tags": [],
        "notes": [],
        "attachments": [],
        "seeAlso": [],
    }

    # --- Identifier fields ---
    doi = _scalar(csl, "DOI", "doi")
    if doi:
        item["DOI"] = doi

    isbn_raw = csl.get("ISBN", "")
    if isinstance(isbn_raw, list):
        isbn_raw = isbn_raw[0] if isbn_raw else ""
    if isbn_raw:
        item["ISBN"] = str(isbn_raw)

    issn_raw = csl.get("ISSN", "")
    if isinstance(issn_raw, list):
        issn_raw = issn_raw[0] if issn_raw else ""
    if issn_raw:
        item["ISSN"] = str(issn_raw)

    # --- Journal / container fields ---
    container_title = _scalar(csl, "container-title", "containerTitle")
    if item_type == "conferencePaper":
        if container_title:
            item["proceedingsTitle"] = container_title
    elif item_type == "bookSection":
        if container_title:
            item["bookTitle"] = container_title
    elif item_type in ("book", "report", "thesis", "dataset", "preprint"):
        if container_title:
            item["publisher"] = container_title
    else:
        if container_title:
            item["publicationTitle"] = container_title

    short_title = _scalar(csl, "container-title-short", "journalAbbreviation")
    if short_title:
        item["journalAbbreviation"] = short_title

    # --- Volume / issue / pages ---
    volume = _scalar(csl, "volume")
    if volume:
        item["volume"] = volume

    issue = _scalar(csl, "issue", "number")
    if issue:
        item["issue"] = issue

    pages = _scalar(csl, "page", "pages")
    if pages:
        item["pages"] = pages

    # --- Edition / publisher ---
    edition = _scalar(csl, "edition")
    if edition:
        item["edition"] = edition

    publisher = _scalar(csl, "publisher")
    if publisher and "publisher" not in item:
        item["publisher"] = publisher

    place = _scalar(csl, "publisher-place", "place")
    if place:
        item["place"] = place

    # --- Series ---
    collection_title = _scalar(csl, "collection-title", "series")
    if collection_title:
        item["series"] = collection_title

    # --- Thesis-specific ---
    institution = _scalar(csl, "publisher")
    if item_type == "thesis" and institution:
        item["university"] = institution

    # --- Report number ---
    report_number = _scalar(csl, "number")
    if item_type == "report" and report_number:
        item["reportNumber"] = report_number

    # --- arXiv extra field (stored in 'Extra' by Zotero) ---
    archive = _scalar(csl, "archive")
    archive_id = _scalar(csl, "archive_location", "archiveID")
    if archive or archive_id:
        extra_parts = []
        if archive:
            extra_parts.append(f"archive: {archive}")
        if archive_id:
            extra_parts.append(f"archive ID: {archive_id}")
        item["extra"] = "\n".join(extra_parts)

    # Clean up empty strings in top-level scalars
    for key in list(item.keys()):
        if item[key] == "" and key not in ("tags", "notes", "attachments", "seeAlso", "accessDate"):
            del item[key]

    return item
