"""Search queries — field-level and full-text."""

from __future__ import annotations

import html
import http.client
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from pyzot import __version__
from pyzot.db import ZoteroDatabase
from pyzot.models import Item
from pyzot.queries.items import _build_items, get_item

MAX_RESPONSE_SIZE_BYTES = 1_000_000


def search_items(
    db: ZoteroDatabase,
    query: str,
    fields: list[str] | None = None,
    item_type: str | None = None,
) -> list[Item]:
    """Search item field values. If fields is None, search all fields."""
    like = f"%{query}%"

    if fields:
        placeholders = ",".join("?" * len(fields))
        field_clause = f"AND f.fieldName IN ({placeholders})"
        field_params: tuple = tuple(fields)
    else:
        field_clause = ""
        field_params = ()

    type_clause = ""
    type_params: tuple = ()
    if item_type:
        type_clause = "AND it.typeName = ?"
        type_params = (item_type,)

    sql = f"""
        SELECT DISTINCT i.itemID
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        LEFT JOIN itemData id ON i.itemID = id.itemID
        LEFT JOIN fields f ON id.fieldID = f.fieldID
        LEFT JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
          AND idv.value LIKE ?
          {field_clause}
          {type_clause}
        ORDER BY i.dateAdded DESC
    """
    params = (like,) + field_params + type_params
    rows = db.fetchall(sql, params)
    return _build_items(db, [r["itemID"] for r in rows])


def search_fulltext(db: ZoteroDatabase, query: str) -> list[Item]:
    """Search the full-text index (fulltextWords table)."""
    words = query.lower().split()
    if not words:
        return []

    # Each word must appear in the same item
    word_subqueries = " AND ".join(
        f"EXISTS (SELECT 1 FROM fulltextWords fw{i} JOIN fulltextItems fi{i} "
        f"ON fw{i}.wordID = fi{i}.wordID WHERE fi{i}.itemID = i.itemID "
        f"AND fw{i}.word LIKE ?)"
        for i in range(len(words))
    )
    params = tuple(f"%{w}%" for w in words)

    sql = f"""
        SELECT DISTINCT i.itemID
        FROM items i
        WHERE i.itemID NOT IN (SELECT itemID FROM itemNotes)
          AND i.itemID NOT IN (SELECT itemID FROM itemAttachments)
          AND {word_subqueries}
        ORDER BY i.dateAdded DESC
    """
    try:
        rows = db.fetchall(sql, params)
        return _build_items(db, [r["itemID"] for r in rows])
    except Exception:
        # fulltextWords may not be populated; fall back to field search
        return search_items(db, query)


def search_by_doi(db: ZoteroDatabase, doi: str) -> Item | None:
    # Normalise: strip https://doi.org/ prefix
    doi = doi.strip()
    for prefix in ("https://doi.org/", "http://doi.org/", "doi:"):
        if doi.lower().startswith(prefix):
            doi = doi[len(prefix):]

    rows = db.fetchall(
        """
        SELECT DISTINCT id.itemID
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE f.fieldName = 'DOI' AND LOWER(idv.value) = LOWER(?)
        """,
        (doi,),
    )
    if not rows:
        return None
    items = _build_items(db, [rows[0]["itemID"]])
    return items[0] if items else None


def search_by_author(db: ZoteroDatabase, query: str) -> list[Item]:
    """Search items by creator first or last name (case-insensitive, partial match)."""
    like = f"%{query}%"
    rows = db.fetchall(
        """
        SELECT DISTINCT ic.itemID
        FROM itemCreators ic
        JOIN creators c ON ic.creatorID = c.creatorID
        WHERE c.lastName LIKE ? OR c.firstName LIKE ?
        """,
        (like, like),
    )
    return _build_items(db, [r["itemID"] for r in rows])


def search_by_year_range(db: ZoteroDatabase, start: int, end: int) -> list[Item]:
    rows = db.fetchall(
        """
        SELECT DISTINCT id.itemID
        FROM itemData id
        JOIN fields f ON id.fieldID = f.fieldID
        JOIN itemDataValues idv ON id.valueID = idv.valueID
        WHERE f.fieldName = 'date'
          AND CAST(SUBSTR(idv.value, 1, 4) AS INTEGER) BETWEEN ? AND ?
        """,
        (start, end),
    )
    return _build_items(db, [r["itemID"] for r in rows])


def get_item_fulltext(db: ZoteroDatabase, item_id_or_key: int | str) -> str | None:
    """Return indexed full-text token content (bag-of-words) with metadata fallback."""
    text, _ = get_item_fulltext_with_strategy(db, item_id_or_key, prefer_network=False)
    return text


def get_item_fulltext_with_strategy(
    db: ZoteroDatabase,
    item_id_or_key: int | str,
    *,
    prefer_network: bool = True,
    auth: dict[str, str] | None = None,
    playwright_fetcher: Callable[[str], str | None] | None = None,
) -> tuple[str | None, str]:
    """Return full-text plus the source used to retrieve it.

    Strategy order:
    1) ``.zotero-ft-cache`` file of any attached PDF (cheapest, most reliable)
    2) direct network access (institution/network-location access)
    3) config-based auth credentials
    4) Playwright interactive login callback
    5) item metadata fallback
    """
    item = get_item(db, item_id_or_key)
    if item is None:
        return None, "not_found"

    # 1) Local Zotero full-text cache (.zotero-ft-cache) for any attachment
    cached = _read_local_fulltext_cache(item, db.path.parent)
    if cached:
        return cached, "cache"

    if prefer_network:
        urls = _candidate_fulltext_urls(item)
        for url in urls:
            text = _fetch_url_text(url)
            if text:
                return text, "network"

        auth_cfg = auth or {}
        user = (auth_cfg.get("username") or "").strip()
        password = auth_cfg.get("password") or ""
        if user and password:
            for url in urls:
                text = _fetch_url_text(url, username=user, password=password)
                if text:
                    return text, "config_auth"

        if playwright_fetcher is not None:
            for url in urls:
                text = (playwright_fetcher(url) or "").strip()
                if text:
                    return text, "playwright_auth"

    fallback_parts = [item.title]
    abstract = item.fields.get("abstractNote") or item.fields.get("abstract")
    if abstract:
        fallback_parts.append(abstract)
    fallback_parts.extend(note.plain_text for note in item.notes if note.plain_text)
    text = "\n\n".join(part for part in fallback_parts if part).strip()
    if text:
        return text, "metadata"
    return None, "none"


def _read_local_fulltext_cache(item, data_dir) -> str | None:
    """Return the first non-empty ``.zotero-ft-cache`` content for any attachment.

    Zotero stores extracted full text from PDFs/HTMLs at
    ``<storage>/<attachment-key>/.zotero-ft-cache`` (plain UTF-8).
    """
    from pathlib import Path as _Path

    data_dir = _Path(data_dir)
    for att in getattr(item, "attachments", []) or []:
        key = getattr(att, "key", None)
        if not key:
            continue
        cache_file = data_dir / "storage" / key / ".zotero-ft-cache"
        try:
            if cache_file.is_file():
                text = cache_file.read_text(encoding="utf-8", errors="ignore").strip()
                if text:
                    return text
        except OSError:
            continue
    return None


def _candidate_fulltext_urls(item: Item) -> list[str]:
    """Build candidate full-text URLs from item DOI and URL fields."""
    urls: list[str] = []
    doi = (item.doi or "").strip()
    if doi:
        # Strip canonical DOI URL and `doi:` prefixes before rebuilding doi.org URL.
        doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", "", doi, flags=re.I).strip()
        urls.append(f"https://doi.org/{doi}")

    raw_url = (item.fields.get("url") or item.fields.get("URL") or "").strip()
    if raw_url:
        urls.append(raw_url)

    # de-duplicate while preserving order
    return list(dict.fromkeys(urls))


def _fetch_url_text(url: str, username: str | None = None, password: str | None = None) -> str | None:
    """Fetch URL content as text, optionally using HTTP Basic Auth credentials.

    Returns plain text content, normalizing HTML into text when needed.
    Returns ``None`` on fetch/parse failure or when the remote content type is PDF.
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None

    req = urllib.request.Request(url, headers={"User-Agent": f"pyzot/{__version__}"})
    if username and password:
        manager = urllib.request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, f"{parsed.scheme}://{parsed.netloc}", username, password)
        opener = urllib.request.build_opener(urllib.request.HTTPBasicAuthHandler(manager))
    else:
        opener = urllib.request.build_opener()

    try:
        with opener.open(req, timeout=15) as resp:
            content_type = (resp.headers.get("Content-Type") or "").lower()
            if "application/pdf" in content_type:
                # PDF extraction is intentionally not attempted here.
                return None
            # Read one extra byte to detect responses larger than our maximum budget.
            payload = resp.read(MAX_RESPONSE_SIZE_BYTES + 1)
    except (urllib.error.URLError, http.client.HTTPException, ValueError, TimeoutError, OSError):
        return None

    if len(payload) > MAX_RESPONSE_SIZE_BYTES:
        payload = payload[:MAX_RESPONSE_SIZE_BYTES]

    text = payload.decode("utf-8", errors="ignore")
    if "text/html" in content_type or not content_type:
        text = _html_to_text(text)

    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _html_to_text(html_content: str) -> str:
    """Convert HTML to plain text with scripts/styles removed and whitespace normalized."""
    body = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html_content)
    body = re.sub(r"(?s)<[^>]+>", " ", body)
    body = html.unescape(body)
    return re.sub(r"\s+", " ", body).strip()
