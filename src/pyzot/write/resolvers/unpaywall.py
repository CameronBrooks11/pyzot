"""Unpaywall resolver — DOI → open-access PDF URL.

Unpaywall (unpaywall.org) provides a free API for finding legal, open-access
versions of academic papers by DOI.

IMPORTANT: Unpaywall requires an email address per their fair-use policy.
Do NOT use this module without a valid email configured via
`zot add login --service unpaywall`.

API docs: https://unpaywall.org/products/api
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def resolve(doi: str, email: str) -> dict | None:
    """GET https://api.unpaywall.org/v2/{doi}?email={email}.

    Parameters
    ----------
    doi:
        The DOI to look up (e.g. ``"10.1038/s41586-020-2649-2"``).
    email:
        The caller's email address (required by Unpaywall fair-use policy).

    Returns
    -------
    dict | None
        Parsed JSON response if the paper has an open-access version
        (``is_oa=True``), or ``None`` if the paper is paywalled or not found.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "The 'write' extra is required for Unpaywall resolver. "
            "Install it with: pip install \"pyzot[write]\""
        ) from exc

    url = f"https://api.unpaywall.org/v2/{doi}"
    params = {"email": email}

    logger.debug("Unpaywall GET %s (email=%s)", url, email)

    try:
        with httpx.Client(timeout=15.0) as client:
            response = client.get(url, params=params)
    except Exception as exc:
        logger.warning("Unpaywall request failed for DOI %s: %s", doi, exc)
        raise

    if response.status_code == 404:
        logger.debug("Unpaywall: DOI not found: %s", doi)
        return None

    if response.status_code != 200:
        logger.warning(
            "Unpaywall returned HTTP %d for DOI %s", response.status_code, doi
        )
        return None

    data = response.json()
    logger.debug("Unpaywall response: is_oa=%s", data.get("is_oa"))

    if not data.get("is_oa", False):
        return None

    return data


def find_oa_pdf_url(doi: str, email: str) -> str | None:
    """Find the first reachable open-access PDF URL for a given DOI.

    Checks ``best_oa_location.url_for_pdf`` first, then all
    ``oa_locations[].url_for_pdf`` entries. Returns the first URL that
    responds with HTTP 200 to a HEAD request.

    Parameters
    ----------
    doi:
        The DOI to look up.
    email:
        The caller's email address (required by Unpaywall fair-use policy).

    Returns
    -------
    str | None
        A reachable PDF URL, or ``None`` if no open-access PDF is available.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            "The 'write' extra is required for Unpaywall resolver. "
            "Install it with: pip install \"pyzot[write]\""
        ) from exc

    data = resolve(doi, email)
    if data is None:
        return None

    # Collect candidate PDF URLs in priority order
    candidates: list[str] = []

    # 1. best_oa_location
    best = data.get("best_oa_location") or {}
    best_pdf = best.get("url_for_pdf")
    if best_pdf:
        candidates.append(best_pdf)

    # 2. All other oa_locations
    for loc in data.get("oa_locations", []):
        pdf_url = loc.get("url_for_pdf")
        if pdf_url and pdf_url not in candidates:
            candidates.append(pdf_url)

    if not candidates:
        logger.debug("Unpaywall: is_oa=True but no url_for_pdf found for DOI %s", doi)
        return None

    # HEAD-check each candidate to verify reachability
    with httpx.Client(timeout=10.0, follow_redirects=True) as client:
        for url in candidates:
            try:
                resp = client.head(
                    url,
                    headers={"User-Agent": "pyzot/0.2 (mailto:pyzot@local)"},
                )
                if resp.status_code == 200:
                    logger.debug("Unpaywall: reachable PDF URL: %s", url)
                    return url
                logger.debug(
                    "Unpaywall: URL %s returned HTTP %d (skipping)", url, resp.status_code
                )
            except Exception as exc:
                logger.debug("Unpaywall: HEAD check failed for %s: %s", url, exc)
                continue

    logger.debug("Unpaywall: no reachable PDF URL found for DOI %s", doi)
    return None
