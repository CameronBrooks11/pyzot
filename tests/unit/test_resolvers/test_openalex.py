"""Tests for OpenAlex resolver using pytest-httpserver."""

from __future__ import annotations

import json

import pytest


OPENALEX_SEARCH_RESPONSE = {
    "results": [
        {
            "id": "https://openalex.org/W1234567",
            "doi": "https://doi.org/10.1016/j.segan.2025.01.001",
            "title": "Beyond simplifications: Evaluating assumptions for low-voltage network modelling",
            "authorships": [
                {"author": {"display_name": "Zhang, J.", "orcid": None}},
                {"author": {"display_name": "Geth, F.", "orcid": None}},
            ],
            "publication_year": 2025,
            "relevance_score": 2345.67,
        },
        {
            "id": "https://openalex.org/W9999999",
            "doi": None,  # no DOI — should be filtered out
            "title": "Some other paper",
            "authorships": [],
            "publication_year": 2020,
            "relevance_score": 10.0,
        },
    ],
    "meta": {"count": 2, "per_page": 5},
}

OPENALEX_WORK_RESPONSE = {
    "id": "https://openalex.org/W1234567",
    "doi": "https://doi.org/10.1016/j.segan.2025.01.001",
    "title": "Beyond simplifications",
    "type": "journal-article",
    "authorships": [
        {"author": {"display_name": "Zhang, J.", "orcid": "https://orcid.org/0000-0001-2345-6789"}},
    ],
    "publication_year": 2025,
    "primary_location": {
        "source": {"display_name": "Sustainable Energy, Grids and Networks"}
    },
    "abstract_inverted_index": {"Beyond": [0], "simplifications": [1]},
}


class TestOpenAlexSearch:
    def test_search_returns_filtered_hits(self, httpserver, monkeypatch):
        """search() returns hits with DOIs and filters out those without."""
        httpserver.expect_request("/works").respond_with_json(OPENALEX_SEARCH_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.openalex._BASE_URL",
            httpserver.url_for(""),
        )

        from pyzot.write.resolvers.openalex import search
        hits = search("Beyond simplifications low-voltage network modelling")

        # Should only return 1 hit (the one with a DOI)
        assert len(hits) == 1
        assert hits[0]["doi"] == "10.1016/j.segan.2025.01.001"  # stripped prefix
        assert hits[0]["year"] == 2025
        assert hits[0]["score"] == pytest.approx(2345.67)

    def test_search_returns_empty_on_network_error(self, monkeypatch):
        """search() returns [] on network failure (soft fail)."""
        import httpx

        def mock_get(*args, **kwargs):
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr("httpx.Client.get", mock_get)

        from pyzot.write.resolvers.openalex import search
        hits = search("some query")
        assert hits == []

    def test_search_returns_empty_on_non200(self, httpserver, monkeypatch):
        """search() returns [] on non-200 response."""
        httpserver.expect_request("/works").respond_with_data(
            "Service Unavailable", status=503, content_type="text/plain"
        )
        monkeypatch.setattr(
            "pyzot.write.resolvers.openalex._BASE_URL",
            httpserver.url_for(""),
        )

        from pyzot.write.resolvers.openalex import search
        hits = search("test query")
        assert hits == []

    def test_search_doi_prefix_stripped(self, httpserver, monkeypatch):
        """search() strips https://doi.org/ prefix from DOIs."""
        response = {
            "results": [
                {
                    "id": "https://openalex.org/W111",
                    "doi": "https://doi.org/10.9999/test",
                    "title": "Test paper",
                    "authorships": [],
                    "publication_year": 2023,
                    "relevance_score": 100.0,
                }
            ],
            "meta": {"count": 1},
        }
        httpserver.expect_request("/works").respond_with_json(response)
        monkeypatch.setattr(
            "pyzot.write.resolvers.openalex._BASE_URL",
            httpserver.url_for(""),
        )

        from pyzot.write.resolvers.openalex import search
        hits = search("test paper")
        assert hits[0]["doi"] == "10.9999/test"


class TestOpenAlexResolve:
    def test_resolve_by_doi(self, httpserver, monkeypatch):
        """resolve() fetches a work by DOI and returns CSL-JSON."""
        doi = "10.1016/j.segan.2025.01.001"
        httpserver.expect_request(
            f"/works/https://doi.org/{doi}"
        ).respond_with_json(OPENALEX_WORK_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.openalex._BASE_URL",
            httpserver.url_for(""),
        )

        from pyzot.write.resolvers.openalex import resolve
        csl = resolve(doi)

        assert csl["type"] == "journal-article"
        assert "Beyond simplifications" in csl["title"]
        assert csl["DOI"] == "10.1016/j.segan.2025.01.001"
        assert csl["issued"]["date-parts"] == [[2025]]
        assert csl["container-title"] == "Sustainable Energy, Grids and Networks"

    def test_resolve_404_raises_lookup_error(self, httpserver, monkeypatch):
        """resolve() raises LookupError on 404."""
        httpserver.expect_request(
            "/works/https://doi.org/10.9999/bad"
        ).respond_with_data("Not Found", status=404, content_type="text/plain")

        monkeypatch.setattr(
            "pyzot.write.resolvers.openalex._BASE_URL",
            httpserver.url_for(""),
        )

        from pyzot.write.resolvers.openalex import resolve
        with pytest.raises(LookupError):
            resolve("10.9999/bad")

    def test_reconstruct_abstract(self):
        """_reconstruct_abstract correctly assembles text from inverted index."""
        from pyzot.write.resolvers.openalex import _reconstruct_abstract
        inverted = {"Hello": [0], "world": [1], "test": [2]}
        result = _reconstruct_abstract(inverted)
        assert result == "Hello world test"

    def test_reconstruct_abstract_empty(self):
        """_reconstruct_abstract returns empty string for empty index."""
        from pyzot.write.resolvers.openalex import _reconstruct_abstract
        assert _reconstruct_abstract({}) == ""
        assert _reconstruct_abstract("not a dict") == ""
