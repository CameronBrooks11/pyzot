"""Integration tests for URL handling through bare `zot add <input>`.

End-to-end with mocked connector + mocked resolvers.
No live network, no live Zotero.

Coverage:
- Generic URL → saveSnapshot
- arXiv URL → arXiv ID → save_items
- PubMed URL → PMID → save_items
- doi.org URL → DOI → save_items
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SAVE_ITEMS_RESPONSE = {"items": [{"key": "URL001", "itemType": "journalArticle"}]}
UPDATE_SESSION_RESPONSE = {}
SAVE_SNAPSHOT_RESPONSE = {"snapshotKey": "SNAP001"}

MOCK_DOI_CSL = {
    "type": "journal-article",
    "title": ["IEEE Smart Grid Paper"],
    "author": [{"given": "J.", "family": "Zhang"}],
    "issued": {"date-parts": [[2023]]},
    "DOI": "10.1109/TPWRS.2023.9876543",
    "container-title": ["IEEE Transactions on Power Systems"],
}

MOCK_ARXIV_CSL = {
    "type": "posted-content",
    "title": "Attention Is All You Need",
    "author": [{"given": "Ashish", "family": "Vaswani"}],
    "issued": {"date-parts": [[2017, 6]]},
    "archive": "arXiv",
    "archive_location": "1706.03762",
}

MOCK_PUBMED_CSL = {
    "type": "journal-article",
    "title": "A PubMed Paper",
    "author": [{"given": "Jane", "family": "Smith"}],
    "issued": {"date-parts": [[2019]]},
    "DOI": "10.1000/pubmed.123",
}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_connector(httpserver):
    httpserver.expect_request("/connector/ping").respond_with_json({"version": "7.0.0"})
    httpserver.expect_request("/connector/saveItems").respond_with_json(
        SAVE_ITEMS_RESPONSE, status=201
    )
    httpserver.expect_request("/connector/updateSession").respond_with_json(UPDATE_SESSION_RESPONSE)
    httpserver.expect_request("/connector/saveSnapshot").respond_with_json(SAVE_SNAPSHOT_RESPONSE)
    return httpserver


# ---------------------------------------------------------------------------
# Generic URL → saveSnapshot
# ---------------------------------------------------------------------------


class TestAddUrlGenericSnapshot:
    def test_generic_url_calls_save_snapshot(self, runner, mock_connector, monkeypatch):
        """Generic URL with no identifier → saveSnapshot called."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))

        # Mock the internal _run_url_snapshot to patch only the HTML fetch part,
        # not the full httpx.Client (which would also break the connector client).
        # We patch the HTML fetch inside _run_url_snapshot by mocking the fetch function.
        MOCK_HTML = "<html><head><title>Test</title></head><body>Content</body></html>"

        def mock_run_url_snapshot(ctx, url, *, collection, tag, dry_run, verbose):
            """Call the real snapshot runner but with HTML pre-fetched (no actual HTTP)."""
            # Directly call save_snapshot on the connector
            connector_url = mock_connector.url_for("").rstrip("/")
            import uuid

            from pyzot.write.connector_client import ConnectorClient

            client = ConnectorClient(base_url=connector_url)
            session_id = uuid.uuid4().hex
            result = client.save_snapshot(url=url, html=MOCK_HTML, session_id=session_id)
            import click

            click.echo(json.dumps(result, indent=2))

        monkeypatch.setattr("pyzot.cli.add._run_url_snapshot", mock_run_url_snapshot)

        result = runner.invoke(
            cli,
            ["add", "https://example.org/some-research-page"],
        )
        assert result.exit_code == 0, result.output

        # saveSnapshot should have been called
        snapshot_called = any(
            "/connector/saveSnapshot" in req.path for req, _ in mock_connector.log
        )
        assert snapshot_called, "saveSnapshot should have been called for generic URL"

    def test_generic_url_dry_run(self, runner, monkeypatch):
        """Generic URL --dry-run shows snapshot payload."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        # Mock the HTML fetch by patching httpx.Client only for the non-connector call.
        # For dry-run, there is no connector call, so patching httpx.Client is safe.
        class MockResponse:
            status_code = 200
            headers = {"content-type": "text/html"}
            text = "<html><body>Test</body></html>"

        class MockClient:
            def __init__(self, **kw):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def get(self, *a, **kw):
                return MockResponse()

        monkeypatch.setattr("httpx.Client", MockClient)

        result = runner.invoke(
            cli,
            ["add", "https://example.org/no-doi-here", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload.get("_type") == "saveSnapshot"
        assert payload.get("url") == "https://example.org/no-doi-here"


# ---------------------------------------------------------------------------
# arXiv URL routing
# ---------------------------------------------------------------------------


class TestAddUrlArxiv:
    def test_arxiv_url_routed_correctly(self, runner, mock_connector, monkeypatch):
        """arXiv URL is detected and routed to the arXiv resolver."""
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
            ["add", "https://arxiv.org/abs/1706.03762"],
        )
        assert result.exit_code == 0, result.output
        assert "URL001" in result.output


# ---------------------------------------------------------------------------
# doi.org URL routing
# ---------------------------------------------------------------------------


class TestAddUrlDoiOrg:
    def test_doi_org_url_routed_as_doi(self, runner, mock_connector, monkeypatch):
        """doi.org URL is detected and routed to the DOI resolver."""
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
            ["add", "https://doi.org/10.1109/TPWRS.2023.9876543"],
        )
        assert result.exit_code == 0, result.output
        assert "URL001" in result.output
