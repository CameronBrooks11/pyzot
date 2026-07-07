"""Integration tests for `zot add import`.

Uses pytest-httpserver to mock /connector/* endpoints.
No real Zotero process or network required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from zotcli.cli.main import cli

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner():
    return CliRunner()


def _env(connector_url: str) -> dict:
    return {
        "ZOTCLI_ALLOW_WRITE": "1",
        "ZOTCLI_CONNECTOR_URL": connector_url,
    }


def _register_ping(httpserver):
    httpserver.expect_request("/connector/ping").respond_with_json(
        {"version": "7.0.0", "prefs": {}}
    )


IMPORT_RESPONSE = [
    {"key": "BIBKEY01", "itemType": "journalArticle", "title": "Array programming with NumPy"}
]


# ---------------------------------------------------------------------------
# Test: --dry-run
# ---------------------------------------------------------------------------

def test_import_dry_run_bib():
    """--dry-run prints content-type and preview without hitting the connector."""
    bib = FIXTURES / "sample.bib"
    result = _runner().invoke(
        cli,
        ["add", "import", str(bib), "--dry-run"],
        env={"ZOTCLI_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "application/x-bibtex" in result.output
    assert "Preview" in result.output


def test_import_dry_run_ris():
    """--dry-run for RIS file shows RIS content-type."""
    ris = FIXTURES / "sample.ris"
    result = _runner().invoke(
        cli,
        ["add", "import", str(ris), "--dry-run"],
        env={"ZOTCLI_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "application/x-research-info-systems" in result.output


# ---------------------------------------------------------------------------
# Test: write gate
# ---------------------------------------------------------------------------

def test_import_requires_write_enabled():
    """Without write enabled, import command fails with actionable message."""
    bib = FIXTURES / "sample.bib"
    result = _runner().invoke(
        cli,
        ["add", "import", str(bib), "--dry-run"],
        env={},
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    assert "write" in result.output.lower()


# ---------------------------------------------------------------------------
# Test: BibTeX import — body bytes and content-type
# ---------------------------------------------------------------------------

def test_import_bib_posts_correct_body_and_content_type(httpserver):
    """BibTeX file is posted verbatim with correct content-type."""
    bib = FIXTURES / "sample.bib"
    bib_bytes = bib.read_bytes()

    received = {}

    def _handle_import(request):
        received["body"] = request.data
        received["content_type"] = request.headers.get("Content-Type")
        from werkzeug.wrappers import Response
        return Response(
            json.dumps(IMPORT_RESPONSE),
            status=201,
            content_type="application/json",
        )

    _register_ping(httpserver)
    httpserver.expect_request("/connector/import", method="POST").respond_with_handler(
        _handle_import
    )

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", "import", str(bib)],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert received["body"] == bib_bytes
    assert received["content_type"] == "application/x-bibtex"
    assert "BIBKEY01" in result.output


# ---------------------------------------------------------------------------
# Test: RIS import
# ---------------------------------------------------------------------------

def test_import_ris_posts_correct_content_type(httpserver):
    """RIS file is posted with application/x-research-info-systems."""
    ris = FIXTURES / "sample.ris"
    ris_bytes = ris.read_bytes()

    received = {}

    def _handle_import(request):
        received["body"] = request.data
        received["content_type"] = request.headers.get("Content-Type")
        from werkzeug.wrappers import Response
        return Response(
            json.dumps(IMPORT_RESPONSE),
            status=201,
            content_type="application/json",
        )

    _register_ping(httpserver)
    httpserver.expect_request("/connector/import", method="POST").respond_with_handler(
        _handle_import
    )

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", "import", str(ris)],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert received["body"] == ris_bytes
    assert received["content_type"] == "application/x-research-info-systems"


# ---------------------------------------------------------------------------
# Test: CSL-JSON import
# ---------------------------------------------------------------------------

def test_import_json_posts_correct_content_type(httpserver, tmp_path: Path):
    """JSON file (CSL-JSON) is posted with the correct content-type."""
    csl_data = [{"type": "article-journal", "title": "Test", "DOI": "10.1000/xyz"}]
    json_file = tmp_path / "refs.json"
    json_file.write_bytes(json.dumps(csl_data).encode())

    received = {}

    def _handle_import(request):
        received["content_type"] = request.headers.get("Content-Type")
        from werkzeug.wrappers import Response
        return Response(
            json.dumps([{"key": "JSONKEY1"}]),
            status=201,
            content_type="application/json",
        )

    _register_ping(httpserver)
    httpserver.expect_request("/connector/import", method="POST").respond_with_handler(
        _handle_import
    )

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", "import", str(json_file)],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert received["content_type"] == "application/vnd.citationstyles.csl+json"
    assert "JSONKEY1" in result.output


# ---------------------------------------------------------------------------
# Test: updateSession is called when --tag is used
# ---------------------------------------------------------------------------

def test_import_calls_update_session_with_tags(httpserver):
    """When --tag is passed, updateSession is called with the tags."""
    bib = FIXTURES / "sample.bib"

    _register_ping(httpserver)
    httpserver.expect_request("/connector/import", method="POST").respond_with_json(
        IMPORT_RESPONSE, status=201
    )

    received_update = {}

    def _handle_update(request):
        received_update["body"] = request.json
        from werkzeug.wrappers import Response
        return Response("{}", status=200, content_type="application/json")

    httpserver.expect_request(
        "/connector/updateSession", method="POST"
    ).respond_with_handler(_handle_update)

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", "import", str(bib), "--tag", "imported", "--tag", "2026"],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    body = received_update.get("body", {})
    tags = body.get("tags", [])
    tag_names = [t.get("tag") for t in tags]
    assert "imported" in tag_names
    assert "2026" in tag_names


# ---------------------------------------------------------------------------
# Test: multiple items imported — count reported
# ---------------------------------------------------------------------------

def test_import_multiple_items(httpserver):
    """Multiple imported items are all reported."""
    bib = FIXTURES / "sample.bib"

    multi_response = [
        {"key": "ITEM0001", "itemType": "journalArticle"},
        {"key": "ITEM0002", "itemType": "book"},
    ]

    _register_ping(httpserver)
    httpserver.expect_request("/connector/import", method="POST").respond_with_json(
        multi_response, status=201
    )

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", "import", str(bib)],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert "ITEM0001" in result.output
    assert "ITEM0002" in result.output
    assert "2" in result.output  # "Imported 2 item(s)"


# ---------------------------------------------------------------------------
# Test: connector_import method directly
# ---------------------------------------------------------------------------

def test_connector_import_method_posts_bytes(httpserver):
    """ConnectorClient.connector_import posts raw bytes with correct content-type."""
    from zotcli.write.connector_client import ConnectorClient

    received = {}

    def _handle(request):
        received["body"] = request.data
        received["content_type"] = request.headers.get("Content-Type")
        from werkzeug.wrappers import Response
        return Response(
            json.dumps([{"key": "TEST001"}]),
            status=201,
            content_type="application/json",
        )

    httpserver.expect_request("/connector/import", method="POST").respond_with_handler(_handle)

    client = ConnectorClient(base_url=httpserver.url_for("").rstrip("/"))
    body = b"@article{test, title={Test}}"
    result = client.connector_import(body=body, content_type="application/x-bibtex")

    assert received["body"] == body
    assert received["content_type"] == "application/x-bibtex"
    # Result is a list (parsed JSON)
    assert isinstance(result, list)
    assert result[0]["key"] == "TEST001"


def test_connector_import_with_session_id(httpserver):
    """connector_import appends ?session=<id> when session_id is provided."""
    from zotcli.write.connector_client import ConnectorClient

    received = {}

    def _handle(request):
        received["query"] = request.query_string.decode()
        from werkzeug.wrappers import Response
        return Response(
            json.dumps([]),
            status=201,
            content_type="application/json",
        )

    # Match any request to /connector/import (with or without query string)
    httpserver.expect_request("/connector/import", method="POST").respond_with_handler(_handle)

    client = ConnectorClient(base_url=httpserver.url_for("").rstrip("/"))
    client.connector_import(body=b"data", content_type="text/plain", session_id="abc123")

    assert "session=abc123" in received.get("query", "")


# ---------------------------------------------------------------------------
# Test: save_standalone_attachment method directly
# ---------------------------------------------------------------------------

def test_save_standalone_attachment_posts_file_bytes(httpserver, tmp_path: Path):
    """ConnectorClient.save_standalone_attachment posts file bytes with correct headers."""
    from zotcli.write.connector_client import ConnectorClient

    pdf = FIXTURES / "sample.pdf"
    pdf_bytes = pdf.read_bytes()

    received = {}

    def _handle(request):
        received["body"] = request.data
        received["content_type"] = request.headers.get("Content-Type")
        received["x_metadata"] = request.headers.get("X-Metadata")
        received["content_length"] = request.headers.get("Content-Length")
        from werkzeug.wrappers import Response
        return Response(
            json.dumps({"canRecognize": True}),
            status=201,
            content_type="application/json",
        )

    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_handler(_handle)

    client = ConnectorClient(base_url=httpserver.url_for("").rstrip("/"))
    result = client.save_standalone_attachment(
        file_path=pdf,
        content_type="application/pdf",
        session_id="test-session-id",
        title="Sample Paper",
        source_url="https://example.com/paper.pdf",
    )

    assert received["body"] == pdf_bytes
    assert received["content_type"] == "application/pdf"
    assert received["content_length"] == str(len(pdf_bytes))

    meta = json.loads(received["x_metadata"])
    assert meta["sessionID"] == "test-session-id"
    assert meta["title"] == "Sample Paper"
    assert meta["url"] == "https://example.com/paper.pdf"

    assert result["canRecognize"] is True
