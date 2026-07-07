"""Tests for Semantic Scholar resolver using pytest-httpserver.

Covers:
- Normal search
- 429 retry behaviour (sleep + retry once)
- Second 429 = give up softly (return [])
- Network error → []
- Filter out hits with no DOI
"""

from __future__ import annotations

SS_SEARCH_RESPONSE = {
    "total": 2,
    "data": [
        {
            "paperId": "abc123",
            "externalIds": {"DOI": "10.1016/j.segan.2025.01.001"},
            "title": "Beyond simplifications in network modelling",
            "authors": [
                {"authorId": "1", "name": "Zhang, J."},
                {"authorId": "2", "name": "Geth, F."},
            ],
            "year": 2025,
        },
        {
            "paperId": "xyz789",
            "externalIds": {},  # no DOI — should be filtered
            "title": "Some paper without a DOI",
            "authors": [{"authorId": "3", "name": "Doe, J."}],
            "year": 2023,
        },
    ],
}


class TestSemanticScholarSearch:
    def test_search_returns_filtered_hits(self, httpserver, monkeypatch):
        """search() returns hits with DOIs; filters out those without."""
        # The module uses f"{_BASE_URL}/paper/search" so the handler must be at /paper/search
        httpserver.expect_request("/paper/search").respond_with_json(SS_SEARCH_RESPONSE)

        # Set _BASE_URL to the httpserver base without trailing slash
        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("Beyond simplifications network modelling")

        assert len(hits) == 1
        assert hits[0]["doi"] == "10.1016/j.segan.2025.01.001"
        assert hits[0]["year"] == 2025
        assert "Zhang, J." in hits[0]["authors"]

    def test_search_filters_no_doi(self, httpserver, monkeypatch):
        """search() filters out hits with no DOI in externalIds."""
        response = {
            "total": 1,
            "data": [
                {
                    "paperId": "no-doi",
                    "externalIds": {"ArXiv": "2401.12345"},
                    "title": "Only ArXiv, no DOI",
                    "authors": [],
                    "year": 2024,
                }
            ],
        }
        httpserver.expect_request("/paper/search").respond_with_json(response)
        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("test query no doi")
        assert hits == []

    def test_429_retry_then_success(self, httpserver, monkeypatch):
        """On first 429, sleep 2s and retry; succeed on second attempt."""
        # First request → 429
        httpserver.expect_ordered_request("/paper/search").respond_with_data(
            "Rate limited",
            status=429,
            content_type="text/plain",
            headers={"Retry-After": "0"},
        )
        # Second request → 200
        httpserver.expect_ordered_request("/paper/search").respond_with_json(SS_SEARCH_RESPONSE)

        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )
        # Patch time.sleep to avoid actually sleeping
        monkeypatch.setattr("pyzot.write.resolvers.semantic_scholar.time.sleep", lambda s: None)

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("Beyond simplifications")
        assert len(hits) == 1
        assert hits[0]["doi"] == "10.1016/j.segan.2025.01.001"

    def test_429_twice_gives_up_softly(self, httpserver, monkeypatch):
        """On second consecutive 429, give up and return []."""
        httpserver.expect_ordered_request("/paper/search").respond_with_data(
            "Rate limited",
            status=429,
            content_type="text/plain",
            headers={"Retry-After": "0"},
        )
        httpserver.expect_ordered_request("/paper/search").respond_with_data(
            "Still rate limited",
            status=429,
            content_type="text/plain",
            headers={"Retry-After": "0"},
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )
        monkeypatch.setattr("pyzot.write.resolvers.semantic_scholar.time.sleep", lambda s: None)

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("rate limited query")
        assert hits == []

    def test_network_error_returns_empty(self, monkeypatch):
        """On network error, returns [] (soft fail)."""

        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            "http://127.0.0.1:19998",  # nothing listening
        )

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("network error test")
        assert hits == []

    def test_non200_returns_empty(self, httpserver, monkeypatch):
        """On non-200 non-429 response, returns [] (soft fail)."""
        httpserver.expect_request("/paper/search").respond_with_data(
            "Internal Server Error", status=500, content_type="text/plain"
        )
        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )

        from pyzot.write.resolvers.semantic_scholar import search

        hits = search("server error test")
        assert hits == []

    def test_api_key_sent_in_header(self, httpserver, monkeypatch):
        """API key from config is sent as x-api-key header."""
        # Use httpserver.log to inspect requests after the fact
        httpserver.expect_request("/paper/search").respond_with_json({"total": 0, "data": []})

        monkeypatch.setattr(
            "pyzot.write.resolvers.semantic_scholar._BASE_URL",
            httpserver.url_for("").rstrip("/"),
        )

        import pyzot.write.resolvers.semantic_scholar as ss_module

        monkeypatch.setattr(ss_module, "_get_api_key", lambda: "test-api-key-123")

        ss_module.search("test")

        # Check the request log for the x-api-key header
        assert httpserver.log, "No requests recorded"
        request, _ = httpserver.log[-1]
        assert request.headers.get("x-api-key") == "test-api-key-123"
