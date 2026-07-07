"""Pydantic models reflecting Zotero's SQLite schema."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, field_validator


class Library(BaseModel):
    library_id: int
    type: str  # "user" or "group"
    editable: bool


class Collection(BaseModel):
    collection_id: int
    key: str
    name: str
    parent_collection_id: int | None = None
    library_id: int
    children: list[Collection] = []
    item_count: int = 0

    model_config = {"arbitrary_types_allowed": True}


class Creator(BaseModel):
    creator_id: int
    first_name: str
    last_name: str
    creator_type: str  # author, editor, translator, …
    order_index: int

    @property
    def display_name(self) -> str:
        if self.last_name and self.first_name:
            return f"{self.last_name}, {self.first_name}"
        return self.last_name or self.first_name


class Attachment(BaseModel):
    item_id: int
    key: str
    parent_item_id: int
    link_mode: int  # 0=imported_file, 1=imported_url, 2=linked_file, 3=linked_url
    content_type: str
    path: str | None = None
    absolute_path: Path | None = None
    file_exists: bool = False

    model_config = {"arbitrary_types_allowed": True}

    @property
    def link_mode_name(self) -> str:
        return {0: "imported_file", 1: "imported_url", 2: "linked_file", 3: "linked_url"}.get(
            self.link_mode, f"unknown({self.link_mode})"
        )

    @property
    def filename(self) -> str | None:
        if self.path:
            return Path(self.path).name
        return None


class Note(BaseModel):
    item_id: int
    parent_item_id: int
    title: str
    note: str  # HTML content
    plain_text: str  # stripped version

    @field_validator("plain_text", mode="before")
    @classmethod
    def strip_html(cls, v: str) -> str:
        if v:
            return re.sub(r"<[^>]+>", "", v).strip()
        return v or ""


class Item(BaseModel):
    item_id: int
    key: str
    item_type: str  # journalArticle, book, conferencePaper, …
    library_id: int
    date_added: datetime
    date_modified: datetime
    fields: dict[str, str] = {}
    creators: list[Creator] = []
    tags: list[str] = []
    collections: list[int] = []
    attachments: list[Attachment] = []
    notes: list[Note] = []

    model_config = {"arbitrary_types_allowed": True}

    # ------------------------------------------------------------------
    # Convenience properties
    # ------------------------------------------------------------------

    @property
    def title(self) -> str:
        return self.fields.get("title", "(no title)")

    @property
    def year(self) -> str | None:
        date = self.fields.get("date", "")
        if date:
            m = re.search(r"\b(\d{4})\b", date)
            if m:
                return m.group(1)
        return None

    @property
    def doi(self) -> str | None:
        return self.fields.get("DOI") or self.fields.get("doi")

    @property
    def authors(self) -> list[str]:
        return [
            c.display_name
            for c in sorted(self.creators, key=lambda c: c.order_index)
            if c.creator_type == "author"
        ]

    @property
    def authors_short(self) -> str:
        """First author last name + et al. for display."""
        a = self.authors
        if not a:
            return ""
        if len(a) == 1:
            return a[0].split(",")[0]
        return a[0].split(",")[0] + " et al."

    @property
    def citation_key(self) -> str | None:
        # Check standard fields first if any plugin adds them
        if "citationKey" in self.fields:
            return self.fields["citationKey"]
        if "citekey" in self.fields:
            return self.fields["citekey"]

        # Check 'extra' field where Better BibTeX stores it
        extra = self.fields.get("extra", "")
        if extra:
            for line in extra.splitlines():
                if line.lower().startswith("citation key:"):
                    return line.split(":", 1)[1].strip()
        return None

    def __str__(self) -> str:
        return f"[{self.item_type}] {self.title} ({self.year or '?'})"
