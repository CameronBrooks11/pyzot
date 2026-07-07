"""Tests for crossref.bibliographic_search() using pytest-httpserver."""

from __future__ import annotations

import pytest


CROSSREF_SEARCH_RESPONSE = {
    "status": "ok",
    "message": {
        "total-results": 2,
        "items": [
            {
                "DOI": "10.1016/j.segan.2025.01.001",
                "title": ["Beyond simplifications: Evaluating assumptions for low-voltage network modelling"],
                "author": [
                    {"given": "J.", "family": "Zhang"},
                    {"given": "F.", "family": "Geth"},
                    {"given": "R.", "family": "Heidari"},
                    {"given": "G.", "family": "Verbič"},
                ],
                "issued": {"date-parts": [[2025]]},
                "container-title": ["Sustainable Energy, Grids and Networks"],
                "score": 285.6,
                "type": "journal-article",
            },
            {
                "DOI": "10.1016/j.segan.2024.12.999",
                "title": ["Low-voltage network assumptions revisited"],
                "author": [{"given": "A.", "family": "Smith"}],
                "issued": {"date-parts": [[2024]]},
                "container-title": ["Sustainable Energy, Grids and Networks"],
                "score": 35.2,
                "type": "journal-article",
            },
        ],
    },
}

CROSSREF_EMPTY_RESPONSE = {
    "status": "ok",
    "message": {
        "total-results": 0,
        "items": [],
    },
}


class TestCrossrefBibliographicSearch:
    def test_happy_path_returns_hits(self, httpserver, monkeypatch):
        """bibliographic_search() returns parsed hits on 200."""
        httpserver.expect_request("/works").respond_with_json(CROSSREF_SEARCH_RESPONSE)
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("Zhang 2025 Beyond simplifications low-voltage")

        assert len(hits) == 2

        top = hits[0]
        assert top["doi"] == "10.1016/j.segan.2025.01.001"
        assert "Beyond simplifications" in top["title"]
        assert top["year"] == 2025
        assert top["score"] == pytest.approx(285.6)
        assert "J. Zhang" in top["authors"]
        assert top["container_title"] == "Sustainable Energy, Grids and Networks"

    def test_empty_response(self, httpserver, monkeypatch):
        """bibliographic_search() returns [] when Crossref returns no items."""
        httpserver.expect_request("/works").respond_with_json(CROSSREF_EMPTY_RESPONSE)
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("completely unrecognised text XYZZY 9999")
        assert hits == []

    def test_network_error_returns_empty(self, monkeypatch):
        """bibliographic_search() returns [] on network error (soft fail)."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            "http://127.0.0.1:19998/works",
        )
        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("network error test")
        assert hits == []

    def test_non200_returns_empty(self, httpserver, monkeypatch):
        """bibliographic_search() returns [] on non-200 response."""
        httpserver.expect_request("/works").respond_with_data(
            "Service Unavailable", status=503, content_type="text/plain"
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("test query")
        assert hits == []

    def test_429_gives_up_after_retry(self, httpserver, monkeypatch):
        """bibliographic_search() returns [] after 429 exhausts retries."""
        httpserver.expect_request("/works").respond_with_data(
            "Rate limited", status=429, content_type="text/plain",
            headers={"Retry-After": "0"},
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )
        monkeypatch.setattr("zotcli.write.resolvers.crossref.time.sleep", lambda s: None)

        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("rate limited test")
        assert hits == []

    def test_authors_parsed_correctly(self, httpserver, monkeypatch):
        """Authors are parsed as 'given family' strings."""
        httpserver.expect_request("/works").respond_with_json(CROSSREF_SEARCH_RESPONSE)
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref._BASE_URL",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.crossref import bibliographic_search
        hits = bibliographic_search("test")
        authors = hits[0]["authors"]
        assert "F. Geth" in authors
        assert "R. Heidari" in authors
