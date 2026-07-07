"""Session lifecycle management for pyzot write operations.

A Session wraps a unique sessionID (uuid4 hex) and coordinates:
- save_items → POST /connector/saveItems
- set_target → POST /connector/updateSession with target="C<id>"
- add_tags   → POST /connector/updateSession with tags=[...]
- add_note   → POST /connector/updateSession with note=<text>

All session records are appended to <pyzot-home>/cache/sessions.jsonl
in newline-delimited JSON format for idempotency review.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from uuid import uuid4

logger = logging.getLogger(__name__)


class Session:
    """Manages a single Zotero connector session.

    Parameters
    ----------
    client:
        A ``ConnectorClient`` instance to use for all HTTP calls.
    library_id:
        The Zotero library ID (default 1 for the personal library).
    """

    def __init__(self, client, library_id: int = 1) -> None:
        self._client = client
        self._library_id = library_id
        self.id: str = uuid4().hex
        self._saved_keys: list[str] = []
        self._collection_id: int | None = None
        self._tags: list[str] = []

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def save_items(self, items: list[dict], uri: str = "https://pyzot.local/add") -> dict:
        """POST /connector/saveItems and record the session.

        Parameters
        ----------
        items:
            List of connector-shaped item dicts.
        uri:
            Source URI passed to Zotero (informational).

        Returns
        -------
        dict
            Parsed Zotero response.
        """
        result = self._client.save_items(items, uri, self.id)
        # Extract item keys from the response (Zotero may return them in various ways)
        keys = self._extract_keys(result)
        self._saved_keys.extend(keys)
        self._log_session()
        return result

    def set_target(self, collection_id_or_name, db=None) -> None:
        """Set the target collection for items saved in this session.

        Parameters
        ----------
        collection_id_or_name:
            Either an integer collection ID, or a string collection name.
            If a string name is provided, ``db`` must also be supplied to
            resolve the name to an ID via the read-only database.
        db:
            A ``ZoteroDatabase`` instance for name resolution (optional).
        """
        if isinstance(collection_id_or_name, int):
            collection_id = collection_id_or_name
        else:
            # Resolve name → ID
            collection_id = self._resolve_collection_name(
                str(collection_id_or_name), db
            )

        self._collection_id = collection_id
        target = f"C{collection_id}"
        self._client.update_session(self.id, target=target)
        self._log_session()

    def add_tags(self, tags: list[str]) -> None:
        """Add tags to all items saved in this session.

        Parameters
        ----------
        tags:
            List of tag strings.
        """
        self._tags.extend(tags)
        self._client.update_session(self.id, tags=self._tags)
        self._log_session()

    def attach_child_pdf(
        self,
        parent_key: str,
        pdf_path,
        source_url: str | None = None,
        title: str | None = None,
    ) -> dict:
        """Upload a PDF as a child attachment of *parent_key*.

        POSTs to ``/connector/saveAttachment`` with the session ID and the
        parent item's key.  The PDF must already exist on disk.

        Parameters
        ----------
        parent_key:
            Zotero item key of the parent item (e.g. ``"ABCD1234"``).
        pdf_path:
            ``pathlib.Path`` (or str) to the local PDF file.
        source_url:
            Source URL to record on the attachment (optional).
        title:
            Display title for the attachment (defaults to the filename stem).

        Returns
        -------
        dict
            Parsed JSON response from the connector.
        """
        from pathlib import Path as _Path

        fpath = _Path(pdf_path)
        if title is None:
            title = fpath.stem

        result = self._client.save_attachment(
            file_path=fpath,
            content_type="application/pdf",
            session_id=self.id,
            parent_item_id=parent_key,
            title=title,
            source_url=source_url,
        )
        logger.debug(
            "attach_child_pdf: parent=%s path=%s -> %s", parent_key, fpath, result
        )
        return result

    def add_note(self, text: str) -> None:
        """Attach a child note to all items saved in this session.

        Parameters
        ----------
        text:
            Plain-text or HTML note content.
        """
        self._client.update_session(self.id, note=text)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_keys(response: dict) -> list[str]:
        """Extract item keys from a saveItems response."""
        # Zotero may return keys in several shapes; try the most common ones
        if not isinstance(response, dict):
            return []
        # Shape 1: {"items": [{"key": "...", ...}, ...]}
        items = response.get("items")
        if isinstance(items, list):
            keys = []
            for item in items:
                if isinstance(item, dict):
                    k = item.get("key")
                    if k:
                        keys.append(k)
            if keys:
                return keys
        # Shape 2: {"key": "..."} (single item)
        k = response.get("key")
        if k:
            return [k]
        # Shape 3: {"keys": [...]}
        ks = response.get("keys")
        if isinstance(ks, list):
            return [str(k) for k in ks]
        return []

    @staticmethod
    def _resolve_collection_name(name: str, db) -> int:
        """Resolve a collection name to an integer collection ID.

        Parameters
        ----------
        name:
            Collection name (exact match first; fuzzy fallback).
        db:
            A ``ZoteroDatabase`` instance.

        Returns
        -------
        int
            The collection ID.

        Raises
        ------
        ValueError
            If the collection cannot be found.
        """
        from pyzot.queries.collections import get_collection_by_name

        if db is None:
            raise ValueError(
                f"Cannot resolve collection name '{name}': no database provided."
            )

        matches = get_collection_by_name(db, name, fuzzy=False)
        if not matches:
            # Try fuzzy match
            matches = get_collection_by_name(db, name, fuzzy=True)
        if not matches:
            raise ValueError(
                f"Collection '{name}' not found in the Zotero database. "
                "Check the collection name with `zot collections`."
            )
        if len(matches) > 1:
            names = ", ".join(f"'{m.name}'" for m in matches)
            raise ValueError(
                f"Ambiguous collection name '{name}' matches multiple collections: {names}. "
                "Use a more specific name."
            )
        return matches[0].collection_id

    def _log_session(self) -> None:
        """Append a session record to <pyzot-home>/cache/sessions.jsonl."""
        try:
            from pyzot.paths import sessions_path

            record = {
                "ts": datetime.now(tz=timezone.utc).isoformat(),
                "session_id": self.id,
                "items": list(self._saved_keys),
                "collection": self._collection_id,
                "tags": list(self._tags),
            }
            path = sessions_path()
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
        except Exception as exc:
            # Non-fatal: log a warning and continue
            logger.warning("Failed to log session to sessions.jsonl: %s", exc)
