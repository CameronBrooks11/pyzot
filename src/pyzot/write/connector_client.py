"""HTTP client for the Zotero connector server (127.0.0.1:23119/connector/*).

All writes to Zotero go through this client. The SQLite database handle
stays strictly read-only throughout.

httpx is imported lazily inside each method so that the read-only import
path never pulls in the 'write' optional dependency.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import click

logger = logging.getLogger("pyzot.connector")


class ConnectorUnreachable(RuntimeError):
    """Raised when the Zotero connector cannot be contacted.

    Zotero appears to be closed. Open Zotero and retry, or pass
    --no-require-zotero to skip the preflight check.
    """

    def __init__(self, url: str, detail: str = "") -> None:
        self.url = url
        self.detail = detail
        msg = (
            f"Zotero connector is not reachable at {url}. "
            "Zotero appears to be closed. Open Zotero and retry, "
            "or pass --no-require-zotero to skip the preflight."
        )
        if detail:
            msg = f"{msg}\n  Detail: {detail}"
        super().__init__(msg)


class ConnectorClient:
    """Thin httpx wrapper for /connector/* endpoints.

    Parameters
    ----------
    base_url:
        Base URL of the Zotero connector server.
        Default: ``http://127.0.0.1:23119``
    timeout:
        Request timeout in seconds (default 5).
    max_retries:
        Number of additional attempts on transient 5xx responses (default 2).
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:23119",
        timeout: float = 5.0,
        max_retries: int = 2,
        verbose: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.verbose = verbose

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_client(self):  # type: ignore[return]
        """Lazily import httpx and return a new Client."""
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'write' extra is required for connector access. "
                'Install it with: pip install "pyzot[write]"'
            ) from exc
        return httpx.Client(timeout=self.timeout)

    def _trace(self, msg: str) -> None:
        """Emit a verbose HTTP trace line to stderr (if verbose) and to the logger."""
        logger.debug("[http] %s", msg)
        if self.verbose:
            click.echo(f"[http] {msg}", err=True)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Execute an HTTP request with exponential-backoff retry on 5xx.

        Returns the parsed JSON body on success.
        Raises ConnectorUnreachable on connection errors or non-2xx after retries.
        """
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None

        # Verbose: describe the outgoing request
        body_len = 0
        json_body = kwargs.get("json")
        raw_content = kwargs.get("content")
        if json_body is not None:
            import json as _json

            body_len = len(_json.dumps(json_body).encode())
            self._trace(f"{method} {url} Content-Type: application/json body_len={body_len}")
        elif raw_content is not None:
            body_len = len(raw_content) if isinstance(raw_content, (bytes, bytearray)) else 0
            ct = kwargs.get("headers", {}).get("Content-Type", "application/octet-stream")
            self._trace(f"{method} {url} Content-Type: {ct} body_len={body_len}")
        else:
            self._trace(f"{method} {url}")

        for attempt in range(self.max_retries + 1):
            if attempt > 0:
                # Exponential back-off: 0.5s, 1s, 2s, …
                time.sleep(0.5 * (2 ** (attempt - 1)))

            t0 = time.monotonic()
            try:
                with self._get_client() as client:
                    response = client.request(method, url, **kwargs)
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                # Connection-level failure: no point retrying if refused immediately
                # unless it's a transient timeout
                import httpx as _httpx  # noqa: PLC0415

                if isinstance(exc, _httpx.ConnectError):
                    raise ConnectorUnreachable(url, str(exc)) from exc
                # For timeouts, retry
                last_exc = exc
                continue

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._trace(f"<- {response.status_code} elapsed={elapsed_ms}ms")
            logger.info(
                "connector %s %s -> %s elapsed_ms=%d",
                method,
                url,
                response.status_code,
                elapsed_ms,
            )

            if response.status_code < 500:
                # 2xx, 3xx, 4xx — do not retry; return or raise immediately
                if response.status_code >= 400:
                    raise ConnectorUnreachable(
                        url,
                        f"HTTP {response.status_code}: {response.text[:200]}",
                    )
                # Return JSON if possible, else raw text
                content_type = response.headers.get("content-type", "")
                if "json" in content_type and response.text.strip():
                    return response.json()
                return {"_raw": response.text, "status_code": response.status_code}

            # 5xx — retry
            last_exc = Exception(f"HTTP {response.status_code}: {response.text[:200]}")

        raise ConnectorUnreachable(
            url,
            str(last_exc) if last_exc else "Unknown error after retries",
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def ping(self) -> dict:
        """GET /connector/ping — liveness check.

        Returns the parsed JSON body from Zotero.
        Raises ConnectorUnreachable if Zotero is closed or unreachable.
        """
        return self._request("GET", "/connector/ping")

    def get_selected_collection(self) -> dict | None:
        """GET /connector/getSelectedCollection — report current target.

        Returns the parsed JSON body, or None if the response is empty.
        Raises ConnectorUnreachable if Zotero is unreachable.
        """
        result = self._request("GET", "/connector/getSelectedCollection")
        if not result:
            return None
        return result

    def save_items(
        self,
        items: list[dict],
        uri: str,
        session_id: str,
    ) -> dict:
        """POST /connector/saveItems — save one or more items to Zotero.

        Parameters
        ----------
        items:
            List of connector-shaped item dicts (see csl_json.csl_to_connector_item).
        uri:
            A URI string that identifies the source (used by Zotero for display).
            Pass ``"https://pyzot.local/add"`` if there is no meaningful URL.
        session_id:
            UUID hex string identifying this save session.

        Returns
        -------
        dict
            Parsed JSON response from Zotero (contains saved item keys, etc.).
        """
        payload = {
            "items": items,
            "uri": uri,
            "sessionID": session_id,
        }
        return self._request("POST", "/connector/saveItems", json=payload)

    def update_session(
        self,
        session_id: str,
        target: str | None = None,
        tags: list[str] | None = None,
        note: str | None = None,
    ) -> dict:
        """POST /connector/updateSession — re-target items saved in a session.

        After ``save_items``, call this to move items to a specific collection
        and/or add tags and a note.

        Parameters
        ----------
        session_id:
            The session UUID hex from ``save_items``.
        target:
            Zotero target string. For a collection use ``"C<collectionID>"``.
            For a library root use ``"L<libraryID>"``.
        tags:
            List of tag strings to apply to all items in the session.
        note:
            HTML or plain-text note to attach as a child note.

        Returns
        -------
        dict
            Parsed JSON response from Zotero.
        """
        payload: dict = {"sessionID": session_id}
        if target is not None:
            payload["target"] = target
        if tags is not None:
            payload["tags"] = [{"tag": t} for t in tags]
        if note is not None:
            payload["note"] = note
        return self._request("POST", "/connector/updateSession", json=payload)

    def save_standalone_attachment(
        self,
        *,
        file_path,
        content_type: str,
        session_id: str,
        title: str,
        source_url: str | None = None,
    ) -> dict:
        """POST /connector/saveStandaloneAttachment — upload a binary file.

        Streams the file to Zotero. Zotero auto-runs ``RecognizeDocument``
        after a successful upload if the content type is PDF or EPUB.

        This method makes **a single attempt only** (no retry). The connector
        endpoint is not idempotent — a retry would create a duplicate attachment.

        Parameters
        ----------
        file_path:
            ``pathlib.Path`` (or str) pointing to the local file to upload.
        content_type:
            MIME type (e.g. ``"application/pdf"``).
        session_id:
            UUID hex string for this session.
        title:
            Display title for the attachment in Zotero.
        source_url:
            Source URL to record on the attachment. Defaults to
            ``"file://<absolute_path>"``.

        Returns
        -------
        dict
            Parsed JSON response from Zotero, e.g. ``{"canRecognize": true}``.
        """
        import json as _json

        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'write' extra is required for connector access. "
                'Install it with: pip install "pyzot[write]"'
            ) from exc

        from pathlib import Path as _Path

        fpath = _Path(file_path)
        file_size = fpath.stat().st_size
        url_str = source_url or f"file://{fpath.resolve()}"

        metadata = _json.dumps(
            {
                "sessionID": session_id,
                "title": title,
                "url": url_str,
            }
        )

        endpoint = f"{self.base_url}/connector/saveStandaloneAttachment"

        with fpath.open("rb") as fh:
            file_data = fh.read()

        with httpx.Client(timeout=max(self.timeout, 60.0)) as client:
            response = client.post(
                endpoint,
                content=file_data,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(file_size),
                    "X-Metadata": metadata,
                },
            )

        if response.status_code >= 400:
            raise ConnectorUnreachable(
                endpoint,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

        content_type_resp = response.headers.get("content-type", "")
        if "json" in content_type_resp:
            return response.json()
        return {"_raw": response.text, "status_code": response.status_code}

    def connector_import(
        self,
        *,
        body: bytes,
        content_type: str,
        session_id: str | None = None,
    ) -> dict:
        """POST /connector/import — import bibliography data into Zotero.

        Sends raw bytes to the connector's import endpoint. Zotero auto-detects
        the bibliography format (RIS, BibTeX, CSL-JSON, MODS, etc.) via its
        built-in import translators.

        Parameters
        ----------
        body:
            Raw bytes of the bibliography file.
        content_type:
            MIME type of the data:
            - RIS: ``"application/x-research-info-systems"``
            - BibTeX: ``"application/x-bibtex"``
            - CSL-JSON: ``"application/vnd.citationstyles.csl+json"``
            - Generic: ``"text/plain"``
        session_id:
            Optional session ID. If provided, appended as ``?session=<id>``
            to the URL so Zotero can associate the import with a session.

        Returns
        -------
        dict
            Parsed JSON response from Zotero (list of imported items, or a
            dict wrapping the list).
        """
        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'write' extra is required for connector access. "
                'Install it with: pip install "pyzot[write]"'
            ) from exc

        path = "/connector/import"
        if session_id:
            path = f"{path}?session={session_id}"

        endpoint = f"{self.base_url}{path}"

        with httpx.Client(timeout=max(self.timeout, 60.0)) as client:
            response = client.post(
                endpoint,
                content=body,
                headers={"Content-Type": content_type},
            )

        if response.status_code >= 400:
            raise ConnectorUnreachable(
                endpoint,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

        content_type_resp = response.headers.get("content-type", "")
        if "json" in content_type_resp:
            return response.json()
        return {"_raw": response.text, "status_code": response.status_code}

    def save_attachment(
        self,
        *,
        file_path,
        content_type: str,
        session_id: str,
        parent_item_id: str,
        title: str,
        source_url: str | None = None,
    ) -> dict:
        """POST /connector/saveAttachment — upload a PDF as a child of an existing item.

        Similar to ``save_standalone_attachment`` but associates the uploaded
        binary with a parent item saved earlier in the same session.

        Parameters
        ----------
        file_path:
            ``pathlib.Path`` (or str) pointing to the local file to upload.
        content_type:
            MIME type (e.g. ``"application/pdf"``).
        session_id:
            UUID hex string for this session.
        parent_item_id:
            The Zotero item key of the parent item (e.g. ``"ABCD1234"``).
        title:
            Display title for the attachment.
        source_url:
            Source URL to record on the attachment.

        Returns
        -------
        dict
            Parsed JSON response from Zotero.
        """
        import json as _json

        try:
            import httpx  # type: ignore[import]
        except ImportError as exc:
            raise ImportError(
                "The 'write' extra is required for connector access. "
                'Install it with: pip install "pyzot[write]"'
            ) from exc

        from pathlib import Path as _Path

        fpath = _Path(file_path)
        file_size = fpath.stat().st_size
        url_str = source_url or f"file://{fpath.resolve()}"

        metadata = _json.dumps(
            {
                "sessionID": session_id,
                "parentItemID": parent_item_id,
                "title": title,
                "url": url_str,
            }
        )

        endpoint = f"{self.base_url}/connector/saveAttachment"

        with fpath.open("rb") as fh:
            file_data = fh.read()

        with httpx.Client(timeout=max(self.timeout, 60.0)) as client:
            response = client.post(
                endpoint,
                content=file_data,
                headers={
                    "Content-Type": content_type,
                    "Content-Length": str(file_size),
                    "X-Metadata": metadata,
                },
            )

        if response.status_code >= 400:
            raise ConnectorUnreachable(
                endpoint,
                f"HTTP {response.status_code}: {response.text[:200]}",
            )

        content_type_resp = response.headers.get("content-type", "")
        if "json" in content_type_resp:
            return response.json()
        return {"_raw": response.text, "status_code": response.status_code}

    def save_snapshot(
        self,
        url: str,
        html: str | None,
        session_id: str,
        snapshot_content_type: str = "text/html",
    ) -> dict:
        """POST /connector/saveSnapshot — save a webpage snapshot to Zotero.

        Zotero will run its translator chain on the provided HTML, using any
        applicable site-specific translator (e.g. for IEEE Xplore or generic
        pages).

        Parameters
        ----------
        url:
            The canonical URL of the page being saved.
        html:
            The raw HTML content of the page, or ``None`` if not available.
        session_id:
            UUID hex string identifying this save session.
        snapshot_content_type:
            MIME type of the snapshot content (default ``"text/html"``).

        Returns
        -------
        dict
            Parsed JSON response from Zotero (contains a snapshot key, etc.).
        """
        payload: dict = {
            "url": url,
            "sessionID": session_id,
        }
        if html is not None:
            payload["html"] = html
        if snapshot_content_type != "text/html":
            payload["snapshotContentType"] = snapshot_content_type
        return self._request("POST", "/connector/saveSnapshot", json=payload)
