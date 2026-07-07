"""Tests for OpenLibrary resolver using monkeypatched httpserver."""

from __future__ import annotations

import pytest

from pyzot.write.resolvers import IdentifierNotFound

OPENLIBRARY_RESPONSE = {
    "ISBN:9780262033848": {
        "url": "http://openlibrary.org/books/OL23170657M/Introduction_to_Algorithms",
        "key": "/books/OL23170657M",
        "title": "Introduction to Algorithms",
        "authors": [
            {"url": "http://openlibrary.org/authors/OL1004780A", "name": "Thomas H. Cormen"},
            {"url": "http://openlibrary.org/authors/OL3328609A", "name": "Charles E. Leiserson"},
        ],
        "publish_date": "2009",
        "publishers": [{"name": "MIT Press"}],
        "publish_places": [{"name": "Cambridge, MA"}],
        "number_of_pages": 1292,
        "identifiers": {
            "isbn_13": ["9780262033848"],
            "isbn_10": ["0262033844"],
        },
    }
}

OPENLIBRARY_EMPTY_RESPONSE: dict = {}


class TestOpenLibraryResolve:
    def test_successful_resolve(self, httpserver, monkeypatch):
        """resolve() returns CSL-JSON for a valid ISBN."""
        httpserver.expect_request("/api/books").respond_with_json(OPENLIBRARY_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary._API_URL",
            httpserver.url_for("/api/books"),
        )

        from pyzot.write.resolvers.openlibrary import resolve

        result = resolve("9780262033848")

        assert result["type"] == "book"
        assert result["title"] == "Introduction to Algorithms"
        assert len(result["author"]) == 2
        assert result["author"][0]["family"] == "Cormen"
        assert result["publisher"] == "MIT Press"
        assert result["ISBN"] == "9780262033848"
        assert result["issued"]["date-parts"] == [[2009]]

    def test_empty_response_raises_not_found(self, httpserver, monkeypatch):
        """resolve() raises IdentifierNotFound when OpenLibrary has no data."""
        httpserver.expect_request("/api/books").respond_with_json(OPENLIBRARY_EMPTY_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary._API_URL",
            httpserver.url_for("/api/books"),
        )

        from pyzot.write.resolvers.openlibrary import resolve

        with pytest.raises(IdentifierNotFound):
            resolve("9999999999999")

    def test_http_error_raises_runtime(self, httpserver, monkeypatch):
        """resolve() raises RuntimeError on non-200 HTTP status."""
        httpserver.expect_request("/api/books").respond_with_data(
            "Service Unavailable", status=503, content_type="text/plain"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary._API_URL",
            httpserver.url_for("/api/books"),
        )

        from pyzot.write.resolvers.openlibrary import resolve

        with pytest.raises(RuntimeError):
            resolve("9780262033848")

    def test_build_csl_directly(self):
        """_build_csl() correctly converts an OpenLibrary book record."""
        from pyzot.write.resolvers.openlibrary import _build_csl

        book = OPENLIBRARY_RESPONSE["ISBN:9780262033848"]
        result = _build_csl(book, "9780262033848")
        assert result["type"] == "book"
        assert "Introduction to Algorithms" in result["title"]
        assert result["author"][0]["given"] == "Thomas H."
        assert result["author"][0]["family"] == "Cormen"
        assert result["publisher-place"] == "Cambridge, MA"
