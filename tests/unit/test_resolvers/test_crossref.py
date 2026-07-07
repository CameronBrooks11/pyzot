"""Tests for crossref resolver using pytest-httpserver (no live network)."""

from __future__ import annotations

import json

import pytest

from pyzot.write.resolvers import IdentifierNotFound


CROSSREF_RESPONSE = {
    "status": "ok",
    "message": {
        "type": "journal-article",
        "title": ["Array programming with NumPy"],
        "author": [
            {"given": "Charles R.", "family": "Harris"},
            {"given": "K. Jarrod", "family": "Millman"},
        ],
        "issued": {"date-parts": [[2020, 9, 16]]},
        "DOI": "10.1038/s41586-020-2649-2",
        "container-title": ["Nature"],
        "volume": "585",
        "issue": "7825",
        "page": "357-362",
        "ISSN": ["0028-0836"],
        "URL": "https://doi.org/10.1038/s41586-020-2649-2",
        "abstract": "Array programming provides a powerful, compact and expressive syntax...",
        "language": "en",
        "publisher": "Springer Science and Business Media LLC",
    },
}


class TestCrossrefResolve:
    def test_successful_resolve(self, httpserver, monkeypatch):
        """resolve() returns the message dict on 200."""
        doi = "10.1038/s41586-020-2649-2"
        httpserver.expect_request(f"/works/{doi}").respond_with_json(
            CROSSREF_RESPONSE
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from pyzot.write.resolvers.crossref import resolve
        result = resolve(doi)
        assert result["type"] == "journal-article"
        assert result["DOI"] == doi

    def test_404_raises_identifier_not_found(self, httpserver, monkeypatch):
        """resolve() raises IdentifierNotFound on 404."""
        doi = "10.9999/nonexistent"
        httpserver.expect_request(f"/works/{doi}").respond_with_data(
            "Not Found", status=404, content_type="text/plain"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from pyzot.write.resolvers.crossref import resolve
        with pytest.raises(IdentifierNotFound) as exc_info:
            resolve(doi)
        assert "doi" in str(exc_info.value).lower()

    def test_5xx_retries_and_succeeds(self, httpserver, monkeypatch):
        """resolve() retries on 500 and returns success on 200."""
        doi = "10.1038/retry-test"
        httpserver.expect_ordered_request(f"/works/{doi}").respond_with_data(
            "error", status=500, content_type="text/plain"
        )
        httpserver.expect_ordered_request(f"/works/{doi}").respond_with_json(
            CROSSREF_RESPONSE
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from pyzot.write.resolvers.crossref import resolve
        result = resolve(doi)
        assert result["DOI"] == "10.1038/s41586-020-2649-2"

    def test_title_is_list_in_crossref(self, httpserver, monkeypatch):
        """Crossref title comes as a list — resolver should pass it through."""
        doi = "10.1038/test"
        httpserver.expect_request(f"/works/{doi}").respond_with_json(CROSSREF_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from pyzot.write.resolvers.crossref import resolve
        result = resolve(doi)
        assert isinstance(result["title"], list)
        assert result["title"][0] == "Array programming with NumPy"
