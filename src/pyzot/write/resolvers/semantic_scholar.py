"""Semantic Scholar resolver — citation/title search fallback.

GET https://api.semanticscholar.org/graph/v1/paper/search?query=<text>&limit=N&fields=externalIds,title,authors,year

Rate limit: up to 100 requests/5 min (unauthenticated). On 429, sleep 2s + retry once;
on second 429 give up softly (return []).

Optional API key via config key ``resolvers.semantic_scholar_api_key`` →
sent as ``x-api-key`` header.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.semanticscholar.org/graph/v1"
_SEARCH_FIELDS = "externalIds,title,authors,year"


def _get_api_key() -> str | None:
    """Return the Semantic Scholar API key from config, or None."""
    try:
        from pyzot.config import get_config_value

        key = get_config_value("resolvers.semantic_scholar_api_key")
        return key or None
    except Exception:
        return None


def search(text: str, limit: int = 5) -> list[dict]:
    """Search Semantic Scholar for works matching *text*.

    Parameters
    ----------
    text:
        Free-text query (citation string, title, etc.).
    limit:
        Maximum number of results to return (default 5).

    Returns
    -------
    list[dict]
        Normalized hit dicts with keys: doi, title, authors, year.
        Hits without a DOI (in ``externalIds.DOI``) are filtered out.

    Notes
    -----
    Rate limit behaviour:
    - On 429: sleep 2 s and retry once.
    - On second 429: give up and return ``[]`` (soft fail).
    - On other network / HTTP errors: log warning and return ``[]``.
    """
    from pyzot.write.resolvers._http import headers as default_headers
    from pyzot.write.resolvers._http import require_httpx

    httpx = require_httpx("Semantic Scholar")
    params = {
        "query": text,
        "limit": limit,
        "fields": _SEARCH_FIELDS,
    }
    headers = default_headers()
    api_key = _get_api_key()
    if api_key:
        headers["x-api-key"] = api_key

    max_attempts = 2  # 1 initial + 1 retry on 429

    for attempt in range(max_attempts):
        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    f"{_BASE_URL}/paper/search",
                    params=params,
                    headers=headers,
                    follow_redirects=True,
                )
        except Exception as exc:
            logger.warning("Semantic Scholar search failed (network error): %s", exc)
            return []

        if resp.status_code == 200:
            break

        if resp.status_code == 429:
            if attempt < max_attempts - 1:
                retry_after = int(resp.headers.get("Retry-After", "2"))
                logger.warning(
                    "Semantic Scholar rate-limited; sleeping %ss before retry", retry_after
                )
                time.sleep(retry_after)
                continue
            else:
                # Second 429 — give up softly
                logger.warning(
                    "Semantic Scholar rate limit exceeded after %d attempts; giving up",
                    max_attempts,
                )
                return []

        # Other non-200 response
        logger.warning("Semantic Scholar search returned HTTP %s", resp.status_code)
        return []

    data = resp.json()
    papers = data.get("data", [])

    hits = []
    for paper in papers:
        external_ids = paper.get("externalIds") or {}
        doi = external_ids.get("DOI")
        if not doi:
            continue  # filter out hits with no DOI

        authors = [a.get("name", "") for a in (paper.get("authors") or []) if a.get("name")]

        hits.append(
            {
                "doi": doi,
                "title": paper.get("title") or "",
                "authors": authors,
                "year": paper.get("year"),
            }
        )

    logger.debug(
        "Semantic Scholar search returned %d usable hits for query: %s", len(hits), text[:80]
    )
    return hits
