"""OpenAlex resolver — citation/title search and work lookup.

Used as a fallback when Crossref bibliographic search returns no confident match.

GET https://api.openalex.org/works?search=<text>&per-page=N
GET https://api.openalex.org/works/<id>

No API key required for polite access (per OpenAlex TOS).
"""

from __future__ import annotations

import logging
import time
from urllib.parse import quote

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.openalex.org"


def _get_user_agent() -> str:
    """Return the User-Agent string from config, falling back to default."""
    try:
        from zotcli.config import get_config_value
        email = get_config_value("resolvers.crossref_user_agent")
        if email:
            return email
    except Exception:
        pass
    return "zotcli/0.2 (mailto:auto-set-on-first-run)"


def _normalize_doi(doi: str | None) -> str | None:
    """Strip https://doi.org/ prefix if present."""
    if not doi:
        return None
    if doi.startswith("https://doi.org/"):
        return doi[len("https://doi.org/"):]
    if doi.startswith("http://doi.org/"):
        return doi[len("http://doi.org/"):]
    return doi


def _extract_authors(work: dict) -> list[str]:
    """Extract a list of author display names from an OpenAlex work dict."""
    authors = []
    for authorship in work.get("authorships", []):
        author = authorship.get("author", {})
        name = author.get("display_name", "")
        if name:
            authors.append(name)
    return authors


def search(text: str, per_page: int = 5) -> list[dict]:
    """Search OpenAlex for works matching *text*.

    Parameters
    ----------
    text:
        Free-text search query (citation string, title, etc.).
    per_page:
        Maximum number of results to return (default 5).

    Returns
    -------
    list[dict]
        Normalized hit dicts with keys: doi, title, authors, year, score.
        Hits without a DOI are filtered out.

    Notes
    -----
    On network failure or non-200 response, returns an empty list (soft fail).
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "The 'write' extra is required for OpenAlex access. "
            "Install it with: pip install \"zotcli[write]\""
        ) from exc

    params = {
        "search": text,
        "per-page": per_page,
        "select": "doi,title,authorships,publication_year,relevance_score,id",
    }
    headers = {"User-Agent": _get_user_agent()}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                f"{_BASE_URL}/works",
                params=params,
                headers=headers,
                follow_redirects=True,
            )
    except Exception as exc:
        logger.warning("OpenAlex search failed (network error): %s", exc)
        return []

    if resp.status_code != 200:
        logger.warning("OpenAlex search returned HTTP %s", resp.status_code)
        return []

    data = resp.json()
    results = data.get("results", [])

    hits = []
    for work in results:
        doi = _normalize_doi(work.get("doi"))
        if not doi:
            continue  # filter out hits with no DOI

        title_raw = work.get("title") or ""
        # OpenAlex returns title as a plain string
        title = title_raw if isinstance(title_raw, str) else str(title_raw)

        hits.append({
            "doi": doi,
            "title": title,
            "authors": _extract_authors(work),
            "year": work.get("publication_year"),
            "score": work.get("relevance_score"),
        })

    logger.debug("OpenAlex search returned %d usable hits for query: %s", len(hits), text[:80])
    return hits


def resolve(openalex_id_or_doi: str) -> dict:
    """Fetch a single OpenAlex work and return a CSL-JSON-shaped dict.

    Parameters
    ----------
    openalex_id_or_doi:
        An OpenAlex ID (``https://openalex.org/W...`` or ``W...``) or a DOI.

    Returns
    -------
    dict
        A CSL-JSON-shaped dict with keys: type, title, author, issued,
        container-title, DOI, publisher, abstract.

    Raises
    ------
    LookupError
        If the work cannot be found.
    RuntimeError
        On network / HTTP errors.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "The 'write' extra is required for OpenAlex access. "
            "Install it with: pip install \"zotcli[write]\""
        ) from exc

    headers = {"User-Agent": _get_user_agent()}

    # Determine endpoint path
    s = openalex_id_or_doi.strip()
    if s.startswith("https://openalex.org/") or s.startswith("W") and s[1:].isdigit():
        # OpenAlex ID
        if s.startswith("https://openalex.org/"):
            work_id = s[len("https://openalex.org/"):]
        else:
            work_id = s
        url = f"{_BASE_URL}/works/{work_id}"
    elif s.startswith("10."):
        # DOI
        url = f"{_BASE_URL}/works/https://doi.org/{quote(s, safe='/')}"
    else:
        url = f"{_BASE_URL}/works/{quote(s, safe='/')}"

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(url, headers=headers, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"OpenAlex request failed: {exc}") from exc

    if resp.status_code == 404:
        raise LookupError(f"OpenAlex: work not found: {openalex_id_or_doi}")
    if resp.status_code != 200:
        raise RuntimeError(f"OpenAlex returned HTTP {resp.status_code} for {openalex_id_or_doi}")

    work = resp.json()

    # --- Map to CSL-JSON-shaped dict ---
    # Type mapping from OpenAlex to CSL
    _TYPE_MAP = {
        "journal-article": "journal-article",
        "proceedings-article": "proceedings-article",
        "book": "book",
        "book-chapter": "book-chapter",
        "dissertation": "thesis",
        "dataset": "dataset",
        "preprint": "posted-content",
        "report": "report",
        "other": "article",
    }
    raw_type = work.get("type", "article")
    csl_type = _TYPE_MAP.get(raw_type, "article")

    # Authors
    authors = []
    for authorship in work.get("authorships", []):
        author_info = authorship.get("author", {})
        display_name = author_info.get("display_name", "")
        orcid = author_info.get("orcid", "")
        if display_name:
            # Try to split into family/given
            parts = display_name.split(", ", 1)
            if len(parts) == 2:
                entry: dict = {"family": parts[0], "given": parts[1]}
            else:
                parts2 = display_name.rsplit(" ", 1)
                if len(parts2) == 2:
                    entry = {"given": parts2[0], "family": parts2[1]}
                else:
                    entry = {"literal": display_name}
            if orcid:
                entry["ORCID"] = orcid
            authors.append(entry)

    # Publication year
    year = work.get("publication_year")
    issued: dict = {}
    if year:
        issued = {"date-parts": [[year]]}

    # Host venue / journal
    primary_location = work.get("primary_location") or {}
    source = primary_location.get("source") or {}
    container_title = source.get("display_name", "")

    doi = _normalize_doi(work.get("doi"))

    csl: dict = {
        "type": csl_type,
        "title": work.get("title") or "",
        "author": authors,
        "issued": issued,
    }
    if container_title:
        csl["container-title"] = container_title
    if doi:
        csl["DOI"] = doi

    abstract = work.get("abstract_inverted_index")
    if abstract is None:
        abstract_text = work.get("abstract", "")
    else:
        abstract_text = _reconstruct_abstract(abstract)
    if abstract_text:
        csl["abstract"] = abstract_text

    logger.debug("OpenAlex resolved %s → DOI=%s", openalex_id_or_doi, doi)
    return csl


def _reconstruct_abstract(inverted_index: dict) -> str:
    """Reconstruct abstract text from OpenAlex inverted index format."""
    if not isinstance(inverted_index, dict):
        return ""
    # Build position → word map
    positions: dict[int, str] = {}
    for word, pos_list in inverted_index.items():
        for pos in pos_list:
            positions[pos] = word
    if not positions:
        return ""
    return " ".join(positions[i] for i in sorted(positions))
