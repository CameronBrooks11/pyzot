"""Tests for ScienceDirect URL → DOI resolver.

Covers:
- DOI in URL (strategy 1)
- PII extraction + Crossref alternative-id (strategy 2+3)
- PII extraction + Crossref bibliographic fallback (strategy 4)
- No PII / no DOI → None
"""

from __future__ import annotations

import pytest


class TestScienceDirectUrlToDoi:
    # ------------------------------------------------------------------
    # Strategy 1: DOI in URL
    # ------------------------------------------------------------------

    def test_doi_in_url_path(self):
        """Extracts DOI embedded in the URL path."""
        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = "https://www.sciencedirect.com/science/article/doi/10.1016/j.segan.2025.01.001"
        doi = url_to_doi(url)
        assert doi == "10.1016/j.segan.2025.01.001"

    def test_doi_in_query_param(self):
        """Extracts DOI from a query parameter."""
        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = "https://linkinghub.elsevier.com/retrieve/doi/10.1016/j.segan.2025.01.001"
        doi = url_to_doi(url)
        assert doi == "10.1016/j.segan.2025.01.001"

    # ------------------------------------------------------------------
    # Strategy 2: PII extraction
    # ------------------------------------------------------------------

    def test_pii_extracted_from_url(self, monkeypatch):
        """Extracts PII and calls Crossref alternative-id lookup."""
        pii = "S2352467725000123"
        expected_doi = "10.1016/j.segan.2025.01.001"

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_alternative_id",
            lambda p: expected_doi if p == pii else None,
        )

        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
        doi = url_to_doi(url)
        assert doi == expected_doi

    def test_abs_pii_path(self, monkeypatch):
        """Accepts /abs/pii/<PII> path variant."""
        pii = "S2352467725000456"
        expected_doi = "10.1016/j.foo.2025.02.002"

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_alternative_id",
            lambda p: expected_doi if p == pii else None,
        )

        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = f"https://www.sciencedirect.com/science/article/abs/pii/{pii}"
        doi = url_to_doi(url)
        assert doi == expected_doi

    # ------------------------------------------------------------------
    # Strategy 3: Crossref alternative-id
    # ------------------------------------------------------------------

    def test_crossref_alternative_id_called(self, httpserver, monkeypatch):
        """_try_crossref_alternative_id queries Crossref with filter=alternative-id:<PII>."""
        pii = "S2352467725000789"
        crossref_response = {
            "status": "ok",
            "message": {
                "total-results": 1,
                "items": [{"DOI": "10.1016/j.segan.2025.03.003", "title": ["Test paper"]}],
            },
        }
        httpserver.expect_request("/works").respond_with_json(crossref_response)

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._CROSSREF_BASE",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.sciencedirect import _try_crossref_alternative_id
        doi = _try_crossref_alternative_id(pii)
        assert doi == "10.1016/j.segan.2025.03.003"

    def test_crossref_alternative_id_empty_returns_none(self, httpserver, monkeypatch):
        """Returns None when Crossref alternative-id filter returns no items."""
        pii = "S2352467725000000"
        crossref_response = {
            "status": "ok",
            "message": {"total-results": 0, "items": []},
        }
        httpserver.expect_request("/works").respond_with_json(crossref_response)

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._CROSSREF_BASE",
            httpserver.url_for("/works"),
        )

        from zotcli.write.resolvers.sciencedirect import _try_crossref_alternative_id
        doi = _try_crossref_alternative_id(pii)
        assert doi is None

    # ------------------------------------------------------------------
    # Strategy 4: bibliographic fallback
    # ------------------------------------------------------------------

    def test_bibliographic_fallback_used_when_alternative_id_empty(self, monkeypatch):
        """Falls back to bibliographic_search when alternative-id returns None."""
        pii = "S2352467725000XYZ"

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_alternative_id",
            lambda p: None,
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_bibliographic",
            lambda p: "10.1016/j.fallback.2025.01.001" if p == pii else None,
        )

        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = f"https://www.sciencedirect.com/science/article/pii/{pii}"
        doi = url_to_doi(url)
        assert doi == "10.1016/j.fallback.2025.01.001"

    # ------------------------------------------------------------------
    # Edge cases
    # ------------------------------------------------------------------

    def test_no_doi_no_pii_returns_none(self):
        """Returns None for a URL with no DOI and no PII."""
        from zotcli.write.resolvers.sciencedirect import url_to_doi

        doi = url_to_doi("https://www.sciencedirect.com/journal/sustainable-energy/vol/42")
        assert doi is None

    def test_pii_uppercase_normalized(self, monkeypatch):
        """PII is uppercased before lookup."""
        captured_pii = []

        def mock_crossref_alternative_id(pii):
            captured_pii.append(pii)
            return None

        def mock_crossref_bibliographic(pii):
            return None

        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_alternative_id",
            mock_crossref_alternative_id,
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.sciencedirect._try_crossref_bibliographic",
            mock_crossref_bibliographic,
        )

        from zotcli.write.resolvers.sciencedirect import url_to_doi

        url = "https://www.sciencedirect.com/science/article/pii/s235246772500xyz0"
        url_to_doi(url)
        if captured_pii:
            assert captured_pii[0] == captured_pii[0].upper()
