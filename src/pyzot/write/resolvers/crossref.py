"""Crossref resolver — DOI → CSL-JSON.

GET https://api.crossref.org/works/{doi}

User-Agent is read from config (key: resolvers.crossref_user_agent).
On 404: raises IdentifierNotFound.
On 429: sleep + retry once.
On 5xx: retry up to 2 times with exponential backoff.
"""

from __future__ import annotations

import logging
import time

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.crossref.org/works"


def resolve(doi: str) -> dict:
    """Fetch metadata for *doi* from Crossref and return a CSL-JSON dict.

    Parameters
    ----------
    doi:
        A normalised DOI string (e.g. ``"10.1038/example"``).

    Returns
    -------
    dict
        A CSL-JSON record extracted from the Crossref ``message`` payload.

    Raises
    ------
    IdentifierNotFound
        If Crossref returns 404 for the given DOI.
    RuntimeError
        If all retry attempts fail with 5xx or other errors.
    """
    from pyzot.write.resolvers import IdentifierNotFound
    from pyzot.write.resolvers._http import headers, require_httpx

    httpx = require_httpx()
    url = f"{_BASE_URL}/{doi}"
    request_headers = headers()
    max_retries = 2

    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(0.5 * (2 ** (attempt - 1)))

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(url, headers=request_headers, follow_redirects=True)
        except Exception as exc:
            if attempt == max_retries:
                raise RuntimeError(f"Failed to reach Crossref for DOI '{doi}': {exc}") from exc
            continue

        if resp.status_code == 200:
            data = resp.json()
            # Crossref wraps the item in {"status": "ok", "message": {...}}
            message = data.get("message", data)
            logger.debug("Crossref resolved DOI %s: type=%s", doi, message.get("type"))
            return message

        if resp.status_code == 404:
            raise IdentifierNotFound("doi", doi, "Crossref returned 404")

        if resp.status_code == 429:
            # Rate limited — wait and retry once
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning("Crossref rate-limited; sleeping %ss", retry_after)
            time.sleep(retry_after)
            if attempt == max_retries:
                raise RuntimeError(f"Crossref rate limit exceeded for DOI '{doi}'")
            continue

        if resp.status_code >= 500:
            logger.warning("Crossref returned %s for DOI %s; retrying", resp.status_code, doi)
            if attempt == max_retries:
                raise RuntimeError(
                    f"Crossref returned {resp.status_code} for DOI '{doi}' after {max_retries + 1} attempts"
                )
            continue

        # Other 4xx
        raise RuntimeError(
            f"Crossref returned unexpected HTTP {resp.status_code} for DOI '{doi}': {resp.text[:200]}"
        )

    raise RuntimeError(f"Crossref: exhausted retries for DOI '{doi}'")


def bibliographic_search(text: str, rows: int = 5) -> list[dict]:
    """Search Crossref by free-text bibliographic query.

    GET https://api.crossref.org/works?query.bibliographic=<text>&rows=<rows>
        &select=DOI,title,author,issued,container-title,score,type

    Parameters
    ----------
    text:
        Free-text citation string or title query.
    rows:
        Maximum number of results to request (default 5).

    Returns
    -------
    list[dict]
        Normalized hit dicts, each with keys:
        ``doi``, ``title``, ``authors``, ``year``, ``score``,
        ``container_title``, ``type``.
        Hits without a DOI are included but their ``doi`` will be empty string.
        Results are returned in Crossref's own relevance order.

    Notes
    -----
    On network failure, 429, or 5xx, returns ``[]`` (soft fail after one retry).
    """
    from pyzot.write.resolvers._http import headers, require_httpx

    httpx = require_httpx("Crossref")
    params = {
        "query.bibliographic": text,
        "rows": rows,
        "select": "DOI,title,author,issued,container-title,score,type",
    }
    request_headers = headers()

    max_retries = 1
    for attempt in range(max_retries + 1):
        if attempt > 0:
            time.sleep(2)

        try:
            with httpx.Client(timeout=15.0) as client:
                resp = client.get(
                    _BASE_URL,
                    params=params,
                    headers=request_headers,
                    follow_redirects=True,
                )
        except Exception as exc:
            logger.warning("Crossref bibliographic search failed (network error): %s", exc)
            return []

        if resp.status_code == 200:
            break

        if resp.status_code == 429:
            retry_after = int(resp.headers.get("Retry-After", "5"))
            logger.warning("Crossref rate-limited on search; sleeping %ss", retry_after)
            time.sleep(retry_after)
            if attempt == max_retries:
                logger.warning("Crossref bibliographic search rate-limited; giving up")
                return []
            continue

        logger.warning("Crossref bibliographic search returned HTTP %s", resp.status_code)
        return []

    try:
        data = resp.json()
    except Exception:
        return []

    items = data.get("message", {}).get("items", [])

    hits = []
    for item in items:
        doi = item.get("DOI", "")

        # title is a list in Crossref
        title_raw = item.get("title", [])
        title = title_raw[0] if isinstance(title_raw, list) and title_raw else str(title_raw)

        # authors
        authors = []
        for a in item.get("author", []):
            family = a.get("family", "")
            given = a.get("given", "")
            if family:
                authors.append(f"{given} {family}".strip() if given else family)

        # year
        issued = item.get("issued", {})
        date_parts = issued.get("date-parts", [[]])
        year = date_parts[0][0] if date_parts and date_parts[0] else None

        # container-title
        ct_raw = item.get("container-title", [])
        container_title = ct_raw[0] if isinstance(ct_raw, list) and ct_raw else str(ct_raw)

        score = item.get("score")

        hits.append(
            {
                "doi": doi,
                "title": title,
                "authors": authors,
                "year": year,
                "score": score,
                "container_title": container_title,
                "type": item.get("type", ""),
            }
        )

    logger.debug(
        "Crossref bibliographic search returned %d hits for query: %s", len(hits), text[:80]
    )
    return hits
