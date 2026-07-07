"""Integration tests for the zot add pipeline.

Uses pytest-httpserver to mock the Zotero connector.
Monkeypatches resolvers so no live network is needed.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli

# ---------------------------------------------------------------------------
# Shared CSL-JSON fixture that resolvers will return
# ---------------------------------------------------------------------------

MOCK_DOI_CSL = {
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
    "abstract": "Array programming provides powerful abstractions.",
    "language": "en",
}

MOCK_ARXIV_CSL = {
    "type": "posted-content",
    "subtype": "preprint",
    "title": "Attention Is All You Need",
    "author": [{"given": "Ashish", "family": "Vaswani"}],
    "issued": {"date-parts": [[2017, 6]]},
    "archive": "arXiv",
    "archive_location": "1706.03762",
}

MOCK_PMID_CSL = {
    "type": "journal-article",
    "title": "Molegro Virtual Docker for Docking",
    "author": [{"given": "Rene", "family": "Thomsen"}],
    "issued": {"date-parts": [[2019]]},
    "DOI": "10.1007/978-1-4939-9752-7_9",
    "container-title": "Methods in molecular biology",
}

MOCK_ISBN_CSL = {
    "type": "book",
    "title": "Introduction to Algorithms",
    "author": [{"given": "Thomas H.", "family": "Cormen"}],
    "issued": {"date-parts": [[2009]]},
    "ISBN": "9780262033848",
    "publisher": "MIT Press",
}

# Connector responses
SAVE_ITEMS_RESPONSE = {"items": [{"key": "NEWITEM1", "itemType": "journalArticle"}]}

UPDATE_SESSION_RESPONSE = {}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_connector(httpserver):
    """Configure httpserver to act as the Zotero connector."""
    httpserver.expect_request("/connector/ping").respond_with_json({"version": "7.0.0"})
    httpserver.expect_request("/connector/saveItems").respond_with_json(
        SAVE_ITEMS_RESPONSE, status=201
    )
    httpserver.expect_request("/connector/updateSession").respond_with_json(UPDATE_SESSION_RESPONSE)
    return httpserver


def _resolver_side_effect(kind: str, csl: dict):
    """Return a patched resolve function that returns the given CSL dict."""

    def patched_resolve(_identifier):
        return csl

    return patched_resolve


# ---------------------------------------------------------------------------
# Dry-run tests (no connector call)
# ---------------------------------------------------------------------------


class TestDryRun:
    def test_doi_dry_run(self, runner, monkeypatch):
        """--dry-run prints JSON without calling the connector."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.dedup.find_by_doi",
            lambda db, doi: None,
        )
        # Patch _open_db to return None (no DB needed for dry-run)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        output = result.output
        payload = json.loads(output)
        assert "items" in payload
        assert payload["items"][0]["itemType"] == "journalArticle"
        # No sessionID in the real connector call when dry-run
        assert payload["sessionID"] == "<dry-run>"

    def test_arxiv_dry_run(self, runner, monkeypatch):
        """--dry-run for arxiv prints JSON without connector call."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "arxiv", "1706.03762", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "preprint"

    def test_pmid_dry_run(self, runner, monkeypatch):
        """--dry-run for pmid prints JSON without connector call."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.pubmed.resolve",
            lambda pmid: MOCK_PMID_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "pmid", "31452104", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "journalArticle"

    def test_isbn_dry_run(self, runner, monkeypatch):
        """--dry-run for isbn prints JSON without connector call."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary.resolve",
            lambda isbn: MOCK_ISBN_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "isbn", "9780262033848", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "book"

    def test_dry_run_includes_collection_in_payload(self, runner, monkeypatch):
        """--dry-run with --collection includes it in the printed JSON."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2", "--dry-run", "--collection", "Smart Grid"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload.get("_collection") == "Smart Grid"

    def test_dry_run_includes_tags_in_payload(self, runner, monkeypatch):
        """--dry-run with --tag includes tags in the printed JSON."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            [
                "add",
                "doi",
                "10.1038/s41586-020-2649-2",
                "--dry-run",
                "--tag",
                "numpy",
                "--tag",
                "ml",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "numpy" in payload.get("_tags", [])
        assert "ml" in payload.get("_tags", [])


# ---------------------------------------------------------------------------
# Duplicate detection tests
# ---------------------------------------------------------------------------


class TestDuplicateDetection:
    def test_duplicate_doi_exits_0_no_connector_call(self, runner, mock_connector, monkeypatch):
        """When a duplicate DOI is found, exits 0 and does NOT call /saveItems."""
        from pyzot.write.dedup import ItemRef

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.cli.add._find_duplicate",
            lambda kind, identifier: ItemRef(
                key="EXIST001", title="Deep Learning for NLP", item_id=1
            ),
        )

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/example"],
        )
        assert result.exit_code == 0, result.output
        assert "EXIST001" in result.output
        assert "already exists" in result.output

        # Verify /connector/saveItems was NOT called
        # mock_connector.log is a list of (Request, Response) tuples
        for req, _resp in mock_connector.log:
            assert "/connector/saveItems" not in req.path, (
                "/connector/saveItems should not have been called for a duplicate"
            )

    def test_force_add_bypasses_dedup(self, runner, mock_connector, monkeypatch):
        """--on-duplicate=force-add skips dedup and calls the connector."""
        from pyzot.write.dedup import ItemRef

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)
        # Even though dedup would return a match, force-add bypasses it
        monkeypatch.setattr(
            "pyzot.cli.add._find_duplicate",
            lambda kind, identifier: ItemRef(key="EXIST001", title="Old Item", item_id=1),
        )

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2", "--on-duplicate", "force-add"],
        )
        # Should call the connector, not bail out
        assert result.exit_code == 0, result.output
        # Check that saveItems WAS called
        # mock_connector.log is a list of (Request, Response) tuples
        save_items_called = any(
            "/connector/saveItems" in req.path for req, _resp in mock_connector.log
        )
        assert save_items_called, "saveItems should have been called with force-add"


# ---------------------------------------------------------------------------
# Success path tests
# ---------------------------------------------------------------------------


class TestSuccessPath:
    def test_doi_add_success(self, runner, mock_connector, monkeypatch):
        """Successful doi add prints the item key."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2"],
        )
        assert result.exit_code == 0, result.output
        assert "NEWITEM1" in result.output

    def test_doi_add_with_tags_calls_update_session(self, runner, mock_connector, monkeypatch):
        """Adding tags triggers a POST to /connector/updateSession."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2", "--tag", "numpy"],
        )
        assert result.exit_code == 0, result.output
        # mock_connector.log is a list of (Request, Response) tuples
        update_called = any(
            "/connector/updateSession" in req.path for req, _resp in mock_connector.log
        )
        assert update_called, "updateSession should have been called when --tag is passed"

    def test_arxiv_add_success(self, runner, mock_connector, monkeypatch):
        """Successful arxiv add prints the item key."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "arxiv", "1706.03762"],
        )
        assert result.exit_code == 0, result.output
        assert "NEWITEM1" in result.output

    def test_pmid_add_success(self, runner, mock_connector, monkeypatch):
        """Successful pmid add prints the item key."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.pubmed.resolve",
            lambda pmid: MOCK_PMID_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "pmid", "31452104"],
        )
        assert result.exit_code == 0, result.output
        assert "NEWITEM1" in result.output

    def test_isbn_add_success(self, runner, mock_connector, monkeypatch):
        """Successful isbn add prints the item key."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary.resolve",
            lambda isbn: MOCK_ISBN_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "isbn", "978-0-262-03384-8"],
        )
        assert result.exit_code == 0, result.output
        assert "NEWITEM1" in result.output


# ---------------------------------------------------------------------------
# Write gate tests
# ---------------------------------------------------------------------------


class TestWriteGate:
    def test_write_disabled_blocks_doi_add(self, runner, monkeypatch):
        """Without write enabled, doi add raises ClickException."""
        monkeypatch.delenv("PYZOT_ALLOW_WRITE", raising=False)
        monkeypatch.setattr("pyzot.config.get_write_enabled", lambda: False)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2"],
        )
        assert result.exit_code != 0
        assert "Write capability is disabled" in result.output

    def test_allow_write_flag_enables_doi_add(self, runner, mock_connector, monkeypatch):
        """--allow-write flag enables write commands."""
        monkeypatch.delenv("PYZOT_ALLOW_WRITE", raising=False)
        monkeypatch.setattr("pyzot.config.get_write_enabled", lambda: False)
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["--allow-write", "add", "doi", "10.1038/s41586-020-2649-2"],
        )
        assert result.exit_code == 0, result.output

    def test_env_var_enables_doi_add(self, runner, mock_connector, monkeypatch):
        """PYZOT_ALLOW_WRITE=1 enables write commands."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.config.get_write_enabled", lambda: False)
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2"],
        )
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# Zotero not running
# ---------------------------------------------------------------------------


class TestZoteroNotRunning:
    def test_connector_not_reachable_fails(self, runner, monkeypatch):
        """When Zotero is not running, add commands fail with actionable error."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        # Point to a port that's definitely not listening
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", "http://127.0.0.1:19998")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )

        result = runner.invoke(
            cli,
            ["add", "doi", "10.1038/s41586-020-2649-2"],
        )
        assert result.exit_code != 0
        assert (
            "Zotero" in result.output
            or "not reachable" in result.output.lower()
            or "not running" in result.output
        )


# ---------------------------------------------------------------------------
# Resolver error handling
# ---------------------------------------------------------------------------


class TestResolverErrors:
    def test_identifier_not_found_exits_nonzero(self, runner, monkeypatch):
        """When resolver raises IdentifierNotFound, CLI exits with error."""
        from pyzot.write.resolvers import IdentifierNotFound

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", "http://127.0.0.1:23119")
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr(
            "pyzot.write.dedup.find_by_doi",
            lambda db, doi: None,
        )

        def mock_resolve(doi):
            raise IdentifierNotFound("doi", doi, "Not found in test")

        # Monkeypatch the module-level resolve function
        import pyzot.write.resolvers.crossref as crossref_mod

        monkeypatch.setattr(crossref_mod, "resolve", mock_resolve)

        result = runner.invoke(
            cli,
            ["add", "doi", "10.9999/nonexistent", "--dry-run"],
        )
        assert result.exit_code != 0
        assert "Not found" in result.output or "not found" in result.output.lower()
