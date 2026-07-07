"""BibTeX export — maps Zotero item types to BibTeX entry types."""

from __future__ import annotations

import re
from typing import IO

from zotcli.models import Item

# Zotero → BibTeX type mapping (from aurimasv.github.io/z2csl/typeMap.xml)
_TYPE_MAP: dict[str, str] = {
    "journalArticle": "article",
    "book": "book",
    "bookSection": "incollection",
    "conferencePaper": "inproceedings",
    "thesis": "phdthesis",
    "report": "techreport",
    "manuscript": "unpublished",
    "encyclopediaArticle": "inreference",
    "dictionaryEntry": "inreference",
    "magazineArticle": "article",
    "newspaperArticle": "article",
    "patent": "patent",
    "webpage": "misc",
    "blogPost": "misc",
    "email": "misc",
    "letter": "misc",
    "interview": "misc",
    "film": "misc",
    "audioRecording": "misc",
    "videoRecording": "misc",
    "tvBroadcast": "misc",
    "radioBroadcast": "misc",
    "podcast": "misc",
    "instantMessage": "misc",
    "forumPost": "misc",
    "presentation": "misc",
    "artwork": "misc",
    "map": "misc",
    "statute": "misc",
    "bill": "misc",
    "hearing": "misc",
    "case": "misc",
    "document": "misc",
    "preprint": "article",
    "standard": "misc",
    "software": "software",
    "dataset": "misc",
}


def _make_citation_key(item: Item) -> str:
    """Generate LastNameYYYYword key."""
    # Try Better BibTeX key first
    ck = item.fields.get("citationKey") or item.fields.get("citekey")
    if ck:
        return re.sub(r"[^\w:-]", "", ck)

    last = ""
    if item.authors:
        last = item.authors[0].split(",")[0].strip()
        last = re.sub(r"[^\w]", "", last)

    year = item.year or "0000"

    # First significant word of title
    title_words = re.findall(r"\b[A-Za-z]{4,}\b", item.title)
    word = title_words[0].lower() if title_words else "untitled"

    return f"{last}{year}{word}"


def _escape_bib(value: str) -> str:
    """Escape special BibTeX characters."""
    for ch in ("&", "%", "$", "#", "_", "{", "}", "~", "^"):
        value = value.replace(ch, "\\" + ch)
    return value


def _format_authors(item: Item) -> str:
    """Format creators as BibTeX author string."""
    authors = [
        f"{c.last_name}, {c.first_name}" if c.first_name else c.last_name
        for c in sorted(item.creators, key=lambda c: c.order_index)
        if c.creator_type == "author"
    ]
    return " and ".join(authors) if authors else ""


def item_to_bibtex(item: Item) -> str:
    entry_type = _TYPE_MAP.get(item.item_type, "misc")
    key = _make_citation_key(item)

    fields: list[str] = []

    title = item.title
    if title and title != "(no title)":
        fields.append(f"  title = {{{_escape_bib(title)}}}")

    authors = _format_authors(item)
    if authors:
        fields.append(f"  author = {{{authors}}}")

    year = item.year
    if year:
        fields.append(f"  year = {{{year}}}")

    for bib_field, zot_field in [
        ("journal", "publicationTitle"),
        ("booktitle", "proceedingsTitle"),
        ("publisher", "publisher"),
        ("address", "place"),
        ("volume", "volume"),
        ("number", "issue"),
        ("pages", "pages"),
        ("doi", "DOI"),
        ("url", "url"),
        ("issn", "ISSN"),
        ("isbn", "ISBN"),
        ("school", "university"),
        ("institution", "institution"),
        ("note", "extra"),
    ]:
        val = item.fields.get(zot_field, "")
        if val:
            fields.append(f"  {bib_field} = {{{_escape_bib(val)}}}")

    body = ",\n".join(fields)
    return f"@{entry_type}{{{key},\n{body}\n}}\n"


def items_to_bibtex(items: list[Item], fp: IO[str] | None = None) -> str:
    output = "\n".join(item_to_bibtex(item) for item in items)
    if fp is not None:
        fp.write(output)
    return output
