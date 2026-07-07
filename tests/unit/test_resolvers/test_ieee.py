"""Tests for IEEE Xplore URL → DOI resolver.

Covers:
- Strategy 1: DOI regex in URL
- Strategy 2: IEEE metadata REST endpoint (success + 401/403 soft-fail)
- Strategy 3: Crossref reverse search fallback
- Non-IEEE URL (no arnumber) → None
"""

from __future__ import annotations

import pytest


class TestIeeeUrlToDoi:
    """Tests for ieee.url_to_doi()."""

    # ------------------------------------------------------------------
    # Strategy 1: DOI in URL
    # ------------------------------------------------------------------

    def test_doi_in_url_path(self):
        """Extracts DOI embedded directly in the URL path."""
        from zotcli.write.resolvers.ieee import url_to_doi

        url = "https://ieeexplore.ieee.org/document/doi/10.1109/TPWRS.2023.1234567"
        doi = url_to_doi(url)
        assert doi == "10.1109/TPWRS.2023.1234567"

    def test_doi_in_query_param(self):
        """Extracts DOI from a 'doi' query parameter."""
        from zotcli.write.resolvers.ieee import url_to_doi

        url = "https://ieeexplore.ieee.org/search?doi=10.1109/ACCESS.2023.9876543"
        doi = url_to_doi(url)
        assert doi == "10.1109/ACCESS.2023.9876543"

    # ------------------------------------------------------------------
    # Strategy 2: IEEE metadata endpoint
    # ------------------------------------------------------------------

    def test_ieee_metadata_returns_doi(self, httpserver, monkeypatch):
        """Fetches metadata from IEEE REST endpoint and extracts DOI."""
        arnumber = "9876543"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_json(
            {"doi": "10.1109/TPWRS.2023.9876543", "title": "A smart grid paper"}
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )
        # No Crossref needed — metadata should succeed
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_crossref_reverse",
            lambda arnumber, threshold: None,
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/document/{arnumber}"
        doi = url_to_doi(url)
        assert doi == "10.1109/TPWRS.2023.9876543"

    def test_ieee_metadata_401_soft_fail(self, httpserver, monkeypatch):
        """On 401 from metadata endpoint, soft-fails and falls through."""
        arnumber = "9876543"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_data(
            "Unauthorized", status=401, content_type="text/plain"
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )
        # Crossref fallback also returns None for this test
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_crossref_reverse",
            lambda arnumber, threshold: None,
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/document/{arnumber}"
        doi = url_to_doi(url)
        assert doi is None  # soft fail, no exception

    def test_ieee_metadata_403_soft_fail(self, httpserver, monkeypatch):
        """On 403 from metadata endpoint, soft-fails and falls through."""
        arnumber = "9876543"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_data(
            "Forbidden", status=403, content_type="text/plain"
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_crossref_reverse",
            lambda arnumber, threshold: None,
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/document/{arnumber}"
        doi = url_to_doi(url)
        assert doi is None

    def test_ieee_metadata_list_response(self, httpserver, monkeypatch):
        """Handles metadata endpoint returning a JSON list (array of objects)."""
        arnumber = "1234567"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_json(
            [{"doi": "10.1109/ACCESS.2023.1234567", "title": "Paper"}]
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/document/{arnumber}"
        doi = url_to_doi(url)
        assert doi == "10.1109/ACCESS.2023.1234567"

    # ------------------------------------------------------------------
    # Strategy 3: Crossref reverse search
    # ------------------------------------------------------------------

    def test_crossref_reverse_used_when_metadata_fails(self, httpserver, monkeypatch):
        """Falls back to Crossref reverse search when metadata fails."""
        arnumber = "9876543"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_data(
            "Not Found", status=404, content_type="text/plain"
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )

        # Mock the crossref fallback to return a DOI
        crossref_doi = "10.1109/TPWRS.2023.9876543"
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_crossref_reverse",
            lambda an, threshold: crossref_doi if an == arnumber else None,
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/document/{arnumber}"
        doi = url_to_doi(url)
        assert doi == crossref_doi

    def test_crossref_reverse_score_below_threshold_rejected(self, monkeypatch):
        """_try_crossref_reverse rejects hits with score below threshold."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_ieee_metadata",
            lambda an: None,
        )

        low_score_hits = [{"doi": "10.1109/X.2023.1", "score": 20.0}]
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: low_score_hits,
        )

        from zotcli.write.resolvers.ieee import _try_crossref_reverse
        doi = _try_crossref_reverse("9876543", score_threshold=50)
        assert doi is None  # low score rejected

    def test_crossref_reverse_score_above_threshold_accepted(self, monkeypatch):
        """_try_crossref_reverse accepts hits with score >= threshold."""
        high_score_hits = [{"doi": "10.1109/X.2023.2", "score": 75.0}]
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: high_score_hits,
        )

        from zotcli.write.resolvers.ieee import _try_crossref_reverse
        doi = _try_crossref_reverse("9876543", score_threshold=50)
        assert doi == "10.1109/X.2023.2"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_arnumber_returns_none(self):
        """Returns None when URL contains no arnumber and no DOI."""
        from zotcli.write.resolvers.ieee import url_to_doi

        doi = url_to_doi("https://ieeexplore.ieee.org/search?query=machine+learning")
        assert doi is None

    def test_arnumber_in_query_string(self, httpserver, monkeypatch):
        """Extracts arnumber from ?arnumber= query param."""
        arnumber = "5678901"
        httpserver.expect_request(f"/rest/document/{arnumber}/metadata").respond_with_json(
            {"doi": "10.1109/TSP.2023.5678901"}
        )

        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._IEEE_METADATA_BASE",
            httpserver.url_for("/rest/document"),
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.ieee._try_crossref_reverse",
            lambda an, threshold: None,
        )

        from zotcli.write.resolvers.ieee import url_to_doi

        url = f"https://ieeexplore.ieee.org/xpl/articleDetails.jsp?arnumber={arnumber}"
        doi = url_to_doi(url)
        assert doi == "10.1109/TSP.2023.5678901"
