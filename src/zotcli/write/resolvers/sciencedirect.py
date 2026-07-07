"""ScienceDirect URL → DOI resolver.

url_to_doi(url: str) -> str | None

Tries in order:
1. Regex-extract a DOI directly from the URL.
2. Extract PII from ``/pii/<PII>`` or ``/abs/pii/<PII>`` path segments.
3. Crossref by PII as alternative-id filter:
   ``GET https://api.crossref.org/works?filter=alternative-id:<PII>&rows=1``
4. If that returns nothing, fall back to
   ``crossref.bibliographic_search(PII)``.

All network calls use httpx (lazily imported).
Returns ``None`` if no DOI is resolved (soft fail).
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

# DOI in URL path or query string, e.g. /doi/10.1016/j.foo.2025.01.001
_DOI_REGEX = re.compile(
    r"(?:^|[/?&])(?:doi[:/]|DOI=)?(10\.\d{4,9}/[^\s?&#\"'<>]+)",
    re.IGNORECASE,
)

# PII in URL: /pii/<PII> or /abs/pii/<PII> (may have slash at end)
# PII format: S followed by 16 alphanumeric chars (typically), but let's be flexible
_PII_REGEX = re.compile(
    r"/(?:abs/)?pii/([A-Z0-9]{17,20})(?:[/?#]|$)",
    re.IGNORECASE,
)

_CROSSREF_BASE = "https://api.crossref.org/works"


def url_to_doi(url: str) -> str | None:
    """Resolve a ScienceDirect URL to a DOI.

    Parameters
    ----------
    url:
        A ScienceDirect article URL, e.g.
        ``https://www.sciencedirect.com/science/article/pii/S2352467725000XYZ``

    Returns
    -------
    str or None
        A DOI string, or ``None`` if no DOI could be resolved.

    Notes
    -----
    Elsevier registers PII (Publisher Item Identifier) as an alternative-id
    at Crossref, so querying ``/works?filter=alternative-id:<PII>`` is
    usually the fastest route to the DOI. If Crossref returns empty, a
    bibliographic search on the PII is attempted as a last resort.
    """
    # ------------------------------------------------------------------
    # Strategy 1: DOI in URL
    # ------------------------------------------------------------------
    m = _DOI_REGEX.search(url)
    if m:
        doi = m.group(1).rstrip(".")
        logger.debug("ScienceDirect: found DOI in URL via regex: %s", doi)
        return doi

    # ------------------------------------------------------------------
    # Strategy 2: Extract PII
    # ------------------------------------------------------------------
    pii: str | None = None
    m2 = _PII_REGEX.search(url)
    if m2:
        pii = m2.group(1).upper()
        logger.debug("ScienceDirect: extracted PII=%s from URL", pii)

    if pii is None:
        logger.debug("ScienceDirect: no DOI or PII found in URL: %s", url)
        return None

    # ------------------------------------------------------------------
    # Strategy 3: Crossref alternative-id filter
    # ------------------------------------------------------------------
    doi = _try_crossref_alternative_id(pii)
    if doi:
        return doi

    # ------------------------------------------------------------------
    # Strategy 4: Crossref bibliographic search by PII
    # ------------------------------------------------------------------
    doi = _try_crossref_bibliographic(pii)
    return doi  # may be None


def _try_crossref_alternative_id(pii: str) -> str | None:
    """Query Crossref for works with alternative-id matching the PII.

    Returns the DOI of the first result, or None.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError:
        logger.warning("httpx not available; skipping Crossref alternative-id strategy")
        return None

    try:
        from zotcli.write.resolvers.crossref import _get_user_agent
        ua = _get_user_agent()
    except Exception:
        ua = "zotcli/0.2"

    params = {
        "filter": f"alternative-id:{pii}",
        "rows": 1,
        "select": "DOI,title",
    }
    headers = {"User-Agent": ua}

    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(
                _CROSSREF_BASE, params=params, headers=headers, follow_redirects=True
            )
    except Exception as exc:
        logger.debug("Crossref alternative-id request failed: %s", exc)
        return None

    if resp.status_code != 200:
        logger.debug("Crossref alternative-id returned HTTP %s", resp.status_code)
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    items = data.get("message", {}).get("items", [])
    if not items:
        return None

    doi = items[0].get("DOI", "")
    if doi:
        logger.debug("ScienceDirect: Crossref alternative-id found DOI %s for PII %s", doi, pii)
        return doi
    return None


def _try_crossref_bibliographic(pii: str) -> str | None:
    """Fall back to Crossref bibliographic search using the PII as query text.

    Returns the DOI of the top hit, or None.
    """
    try:
        from zotcli.write.resolvers.crossref import bibliographic_search
    except ImportError:
        return None

    hits = bibliographic_search(pii, rows=1)
    if not hits:
        return None

    doi = hits[0].get("doi", "")
    if doi:
        logger.debug("ScienceDirect: Crossref bibliographic search found DOI %s for PII %s", doi, pii)
        return doi
    return None
