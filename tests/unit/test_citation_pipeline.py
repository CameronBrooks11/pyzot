"""Tests for citation_pipeline.resolve_citation().

Uses the §4.1 worked example from PLAN_WRITE.md:
  "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications:
   Evaluating assumptions for low-voltage network modelling in the DER era.
   Sustainable Energy, Grids and Networks, 2025."

Covers:
- High-confidence auto-accept flow (single unambiguous top hit)
- Ambiguous → interactive pick flow
- Non-interactive ambiguous → fall-through (OpenAlex)
- Fully unresolved flow → returns None
- Normalisation of whitespace + smart quotes
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Fixtures / constants
# ---------------------------------------------------------------------------

ZHANG_CITATION = (
    "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: "
    "Evaluating assumptions for low-voltage network modelling in the DER era. "
    "Sustainable Energy, Grids and Networks, 2025."
)

ZHANG_DOI = "10.1016/j.segan.2025.01.001"

CROSSREF_TOP_HIT = {
    "doi": ZHANG_DOI,
    "title": "Beyond simplifications: Evaluating assumptions for low-voltage network modelling",
    "authors": ["J. Zhang", "F. Geth", "R. Heidari", "G. Verbič"],
    "year": 2025,
    "score": 285.6,
    "container_title": "Sustainable Energy, Grids and Networks",
    "type": "journal-article",
}

CROSSREF_SECOND_HIT = {
    "doi": "10.1016/j.segan.2024.12.999",
    "title": "Low-voltage network assumptions revisited",
    "authors": ["A. Smith"],
    "year": 2024,
    "score": 35.2,
    "container_title": "Sustainable Energy, Grids and Networks",
    "type": "journal-article",
}

# CSL-JSON that crossref.resolve returns
ZHANG_CSL = {
    "type": "journal-article",
    "title": ["Beyond simplifications: Evaluating assumptions for low-voltage network modelling in the DER era"],
    "author": [
        {"given": "J.", "family": "Zhang"},
        {"given": "F.", "family": "Geth"},
        {"given": "R.", "family": "Heidari"},
        {"given": "G.", "family": "Verbič"},
    ],
    "issued": {"date-parts": [[2025]]},
    "DOI": ZHANG_DOI,
    "container-title": ["Sustainable Energy, Grids and Networks"],
    "publisher": "Elsevier",
    "score": 285.6,
}


class TestResolveCitationHighConfidence:
    """Auto-accept path: single high-confidence Crossref hit."""

    def test_high_confidence_single_hit_auto_accepted(self, monkeypatch):
        """When top hit score >> threshold and gap criterion met, auto-accepts without prompting."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [CROSSREF_TOP_HIT, CROSSREF_SECOND_HIT],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL if doi == ZHANG_DOI else {},
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=False)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI
        assert "Beyond simplifications" in (result.get("title") or [""])[0]

    def test_auto_accept_when_only_one_hit(self, monkeypatch):
        """Auto-accepts the sole Crossref hit if score >= threshold."""
        sole_hit = dict(CROSSREF_TOP_HIT, score=80.0)
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [sole_hit],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL,
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=False)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI

    def test_gap_ratio_below_threshold_triggers_fallthrough(self, monkeypatch):
        """When gap ratio is too small (ambiguous), falls through in non-interactive mode."""
        # Scores: 60.0 and 55.0 → gap = 60/55 = 1.09 < 1.4
        hit1 = dict(CROSSREF_TOP_HIT, score=60.0)
        hit2 = dict(CROSSREF_SECOND_HIT, score=55.0)

        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [hit1, hit2],
        )
        # Fall through to OpenAlex which returns nothing
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.semantic_scholar.search",
            lambda text, limit: [],
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=False)

        # non-interactive + ambiguous → None
        assert result is None


class TestResolveCitationInteractive:
    """Interactive disambiguation flow."""

    def test_interactive_user_picks_first(self, monkeypatch):
        """User picks candidate #1, which resolves to the expected DOI."""
        # Scores too close for auto-accept: gap = 60/55 < 1.4
        hit1 = dict(CROSSREF_TOP_HIT, score=60.0)
        hit2 = dict(CROSSREF_SECOND_HIT, score=55.0)

        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [hit1, hit2],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL,
        )
        # Simulate user typing "1"
        monkeypatch.setattr("builtins.input", lambda prompt: "1")

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=True)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI

    def test_interactive_user_picks_n_falls_through(self, monkeypatch):
        """User picks 'n' (none) → falls through to OpenAlex."""
        hit1 = dict(CROSSREF_TOP_HIT, score=60.0)
        hit2 = dict(CROSSREF_SECOND_HIT, score=55.0)

        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [hit1, hit2],
        )
        monkeypatch.setattr("builtins.input", lambda prompt: "n")

        # OpenAlex returns the DOI
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [
                {"doi": ZHANG_DOI, "title": "Beyond simplifications", "authors": [], "year": 2025, "score": None}
            ],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL,
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=True)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI

    def test_interactive_eof_falls_through(self, monkeypatch):
        """EOFError during input (non-TTY) treated like 'n', falls through."""
        hit1 = dict(CROSSREF_TOP_HIT, score=60.0)
        hit2 = dict(CROSSREF_SECOND_HIT, score=55.0)

        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [hit1, hit2],
        )

        def raise_eof(prompt):
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.semantic_scholar.search",
            lambda text, limit: [],
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, threshold=50, gap=1.4, interactive=True)
        # Falls through all fallbacks, returns None
        assert result is None


class TestResolveCitationOpenAlexFallback:
    """OpenAlex fallback flow."""

    def test_openalex_fallback_when_crossref_empty(self, monkeypatch):
        """When Crossref returns nothing, OpenAlex top DOI is used."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [
                {
                    "doi": ZHANG_DOI,
                    "title": "Beyond simplifications",
                    "authors": ["J. Zhang"],
                    "year": 2025,
                    "score": 2345.67,
                }
            ],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL,
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, interactive=False)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI


class TestResolveCitationSemanticScholarFallback:
    """Semantic Scholar fallback flow."""

    def test_s2_fallback_when_crossref_and_openalex_empty(self, monkeypatch):
        """When Crossref + OpenAlex return nothing, S2 top DOI is used."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.semantic_scholar.search",
            lambda text, limit: [
                {
                    "doi": ZHANG_DOI,
                    "title": "Beyond simplifications",
                    "authors": ["J. Zhang"],
                    "year": 2025,
                }
            ],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.resolve",
            lambda doi: ZHANG_CSL,
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation(ZHANG_CITATION, interactive=False)

        assert result is not None
        assert result["DOI"] == ZHANG_DOI


class TestResolveCitationFullyUnresolved:
    """All strategies fail → None."""

    def test_returns_none_when_all_fallbacks_empty(self, monkeypatch):
        """Returns None when Crossref, OpenAlex, and S2 all return nothing."""
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.openalex.search",
            lambda text, per_page: [],
        )
        monkeypatch.setattr(
            "zotcli.write.resolvers.semantic_scholar.search",
            lambda text, limit: [],
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation("This citation matches nothing.", interactive=False)

        assert result is None

    def test_returns_none_for_empty_string(self, monkeypatch):
        """Empty string input returns None immediately."""
        # No resolver calls should be made
        crossref_called = []
        monkeypatch.setattr(
            "zotcli.write.resolvers.crossref.bibliographic_search",
            lambda text, rows: crossref_called.append(text) or [],
        )

        from zotcli.write.citation_pipeline import resolve_citation
        result = resolve_citation("", interactive=False)

        assert result is None
        assert crossref_called == []  # resolver never called for empty input


class TestCitationNormalisation:
    """Text normalisation before search."""

    def test_smart_quotes_normalised(self, monkeypatch):
        """Smart quotes are replaced with straight quotes before searching."""
        captured = []

        def mock_search(text, rows):
            captured.append(text)
            return []

        monkeypatch.setattr("zotcli.write.resolvers.crossref.bibliographic_search", mock_search)
        monkeypatch.setattr("zotcli.write.resolvers.openalex.search", lambda t, per_page: [])
        monkeypatch.setattr("zotcli.write.resolvers.semantic_scholar.search", lambda t, limit: [])

        from zotcli.write.citation_pipeline import resolve_citation
        resolve_citation("‘smart’ quotes “test”", interactive=False)

        assert captured
        assert "‘" not in captured[0]
        assert "’" not in captured[0]
        assert "smart" in captured[0]

    def test_extra_whitespace_collapsed(self, monkeypatch):
        """Extra whitespace is collapsed to single spaces."""
        captured = []

        def mock_search(text, rows):
            captured.append(text)
            return []

        monkeypatch.setattr("zotcli.write.resolvers.crossref.bibliographic_search", mock_search)
        monkeypatch.setattr("zotcli.write.resolvers.openalex.search", lambda t, per_page: [])
        monkeypatch.setattr("zotcli.write.resolvers.semantic_scholar.search", lambda t, limit: [])

        from zotcli.write.citation_pipeline import resolve_citation
        resolve_citation("  Zhang,   J.    (2025)   Beyond  simplifications  ", interactive=False)

        assert captured
        assert "  " not in captured[0]  # no double spaces
