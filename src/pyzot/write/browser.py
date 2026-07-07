"""Playwright-powered browser session for paywalled content.

All Playwright imports are **lazy** — they occur only inside function bodies,
never at module top-level.  This ensures that ``import pyzot`` never pulls
in the ``playwright`` package.  The ``[browser]`` optional extra must be
installed separately:

    pip install "pyzot[browser]"

Classes
-------
BrowserSession
    Wraps a persistent Chromium profile for a given service (``ieee``,
    ``sciencedirect``).  ``login()`` opens a headed window so the user can
    authenticate; ``fetch()`` reuses the saved cookies in headless mode to
    download PDFs.

Exceptions
----------
BrowserFetchError
    Raised when a URL cannot be fetched as a PDF/EPUB (wrong Content-Type,
    download failure, etc.).

Helpers
-------
is_browser_extra_installed() -> bool
    Returns ``True`` when the ``playwright`` package is importable.

install_browser() -> None
    Runs ``playwright install chromium`` via ``subprocess.run``.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("pyzot.browser")


class BrowserFetchError(RuntimeError):
    """Raised when a browser fetch does not yield a valid PDF/EPUB."""


def is_browser_extra_installed() -> bool:
    """Return True if the playwright package is importable.

    Returns False if playwright is not installed (i.e. the ``[browser]``
    optional extra is absent).
    """
    try:
        import playwright.sync_api  # noqa: F401  # type: ignore[import]
        return True
    except ImportError:
        return False


def install_browser() -> None:
    """Install the Chromium browser via ``playwright install chromium``.

    Runs the command in a subprocess and streams its output to stdout/stderr.
    Raises ``RuntimeError`` if the command fails.
    """
    logger.info("Running: playwright install chromium")
    result = subprocess.run(
        ["playwright", "install", "chromium"],
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"playwright install chromium failed with exit code {result.returncode}."
        )


# ---------------------------------------------------------------------------
# Service-specific login configuration
# ---------------------------------------------------------------------------

_SERVICE_CONFIG: dict[str, dict] = {
    "ieee": {
        "landing_url": "https://ieeexplore.ieee.org/Xplore/home.jsp",
        "display_name": "IEEE Xplore",
        "domains": ("ieeexplore.ieee.org",),
    },
    "sciencedirect": {
        "landing_url": "https://www.sciencedirect.com/",
        "display_name": "ScienceDirect",
        "domains": ("sciencedirect.com", "linkinghub.elsevier.com"),
    },
    # "default" is a cookieless real-browser profile used as a stealth
    # fallback for sites that bot-block plain HTTP (MDPI, Wiley, ...) but
    # are otherwise OA. No login flow — just a real Chromium fingerprint.
    "default": {
        "landing_url": "about:blank",
        "display_name": "Default browser",
        "domains": (),
    },
}


def service_for_url(url: str) -> str | None:
    """Map a URL to the BrowserSession service name that owns its cookies.

    Returns one of the named cookied services (``"ieee"``, ``"sciencedirect"``)
    if a saved login covers the URL's host, otherwise ``"default"`` which is
    a cookieless stealth-browser profile suitable for OA sites with bot
    protection (MDPI, Wiley, etc.).
    """
    from urllib.parse import urlparse
    try:
        host = (urlparse(url).hostname or "").lower()
    except Exception:
        return None
    if not host:
        return None
    for name, cfg in _SERVICE_CONFIG.items():
        if name == "default":
            continue
        for domain in cfg.get("domains", ()):
            if host == domain or host.endswith("." + domain):
                return name
    return "default"


class BrowserSession:
    """Playwright session for a specific service.

    Parameters
    ----------
    service:
        One of ``"ieee"`` or ``"sciencedirect"``.  The string is used as the
        subdirectory name under ``<pyzot-home>/cookies/<service>/`` for the
        persistent browser profile.
    """

    def __init__(self, service: str) -> None:
        self.service = service
        from pyzot.paths import cookies_root
        self.profile_dir: Path = cookies_root() / service
        self.profile_dir.mkdir(parents=True, exist_ok=True)

    def login(self) -> dict:
        """Open a headed Chromium window so the user can authenticate.

        The browser uses a persistent profile at ``self.profile_dir`` so
        cookies and session state survive across runs.  When the user has
        finished signing in, they press ``<Enter>`` in the terminal to save
        the session and close the browser.

        Returns
        -------
        dict
            ``{"service": str, "logged_in_at": str}`` on success.

        Raises
        ------
        ImportError
            If playwright is not installed.
        ValueError
            If *service* is not ``"ieee"`` or ``"sciencedirect"``.
        """
        from datetime import datetime, timezone

        if not is_browser_extra_installed():
            raise ImportError(
                "Browser support is not installed. "
                'Install it with: pip install "pyzot[browser]"'
            )

        if self.service not in _SERVICE_CONFIG:
            raise ValueError(
                f"Unknown service {self.service!r}. "
                f"Supported: {sorted(_SERVICE_CONFIG)}"
            )

        cfg = _SERVICE_CONFIG[self.service]
        landing_url = cfg["landing_url"]
        display_name = cfg["display_name"]

        # Lazy import — only when this method is actually called
        from playwright.sync_api import sync_playwright  # type: ignore[import]

        logger.info(
            "Opening headed Chromium for %s (profile: %s)", display_name, self.profile_dir
        )

        with sync_playwright() as p:
            # Use a persistent context so cookies survive
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=False,
                args=["--no-first-run", "--disable-blink-features=AutomationControlled"],
            )
            page = context.new_page()
            page.goto(landing_url, wait_until="domcontentloaded", timeout=30_000)
            logger.info("Navigated to %s", landing_url)

            # Terminal confirmation — most reliable cross-service heuristic
            print(
                f"\n[pyzot] Opened {display_name} in Chromium.\n"
                f"         Sign in using your institutional SSO or account credentials.\n"
                f"         When you are fully signed in, press <Enter> here to save "
                f"your session and close the browser.",
                flush=True,
            )
            try:
                input()
            except EOFError:
                # Non-interactive environment — proceed anyway
                pass

            # Persist storage state (cookies, localStorage, sessionStorage)
            storage_path = self.profile_dir / "storage_state.json"
            try:
                context.storage_state(path=str(storage_path))
                logger.info("Storage state saved to %s", storage_path)
            except Exception as exc:
                logger.warning("Could not save storage state: %s", exc)

            context.close()

        now = datetime.now(tz=timezone.utc).isoformat()
        return {"service": self.service, "logged_in_at": now}

    def fetch(
        self,
        url: str,
        *,
        dest: Path | None = None,
        timeout_s: float = 60,
        headless: bool = True,
    ) -> bytes | Path:
        """Fetch a URL in Chromium, reusing saved cookies.

        Navigates to *url* and captures the response.  If the response
        Content-Type is ``application/pdf`` or ``application/epub+zip``,
        returns the body bytes (or saves to *dest* and returns the Path).

        For URLs that trigger a browser download dialog instead of inline
        rendering, the ``page.expect_download()`` context manager is used.

        Parameters
        ----------
        url:
            Target URL (must ultimately resolve to a PDF or EPUB resource).
        dest:
            If provided, the response body is saved to this path.
            The parent directory must exist.
        timeout_s:
            Request timeout in seconds (default 60).
        headless:
            If True (default), run Chromium without a visible window.
            Set False to show the window — useful when the user needs to
            solve a captcha or complete an institutional login mid-flow.

        Returns
        -------
        bytes | Path
            If *dest* is None: raw response bytes.
            If *dest* is given: the Path to the saved file.

        Raises
        ------
        ImportError
            If playwright is not installed.
        BrowserFetchError
            If the response Content-Type is not PDF or EPUB.
        """
        if not is_browser_extra_installed():
            raise ImportError(
                "Browser support is not installed. "
                'Install it with: pip install "pyzot[browser]"'
            )

        from playwright.sync_api import sync_playwright  # type: ignore[import]

        timeout_ms = int(timeout_s * 1000)

        logger.info(
            "Fetching %s via %s Chromium (profile: %s)",
            url, "headless" if headless else "headed", self.profile_dir,
        )

        pdf_bytes: bytes | None = None

        with sync_playwright() as p:
            # Stealth-ish args: disable the "Chrome is being controlled by
            # automated test software" infobar and the navigator.webdriver
            # flag that Akamai et al. use to bot-detect headless Chromium.
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(self.profile_dir),
                headless=headless,
                args=[
                    "--no-first-run",
                    "--disable-blink-features=AutomationControlled",
                ],
                user_agent=(
                    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 800},
            )
            # Hide the navigator.webdriver flag from any loaded page.
            context.add_init_script(
                "Object.defineProperty(navigator, 'webdriver', {get: () => undefined});"
            )
            page = context.new_page()

            # Capture any PDF/EPUB response body we see on the wire — works
            # even when Chromium renders the PDF inline instead of downloading.
            captured: list[bytes] = []

            def _handle_response(response) -> None:
                try:
                    content_type = response.headers.get("content-type", "").lower()
                    if "pdf" in content_type or "epub" in content_type:
                        captured.append(response.body())
                        logger.debug(
                            "Captured %s (%d bytes) from %s",
                            content_type, len(captured[-1]), response.url,
                        )
                except Exception as exc:
                    logger.debug("Could not capture response body: %s", exc)

            page.on("response", _handle_response)

            try:
                with page.expect_download(timeout=timeout_ms) as download_info:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)

                download = download_info.value
                tmp_download = Path(download.path())
                pdf_bytes = tmp_download.read_bytes()
                logger.info("PDF captured via download handler (%d bytes)", len(pdf_bytes))
            except Exception:
                # No download dialog — check what we captured.
                if captured:
                    pdf_bytes = captured[-1]
                    logger.info("PDF captured via response handler (%d bytes)", len(pdf_bytes))
                else:
                    pdf_bytes = b""

            context.close()

        if not pdf_bytes:
            raise BrowserFetchError(
                f"No PDF content retrieved from {url!r}. "
                "The URL may require additional authentication, or may not resolve to a PDF."
            )

        # Validate: minimal PDF magic bytes check
        # (we accept EPUBs too — they start with PK zip header)
        if not (pdf_bytes[:4] == b"%PDF" or pdf_bytes[:2] == b"PK"):
            raise BrowserFetchError(
                f"Response from {url!r} does not appear to be a PDF or EPUB "
                f"(first bytes: {pdf_bytes[:8]!r})."
            )

        if dest is not None:
            dest = Path(dest)
            dest.write_bytes(pdf_bytes)
            logger.info("Saved %d bytes to %s", len(pdf_bytes), dest)
            return dest

        return pdf_bytes

    def fetch_html(self, url: str, *, timeout_s: float = 30.0) -> str | None:
        """Fetch the rendered HTML of *url* using saved cookies (headless).

        Used by the find-file resolver pipeline when a ``pageURL`` (landing
        page) needs to be scraped for a PDF link. Returns the final rendered
        HTML, or None if loading failed.

        Does not validate Content-Type — callers parse HTML themselves.
        """
        if not is_browser_extra_installed():
            raise ImportError(
                "Browser support is not installed. "
                'Install it with: pip install "pyzot[browser]"'
            )

        from playwright.sync_api import sync_playwright  # type: ignore[import]

        timeout_ms = int(timeout_s * 1000)
        logger.info("Fetching HTML from %s (headless, profile: %s)", url, self.profile_dir)

        try:
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=True,
                    args=["--no-first-run"],
                )
                page = context.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                try:
                    page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    pass
                html = page.content()
                context.close()
                return html
        except Exception as exc:
            logger.debug("fetch_html failed for %s: %s", url, exc)
            return None

    def cookies_exist(self) -> bool:
        """Return True if this service has any saved cookie data on disk."""
        try:
            # Persistent profile creates many files; treat profile as cookied
            # if storage_state.json exists or the profile dir has cookie files.
            storage_state = self.profile_dir / "storage_state.json"
            if storage_state.exists() and storage_state.stat().st_size > 0:
                return True
            # Look for Default/Cookies (Chromium persistent profile)
            for candidate in (
                self.profile_dir / "Default" / "Cookies",
                self.profile_dir / "Default" / "Network" / "Cookies",
            ):
                if candidate.exists():
                    return True
        except Exception:
            pass
        return False
