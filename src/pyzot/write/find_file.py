"""Find-file pipeline — Python port of Zotero's ``Find Available PDFs``.

Mirrors the resolver structure from
``zotero/chrome/content/zotero/xpcom/attachments.js``:

  1. ``doi``    → ``https://doi.org/{doi}`` → follow redirects, scrape page
  2. ``url``    → item's URL field          → follow redirects, scrape page
  3. ``oa``     → Zotero OA endpoint        → direct PDF URL or page URL
  4. ``custom`` → user-defined resolvers (config: ``findPDFs.resolvers``)

For each resolver result with a ``url``, the file is downloaded directly.
For results with only a ``pageURL``, the page HTML is scraped for an
``<a href="...pdf">`` (or ``<meta name="citation_pdf_url">``) link and that
URL is then downloaded.

Network strategy:
  - First attempt uses plain ``httpx`` (fast, no browser).
  - If the response is HTML behind a paywall AND a BrowserSession with
    saved cookies covers the host, the request is retried via the browser
    in headless mode.
  - If the headless retry still fails to obtain a PDF AND ``allow_headed``
    is True, the browser opens visibly so the user can solve a captcha
    or complete an institutional login (one-time per session).

All errors are swallowed and logged at DEBUG; the function returns None on
total failure so callers can chain it into a fallback list.
"""

from __future__ import annotations

import html as _html
import logging
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse, urljoin

logger = logging.getLogger("pyzot.find_file")

# A realistic User-Agent string. Many publishers (Akamai-protected MDPI,
# Cloudflare-protected Wiley, Elsevier) 403 on bot-shaped UAs even for OA
# files. Match Zotero's own request fingerprint as closely as we reasonably
# can; the actual Zotero desktop client uses a normal Firefox UA.
_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)
_ACCEPT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}
_MAX_REDIRECTS = 10
_MAX_RESOLVERS = 6  # cap per-call results to avoid Unpaywall pathological cases
_DEFAULT_TIMEOUT_S = 30.0
_PDF_MAGIC = b"%PDF-"

_PDF_LINK_RE = re.compile(
    r'<meta\s+name=["\']citation_pdf_url["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_HREF_PDF_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']',
    re.IGNORECASE,
)
_HREF_PDF_KEYWORD_RE = re.compile(
    r'<a\s+[^>]*href=["\']([^"\']+(?:/pdf|pdfdirect|/pdfft)[^"\']*)["\']',
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class FindFileResult:
    """A successful find-file outcome.

    Attributes
    ----------
    path:
        Local temp file containing the downloaded PDF / EPUB.
        The caller is responsible for moving/copying and deleting it.
    source_url:
        The URL from which the file was downloaded (for provenance).
    access_method:
        Which resolver succeeded: 'doi', 'url', 'oa', 'custom', or
        'browser:<service>' for browser-fetched files.
    content_type:
        MIME type sniffed from the downloaded bytes.
    version:
        OA version (only set when access_method == 'oa').
    """

    path: Path
    source_url: str
    access_method: str
    content_type: str = "application/pdf"
    version: str | None = None


@dataclass
class _ResolverEntry:
    """One step in the resolver pipeline."""

    url: str | None = None  # direct file URL
    page_url: str | None = None  # landing page (scrape for PDF link)
    access_method: str = ""
    version: str | None = None
    referrer: str | None = None


# ---------------------------------------------------------------------------
# Custom-resolver config loader
# ---------------------------------------------------------------------------

def _load_custom_resolvers() -> list[dict]:
    """Load user-defined resolvers from config (``findPDFs.resolvers``).

    The config shape mirrors Zotero's ``findPDFs.resolvers`` pref:
    a list of objects with name / method / url / mode / selector etc.
    Returns [] when absent or malformed.
    """
    try:
        from pyzot.config import get_config_value
        raw = get_config_value("findPDFs.resolvers")
        if not raw:
            return []
        import json as _json
        parsed = _json.loads(raw)
        if isinstance(parsed, dict):
            parsed = [parsed]
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)]
    except Exception as exc:
        logger.debug("Failed to load custom resolvers: %s", exc)
    return []


# ---------------------------------------------------------------------------
# Resolver builder
# ---------------------------------------------------------------------------

def build_resolvers(
    *,
    doi: str | None,
    item_url: str | None,
    methods: tuple[str, ...] = ("doi", "url", "oa", "custom"),
) -> list[_ResolverEntry]:
    """Return resolver entries in priority order for *doi* / *item_url*.

    Empty or invalid inputs are skipped. The order matches Zotero's default
    ``methods = ['doi', 'url', 'oa', 'custom']``.
    """
    entries: list[_ResolverEntry] = []
    doi = (doi or "").strip()
    item_url = (item_url or "").strip()

    if "doi" in methods and doi:
        entries.append(_ResolverEntry(
            page_url=f"https://doi.org/{doi}",
            access_method="doi",
        ))

    if "url" in methods and item_url:
        entries.append(_ResolverEntry(
            page_url=item_url,
            access_method="url",
        ))

    if "oa" in methods and doi:
        from pyzot.write.oa_search import search_oa
        try:
            for oa in search_oa(doi)[:_MAX_RESOLVERS]:
                entries.append(_ResolverEntry(
                    url=oa.url,
                    page_url=oa.page_url,
                    access_method="oa",
                    version=oa.version,
                ))
        except Exception as exc:
            logger.debug("OA search failed: %s", exc)

    if "custom" in methods and doi:
        for spec in _load_custom_resolvers():
            try:
                url = (spec.get("url") or "").replace("{doi}", doi)
                if not url:
                    continue
                entries.append(_ResolverEntry(
                    page_url=url,
                    access_method=spec.get("name", "custom"),
                ))
            except Exception as exc:
                logger.debug("Skipping bad custom resolver: %s", exc)

    return entries


# ---------------------------------------------------------------------------
# Core: download driver
# ---------------------------------------------------------------------------

def find_file(
    *,
    doi: str | None = None,
    item_url: str | None = None,
    methods: tuple[str, ...] = ("doi", "url", "oa", "custom"),
    allow_browser: bool = True,
    allow_headed: bool = True,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> FindFileResult | None:
    """Try to download a PDF/EPUB for *doi* and/or *item_url*.

    Runs through the 4-resolver pipeline (`build_resolvers`) and returns the
    first successful download as a :class:`FindFileResult` referencing a
    local temp file. Returns None if nothing was found.

    Parameters
    ----------
    doi:
        Item DOI (used by doi / oa / custom resolvers).
    item_url:
        Item URL field (used by the url resolver, also scraped for PDF link).
    methods:
        Subset of resolvers to enable. Defaults to all four, like Zotero.
    allow_browser:
        If True (default), fall back to BrowserSession with saved cookies
        when plain HTTP returns HTML behind a paywall.
    allow_headed:
        If True (default), open a visible browser window when even the
        cookied headless attempt fails (so the user can solve a captcha or
        log in interactively). Set False for non-interactive scripts.
    timeout_s:
        Per-request timeout. The overall call may take much longer because
        it walks the resolver list.
    """
    entries = build_resolvers(doi=doi, item_url=item_url, methods=methods)
    if not entries:
        return None

    tried: set[str] = set()

    for entry in entries:
        # --- direct URL ---
        if entry.url and entry.url not in tried:
            tried.add(entry.url)
            result = _try_download(
                entry.url,
                access_method=entry.access_method,
                version=entry.version,
                allow_browser=allow_browser,
                allow_headed=allow_headed,
                timeout_s=timeout_s,
            )
            if result is not None:
                return result

        # --- pageURL: fetch HTML, look for PDF link, download ---
        if entry.page_url and entry.page_url not in tried:
            tried.add(entry.page_url)
            pdf_url = _scrape_pdf_url_from_page(
                entry.page_url,
                allow_browser=allow_browser,
                allow_headed=allow_headed,
                timeout_s=timeout_s,
            )
            if pdf_url and pdf_url not in tried:
                tried.add(pdf_url)
                result = _try_download(
                    pdf_url,
                    access_method=entry.access_method,
                    version=entry.version,
                    referrer=entry.page_url,
                    allow_browser=allow_browser,
                    allow_headed=allow_headed,
                    timeout_s=timeout_s,
                )
                if result is not None:
                    return result

    return None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _try_download(
    url: str,
    *,
    access_method: str,
    version: str | None = None,
    referrer: str | None = None,
    allow_browser: bool = True,
    allow_headed: bool = True,
    timeout_s: float = _DEFAULT_TIMEOUT_S,
) -> FindFileResult | None:
    """Download *url* to a temp file and return a result if it's a PDF/EPUB."""
    # 1) Plain httpx
    payload = _http_get_pdf(url, referrer=referrer, timeout_s=timeout_s)
    if payload is not None:
        return _save_payload(payload, url, access_method, version)

    if not allow_browser:
        return None

    # 2) Browser fallback if a known service owns the host
    from pyzot.write.browser import (
        BrowserFetchError,
        BrowserSession,
        is_browser_extra_installed,
        service_for_url,
    )

    service = service_for_url(url)
    if service is None or not is_browser_extra_installed():
        return None

    sess = BrowserSession(service)
    # The "default" service is cookieless (stealth-browser stand-in for OA
    # sites with bot protection); named services require a saved login.
    if service != "default" and not sess.cookies_exist():
        logger.debug("No cookies saved for service %s; skipping browser fallback", service)
        return None

    # 2a) Headless first
    try:
        pdf_bytes = sess.fetch(url, timeout_s=timeout_s, headless=True)
        if isinstance(pdf_bytes, bytes) and pdf_bytes.startswith(_PDF_MAGIC):
            return _save_payload(pdf_bytes, url, f"browser:{service}", version)
    except (BrowserFetchError, Exception) as exc:
        logger.debug("Headless browser fetch failed for %s: %s", url, exc)

    if not allow_headed:
        return None

    # 2b) Headed escalation — only for named (cookied) services.
    # For "default" there is no login that headed-mode could complete, so
    # we skip the escalation to avoid pointlessly popping a browser window.
    if service == "default":
        return None

    try:
        import click
        click.echo(
            f"[find-file] Opening browser to retrieve PDF from {url} "
            f"(service: {service}). Sign in or solve captcha if prompted.",
            err=True,
        )
    except ImportError:
        pass
    try:
        pdf_bytes = sess.fetch(url, timeout_s=max(timeout_s, 120.0), headless=False)
        if isinstance(pdf_bytes, bytes) and pdf_bytes.startswith(_PDF_MAGIC):
            return _save_payload(pdf_bytes, url, f"browser:{service}", version)
    except BrowserFetchError as exc:
        logger.debug("Headed browser fetch failed for %s: %s", url, exc)
    except Exception as exc:
        logger.debug("Headed browser fetch error for %s: %s", url, exc)

    return None


def _http_get_pdf(url: str, *, referrer: str | None = None, timeout_s: float) -> bytes | None:
    """Plain httpx GET. Returns bytes only if response looks like a PDF/EPUB."""
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not installed; cannot fetch %s", url)
        return None

    headers = {"User-Agent": _USER_AGENT, **_ACCEPT_HEADERS}
    if referrer:
        headers["Referer"] = referrer
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("HTTP GET failed for %s: %s", url, exc)
        return None

    if resp.status_code >= 400:
        logger.debug("HTTP %s for %s", resp.status_code, url)
        return None

    body = resp.content
    if not body:
        return None

    # Validate by magic bytes — Content-Type is unreliable
    if body[:5] == _PDF_MAGIC:
        return body
    if body[:4] == b"PK\x03\x04":  # could be EPUB
        # Loose EPUB check; sniff_mime handles deeper validation later
        return body

    return None


def _save_payload(
    payload: bytes,
    source_url: str,
    access_method: str,
    version: str | None,
) -> FindFileResult:
    """Write bytes to a NamedTemporaryFile and wrap in a FindFileResult."""
    suffix = ".pdf"
    if payload[:4] == b"PK\x03\x04":
        suffix = ".epub"
    fd = tempfile.NamedTemporaryFile(prefix="pyzot_findfile_", suffix=suffix, delete=False)
    try:
        fd.write(payload)
    finally:
        fd.close()
    path = Path(fd.name)

    # Sniff for final content_type
    content_type = "application/pdf"
    if suffix == ".epub":
        content_type = "application/epub+zip"

    logger.info(
        "find_file: downloaded %d bytes from %s via %s",
        len(payload), source_url, access_method,
    )
    return FindFileResult(
        path=path,
        source_url=source_url,
        access_method=access_method,
        content_type=content_type,
        version=version,
    )


def _scrape_pdf_url_from_page(
    page_url: str,
    *,
    allow_browser: bool,
    allow_headed: bool,
    timeout_s: float,
) -> str | None:
    """Fetch *page_url* and extract a PDF link from the HTML.

    Looks for ``<meta name="citation_pdf_url" content="...">`` first
    (Google Scholar convention, supported by most journal sites), then
    falls back to ``<a href="*.pdf">`` and ``<a href="*pdf*">`` patterns.

    Falls back to BrowserSession HTML render when plain HTTP is blocked.
    """
    html = _http_get_html(page_url, timeout_s=timeout_s)
    if html is None and allow_browser:
        # Try cookied browser for paywalled landing pages
        try:
            from pyzot.write.browser import (
                BrowserSession,
                is_browser_extra_installed,
                service_for_url,
            )
            service = service_for_url(page_url)
            if service and is_browser_extra_installed():
                sess = BrowserSession(service)
                if sess.cookies_exist():
                    html = sess.fetch_html(page_url, timeout_s=timeout_s)
        except Exception as exc:
            logger.debug("Browser fetch_html failed: %s", exc)

    if not html:
        return None

    return _extract_pdf_url(html, page_url)


def _http_get_html(url: str, *, timeout_s: float) -> str | None:
    """Plain httpx GET for HTML. Returns text or None."""
    try:
        import httpx
    except ImportError:
        return None
    headers = {"User-Agent": _USER_AGENT, **_ACCEPT_HEADERS}
    try:
        with httpx.Client(timeout=timeout_s, follow_redirects=True) as client:
            resp = client.get(url, headers=headers)
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.debug("HTTP GET (html) failed for %s: %s", url, exc)
        return None
    if resp.status_code >= 400:
        return None
    ct = resp.headers.get("content-type", "").lower()
    if "html" not in ct and "xml" not in ct and "text" not in ct:
        return None
    try:
        return resp.text
    except Exception:
        return None


def _extract_pdf_url(html: str, base_url: str) -> str | None:
    """Find the first plausible PDF URL in *html*.

    Search order matches Zotero's heuristics:
    1. ``citation_pdf_url`` meta tag
    2. ``<a href="...*.pdf">``
    3. ``<a href="...{pdf,pdfdirect,pdfft}...">`` (common journal patterns)
    """
    m = _PDF_LINK_RE.search(html)
    if m:
        return _absolute(_html.unescape(m.group(1)), base_url)
    m = _HREF_PDF_RE.search(html)
    if m:
        return _absolute(_html.unescape(m.group(1)), base_url)
    m = _HREF_PDF_KEYWORD_RE.search(html)
    if m:
        return _absolute(_html.unescape(m.group(1)), base_url)
    return None


def _absolute(url: str, base: str) -> str:
    """Resolve a (possibly relative) URL against a base."""
    if not url:
        return url
    if url.startswith(("http://", "https://")):
        return url
    return urljoin(base, url)
