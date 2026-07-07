"""IEEE Xplore URL → DOI resolver.

url_to_doi(url: str) -> str | None

Tries in order:
1. Regex-extract a DOI directly from the URL or its query string.
2. Extract the IEEE arnumber and fetch the public metadata endpoint
   ``https://ieeexplore.ieee.org/rest/document/<arnumber>/metadata``
   (no API key required for basic fields). Soft-fail on 401/403/404.
3. Crossref reverse search: bibliographic_search(arnumber); accept
   only if score >= threshold (default 50).

No browser / Playwright used. All network calls use httpx (lazily imported).

Soft-fail behaviour
-------------------
If every strategy fails (network error, 401, 403, 404, no high-confidence
Crossref match) the function returns ``None`` so the caller can fall back
to the saveSnapshot path.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Compiled regexes
# ---------------------------------------------------------------------------

# DOI in path, e.g. /doi/10.1109/TPWRS.2023.1234567
_DOI_IN_PATH = re.compile(
    r"(?:^|[/?&])(?:doi/|DOI=)?(10\.\d{4,9}/[^\s?&#\"'<>]+)",
    re.IGNORECASE,
)

# arnumber in path like /document/<arnumber>
_ARNUMBER_PATH = re.compile(
    r"/document/(\d+)(?:[/?#]|$)",
    re.IGNORECASE,
)

# arnumber in query string ?arnumber=<n>
_ARNUMBER_QUERY = re.compile(r"arnumber=(\d+)", re.IGNORECASE)

_IEEE_METADATA_BASE = "https://ieeexplore.ieee.org/rest/document"

# Default Crossref score threshold for reverse-search acceptance
_DEFAULT_SCORE_THRESHOLD = 50


def url_to_doi(url: str, score_threshold: int = _DEFAULT_SCORE_THRESHOLD) -> str | None:
    """Resolve an IEEE Xplore URL to a DOI.

    Parameters
    ----------
    url:
        An IEEE Xplore article URL, e.g.
        ``https://ieeexplore.ieee.org/document/9876543``
    score_threshold:
        Minimum Crossref relevance score to accept a reverse-search result
        (default 50). Configurable via ``resolvers.ieee_crossref_threshold``.

    Returns
    -------
    str or None
        A DOI string (e.g. ``"10.1109/TPWRS.2023.1234567"``), or ``None``
        if no DOI could be resolved.

    Notes
    -----
    - Strategy 3 (Crossref reverse search) is only tried when strategies 1
      and 2 fail.
    - On 401/403/404 from the IEEE metadata endpoint, the function soft-fails
      and falls through to strategy 3 rather than raising.
    - All network I/O uses httpx with a 10 s timeout.
    """
    # Try to read threshold from config
    try:
        from zotcli.config import get_config_value
        cfg_threshold = get_config_value("resolvers.ieee_crossref_threshold")
        if cfg_threshold is not None:
            try:
                score_threshold = int(cfg_threshold)
            except (TypeError, ValueError):
                pass
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Strategy 1: Regex-extract DOI from the URL itself
    # ------------------------------------------------------------------
    m = _DOI_IN_PATH.search(url)
    if m:
        doi = m.group(1).rstrip(".")  # strip trailing dot that can appear in URLs
        logger.debug("IEEE: found DOI in URL via regex: %s", doi)
        return doi

    # Also check query parameters for doi=...
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=False)
    for key in ("doi", "DOI"):
        vals = qs.get(key, [])
        if vals:
            doi = vals[0].rstrip(".")
            logger.debug("IEEE: found DOI in query param: %s", doi)
            return doi

    # ------------------------------------------------------------------
    # Extract arnumber for strategies 2 & 3
    # ------------------------------------------------------------------
    arnumber: str | None = None

    m2 = _ARNUMBER_PATH.search(url)
    if m2:
        arnumber = m2.group(1)
    else:
        m3 = _ARNUMBER_QUERY.search(url)
        if m3:
            arnumber = m3.group(1)

    if arnumber is None:
        logger.debug("IEEE: could not extract arnumber from URL: %s", url)
        return None

    # ------------------------------------------------------------------
    # Strategy 2: IEEE public metadata REST endpoint
    # ------------------------------------------------------------------
    doi = _try_ieee_metadata(arnumber)
    if doi:
        return doi

    # ------------------------------------------------------------------
    # Strategy 3: Crossref reverse search by arnumber
    # ------------------------------------------------------------------
    doi = _try_crossref_reverse(arnumber, score_threshold)
    return doi  # may be None


def _try_ieee_metadata(arnumber: str) -> str | None:
    """Fetch IEEE public metadata endpoint and return DOI or None.

    Soft-fails (returns None) on 401, 403, 404, network errors, or missing DOI.
    """
    try:
        import httpx  # type: ignore[import]
    except ImportError:
        logger.warning("httpx not available; skipping IEEE metadata strategy")
        return None

    url = f"{_IEEE_METADATA_BASE}/{arnumber}/metadata"
    try:
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, follow_redirects=True)
    except Exception as exc:
        logger.debug("IEEE metadata request failed (network error): %s", exc)
        return None

    if resp.status_code in (401, 403, 404):
        logger.debug("IEEE metadata endpoint returned %s for arnumber %s; soft-failing", resp.status_code, arnumber)
        return None

    if resp.status_code != 200:
        logger.debug("IEEE metadata endpoint returned unexpected HTTP %s", resp.status_code)
        return None

    try:
        data = resp.json()
    except Exception:
        return None

    # The response may be a list or a dict
    if isinstance(data, list):
        if not data:
            return None
        data = data[0]

    doi = data.get("doi") or data.get("DOI")
    if doi:
        logger.debug("IEEE metadata: found DOI %s for arnumber %s", doi, arnumber)
        return str(doi).strip()

    return None


def _try_crossref_reverse(arnumber: str, score_threshold: int) -> str | None:
    """Try to resolve arnumber to a DOI via Crossref bibliographic search.

    Accepts the top hit only if its score >= score_threshold.
    Returns the DOI or None.
    """
    try:
        from zotcli.write.resolvers.crossref import bibliographic_search
    except ImportError:
        return None

    hits = bibliographic_search(arnumber, rows=5)
    if not hits:
        return None

    top = hits[0]
    score = top.get("score")
    doi = top.get("doi", "")

    if not doi:
        return None

    if score is not None and score < score_threshold:
        logger.debug(
            "IEEE Crossref reverse: top hit score %.1f < threshold %d; rejecting",
            score,
            score_threshold,
        )
        return None

    logger.debug("IEEE Crossref reverse: accepted DOI %s (score=%s)", doi, score)
    return doi
