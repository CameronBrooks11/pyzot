"""Open-access PDF lookup via Zotero's Unpaywall mirror.

Calls ``POST https://services.zotero.org/oa/search`` with a DOI and returns
the array of ``{url, pageURL, version}`` records. This is the same endpoint
that Zotero's "Find Available PDFs" feature uses internally
(see ``utilities_internal.js::getOpenAccessPDFURLs``).

The endpoint is documented in the Zotero source as a private API:
*"Please use Unpaywall directly for non-Zotero projects."* We use it because
we are replicating Zotero's UX inside a CLI; for high-volume non-interactive
usage, switch to Unpaywall directly via ``write/resolvers/unpaywall.py``.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from dataclasses import dataclass

logger = logging.getLogger("zotcli.oa_search")

_OA_SEARCH_URL = "https://services.zotero.org/oa/search"
_DEFAULT_TIMEOUT_S = 10.0


@dataclass
class OAResult:
    """One open-access record returned by the Zotero OA endpoint.

    Either ``url`` (direct PDF URL) or ``page_url`` (landing page where the
    PDF link must be scraped) will be present; sometimes both.
    """

    url: str | None
    page_url: str | None
    version: str | None  # 'submittedVersion' | 'acceptedVersion' | 'publishedVersion'


def search_oa(doi: str, *, timeout_s: float = _DEFAULT_TIMEOUT_S) -> list[OAResult]:
    """Return open-access records for *doi*, or [] if none are found.

    Network errors and HTTP failures return [] (logged at DEBUG); they do not
    raise, so callers can safely include this in a fallback chain.
    """
    doi = (doi or "").strip()
    if not doi:
        return []

    payload = json.dumps({"doi": doi}).encode()
    req = urllib.request.Request(
        _OA_SEARCH_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            raw = resp.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        logger.debug("OA search failed for %r: %s", doi, exc)
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.debug("OA search returned non-JSON for %r: %s", doi, exc)
        return []

    if not isinstance(data, list):
        return []

    out: list[OAResult] = []
    for entry in data:
        if not isinstance(entry, dict):
            continue
        out.append(OAResult(
            url=entry.get("url") or None,
            page_url=entry.get("pageURL") or None,
            version=entry.get("version") or None,
        ))
    logger.debug("OA search %r: %d results", doi, len(out))
    return out
