"""OpenLibrary resolver — ISBN → CSL-JSON.

GET https://openlibrary.org/api/books?bibkeys=ISBN:{isbn}&format=json&jscmd=data

Falls back to an empty record if OpenLibrary has no data.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_API_URL = "https://openlibrary.org/api/books"


def resolve(isbn: str) -> dict:
    """Fetch metadata for *isbn* from OpenLibrary and return a CSL-JSON dict.

    Parameters
    ----------
    isbn:
        A normalised ISBN string (digits only, no hyphens; 10 or 13 digits).

    Returns
    -------
    dict
        A CSL-JSON record with ``type: "book"``.

    Raises
    ------
    IdentifierNotFound
        If OpenLibrary returns no data for the given ISBN.
    RuntimeError
        On HTTP errors.
    """
    from pyzot.write.resolvers import IdentifierNotFound
    from pyzot.write.resolvers._http import require_httpx

    httpx = require_httpx()
    params = {
        "bibkeys": f"ISBN:{isbn}",
        "format": "json",
        "jscmd": "data",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(_API_URL, params=params, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to reach OpenLibrary for ISBN '{isbn}': {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"OpenLibrary returned HTTP {resp.status_code} for ISBN '{isbn}': {resp.text[:200]}"
        )

    data = resp.json()
    key = f"ISBN:{isbn}"
    book = data.get(key)
    if not book:
        raise IdentifierNotFound("isbn", isbn, "OpenLibrary returned no data for this ISBN")

    return _build_csl(book, isbn)


def _build_csl(book: dict, isbn: str) -> dict:
    """Convert an OpenLibrary book record to CSL-JSON."""
    title = book.get("title", "")
    subtitle = book.get("subtitle", "")
    if subtitle:
        title = f"{title}: {subtitle}"

    # Authors
    creators: list[dict] = []
    for author in book.get("authors", []):
        name = author.get("name", "")
        if name:
            parts = name.rsplit(" ", 1)
            if len(parts) == 2:
                creators.append({"given": parts[0], "family": parts[1]})
            else:
                creators.append({"literal": name})

    # Date
    publish_date = book.get("publish_date", "")
    date_parts_list: list[list[int]] = []
    if publish_date:
        import re
        year_match = re.search(r"\b(\d{4})\b", publish_date)
        if year_match:
            date_parts_list = [[int(year_match.group(1))]]

    # Publishers
    publisher = ""
    publishers = book.get("publishers", [])
    if publishers:
        publisher = publishers[0].get("name", "")

    # Place
    place = ""
    publish_places = book.get("publish_places", [])
    if publish_places:
        place = publish_places[0].get("name", "")

    # ISBNs
    isbn_val = isbn
    identifiers = book.get("identifiers", {})
    isbn_13_list = identifiers.get("isbn_13", [])
    isbn_10_list = identifiers.get("isbn_10", [])
    if isbn_13_list:
        isbn_val = isbn_13_list[0]
    elif isbn_10_list:
        isbn_val = isbn_10_list[0]

    # Number of pages
    num_pages = book.get("number_of_pages")

    # URL
    url = book.get("url", book.get("info_url", ""))

    csl: dict = {
        "type": "book",
        "title": title,
        "author": creators,
        "publisher": publisher,
        "publisher-place": place,
        "ISBN": isbn_val,
        "URL": url,
    }
    if date_parts_list:
        csl["issued"] = {"date-parts": date_parts_list}
    elif publish_date:
        csl["issued"] = {"literal": publish_date}
    if num_pages:
        csl["number-of-pages"] = str(num_pages)

    # Series
    subjects = book.get("subjects", [])
    if subjects:
        # Use first subject as genre/keyword (no direct CSL mapping for subjects)
        first_subject = subjects[0]
        if isinstance(first_subject, dict):
            csl["genre"] = first_subject.get("name", "")
        elif isinstance(first_subject, str):
            csl["genre"] = first_subject

    return csl
