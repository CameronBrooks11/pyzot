"""arXiv resolver — arXiv ID → CSL-JSON.

GET http://export.arxiv.org/api/query?id_list={id}

Parses Atom XML using stdlib xml.etree.ElementTree.
Returns a CSL-JSON-shaped dict with type "posted-content" (preprint).
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_API_URL = "http://export.arxiv.org/api/query"

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

# Namespace map for ElementTree
_NS = {
    "atom": _ATOM_NS,
    "arxiv": _ARXIV_NS,
}


def resolve(arxiv_id: str) -> dict:
    """Fetch metadata for *arxiv_id* from the arXiv Atom feed.

    Parameters
    ----------
    arxiv_id:
        A normalised arXiv ID (e.g. ``"2401.12345"`` or ``"cs.AI/0701001"``).

    Returns
    -------
    dict
        A CSL-JSON record with ``type: "posted-content"``.

    Raises
    ------
    IdentifierNotFound
        If arXiv returns no entries for the given ID.
    RuntimeError
        On HTTP errors.
    """
    from pyzot.write.resolvers._http import require_httpx

    httpx = require_httpx()
    url = f"{_API_URL}?id_list={arxiv_id}"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to reach arXiv for ID '{arxiv_id}': {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"arXiv API returned HTTP {resp.status_code} for ID '{arxiv_id}': {resp.text[:200]}"
        )

    return _parse_atom(resp.text, arxiv_id)


def _parse_atom(xml_text: str, arxiv_id: str) -> dict:
    """Parse arXiv Atom XML and return a CSL-JSON dict."""
    from pyzot.write.resolvers import IdentifierNotFound

    root = ET.fromstring(xml_text)
    entries = root.findall("atom:entry", _NS)
    if not entries:
        raise IdentifierNotFound("arxiv", arxiv_id, "No entries in arXiv Atom response")

    entry = entries[0]

    # Check for the "no results" error entry
    title_el = entry.find("atom:title", _NS)
    title = (title_el.text or "").strip() if title_el is not None else ""
    if title == "Error":
        raise IdentifierNotFound("arxiv", arxiv_id, "arXiv returned an error entry")

    # Authors
    creators = []
    for author_el in entry.findall("atom:author", _NS):
        name_el = author_el.find("atom:name", _NS)
        if name_el is not None and name_el.text:
            full_name = name_el.text.strip()
            # arXiv uses "FirstName LastName"; split naively on last space
            parts = full_name.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append({
                    "given": parts[0],
                    "family": parts[1],
                })
            else:
                creators.append({"literal": full_name})

    # Published date (ISO 8601: YYYY-MM-DDTHH:MM:SSZ)
    published_el = entry.find("atom:published", _NS)
    date_str = ""
    date_parts_list: list[list[int]] = []
    if published_el is not None and published_el.text:
        raw = published_el.text.strip()
        year_month_day = raw[:10].split("-")
        try:
            date_parts_list = [[int(p) for p in year_month_day]]
            date_str = "-".join(year_month_day[:3])
        except ValueError:
            date_str = raw[:10]

    # Abstract
    summary_el = entry.find("atom:summary", _NS)
    abstract = (summary_el.text or "").strip() if summary_el is not None else ""

    # arXiv ID from <id> element (canonical URL)
    id_el = entry.find("atom:id", _NS)
    canonical_url = (id_el.text or "").strip() if id_el is not None else ""
    # Extract clean arXiv ID from URL like http://arxiv.org/abs/2401.12345v1
    clean_id = arxiv_id
    if canonical_url:
        # Strip URL prefix to get the bare ID
        for prefix in ("http://arxiv.org/abs/", "https://arxiv.org/abs/"):
            if canonical_url.startswith(prefix):
                clean_id = canonical_url[len(prefix):]
                break

    # Category (primary)
    category_el = entry.find("arxiv:primary_category", _NS)
    category = ""
    if category_el is not None:
        category = category_el.get("term", "")

    # Journal ref (if published somewhere)
    journal_ref_el = entry.find("arxiv:journal_ref", _NS)
    journal_ref = (journal_ref_el.text or "").strip() if journal_ref_el is not None else ""

    # DOI (if published)
    doi_el = entry.find("arxiv:doi", _NS)
    doi = (doi_el.text or "").strip() if doi_el is not None else ""

    # Build CSL-JSON
    csl: dict = {
        "type": "posted-content",
        "subtype": "preprint",
        "title": title,
        "author": creators,
        "abstract": abstract,
        "URL": canonical_url or f"https://arxiv.org/abs/{arxiv_id}",
        "source": "arXiv",
        "archive": "arXiv",
        "archive_location": clean_id,
    }

    if date_parts_list:
        csl["issued"] = {"date-parts": date_parts_list}
    elif date_str:
        csl["issued"] = {"literal": date_str}

    if doi:
        csl["DOI"] = doi
    if journal_ref:
        csl["container-title"] = journal_ref
    if category:
        csl["genre"] = category

    return csl
