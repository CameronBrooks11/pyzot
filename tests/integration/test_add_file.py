"""Integration tests for file handling through bare `zot add <input>`.

Uses pytest-httpserver to mock /connector/* endpoints.
No real Zotero process or network required.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from pyzot.cli.main import cli

FIXTURES = Path(__file__).parent.parent / "fixtures"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _runner():
    return CliRunner()


def _env(connector_url: str) -> dict:
    """Env vars that enable write + point to mock connector."""
    return {
        "PYZOT_ALLOW_WRITE": "1",
        "PYZOT_CONNECTOR_URL": connector_url,
    }


# ---------------------------------------------------------------------------
# /connector/ping mock helper
# ---------------------------------------------------------------------------


def _register_ping(httpserver):
    httpserver.expect_request("/connector/ping").respond_with_json(
        {"version": "7.0.0", "prefs": {}}
    )


# ---------------------------------------------------------------------------
# Test: --dry-run prints metadata, sends no HTTP request
# ---------------------------------------------------------------------------


def test_add_file_dry_run(tmp_path: Path):
    """--dry-run prints metadata without hitting the connector."""
    pdf = FIXTURES / "sample.pdf"
    result = _runner().invoke(
        cli,
        ["add", str(pdf), "--dry-run"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "Dry-run" in result.output
    assert "application/pdf" in result.output
    assert "sample.pdf" in result.output or "sample" in result.output
    assert "X-Metadata" in result.output


def test_add_file_dry_run_epub(tmp_path: Path):
    """--dry-run works for EPUB files."""
    epub = FIXTURES / "sample.epub"
    result = _runner().invoke(
        cli,
        ["add", str(epub), "--dry-run"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "application/epub+zip" in result.output


def test_add_file_dry_run_shows_collection_and_tags(tmp_path: Path):
    """--dry-run includes collection and tags in output."""
    pdf = FIXTURES / "sample.pdf"
    result = _runner().invoke(
        cli,
        ["add", str(pdf), "--dry-run", "--collection", "Inbox", "--tag", "ml"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "Inbox" in result.output
    assert "ml" in result.output


# ---------------------------------------------------------------------------
# Test: bare path dispatch routes non-PDF/EPUB files to import
# ---------------------------------------------------------------------------


def test_add_file_path_routes_bib_to_import(tmp_path: Path):
    """Bare .bib paths route to the import path after file/import collapse."""
    bib = FIXTURES / "sample.bib"
    result = _runner().invoke(
        cli,
        ["add", str(bib), "--dry-run"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "application/x-bibtex" in result.output


def test_add_file_path_routes_ris_to_import(tmp_path: Path):
    """Bare .ris paths route to the import path after file/import collapse."""
    ris = FIXTURES / "sample.ris"
    result = _runner().invoke(
        cli,
        ["add", str(ris), "--dry-run"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "application/x-research-info-systems" in result.output


def test_add_file_path_routes_unknown_type_to_import(tmp_path: Path):
    """Unknown absolute paths still route to the import path."""
    f = tmp_path / "data.bin"
    f.write_bytes(b"\x00\x01\x02\x03")
    result = _runner().invoke(
        cli,
        ["add", str(f), "--dry-run"],
        env={"PYZOT_ALLOW_WRITE": "1"},
        catch_exceptions=False,
    )
    assert result.exit_code == 0, result.output
    assert "Content-Type : text/plain" in result.output


# ---------------------------------------------------------------------------
# Test: write gate
# ---------------------------------------------------------------------------


def test_add_file_requires_write_enabled(tmp_path: Path):
    """Without write enabled, command fails immediately."""
    pdf = FIXTURES / "sample.pdf"
    result = _runner().invoke(
        cli,
        ["add", str(pdf), "--dry-run"],
        env={},
        catch_exceptions=False,
    )
    assert result.exit_code != 0
    # Should mention write.enabled or --allow-write
    assert "write" in result.output.lower() or "write" in (result.output or "").lower()


# ---------------------------------------------------------------------------
# Test: live upload — canRecognize=false
# ---------------------------------------------------------------------------


def test_add_file_upload_can_recognize_false(httpserver, tmp_path: Path):
    """Uploads the file bytes; with canRecognize=false, prints attachment key."""
    pdf = FIXTURES / "sample.pdf"
    pdf_bytes = pdf.read_bytes()

    _register_ping(httpserver)

    # Capture the actual uploaded bytes for assertion
    received = {}

    def _handle_attachment(request):
        received["body"] = request.data
        received["content_type"] = request.headers.get("Content-Type")
        received["x_metadata"] = request.headers.get("X-Metadata")
        received["content_length"] = request.headers.get("Content-Length")
        from werkzeug.wrappers import Response

        return Response(
            json.dumps({"canRecognize": False, "key": "ATTCH001"}),
            status=201,
            content_type="application/json",
        )

    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_handler(_handle_attachment)

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", str(pdf), "--wait-recognize", "0"],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output

    # Verify correct bytes were uploaded
    assert received.get("body") == pdf_bytes
    # Verify Content-Type
    assert received.get("content_type") == "application/pdf"
    # Verify Content-Length
    assert received.get("content_length") == str(len(pdf_bytes))
    # Verify X-Metadata contains sessionID and title
    meta = json.loads(received.get("x_metadata", "{}"))
    assert "sessionID" in meta
    assert "title" in meta
    assert "url" in meta
    assert meta["url"].startswith("file://")


def test_add_file_upload_epub(httpserver, tmp_path: Path):
    """EPUB files are uploaded with correct content-type."""
    epub = FIXTURES / "sample.epub"

    received = {}

    def _handle_attachment(request):
        received["content_type"] = request.headers.get("Content-Type")
        from werkzeug.wrappers import Response

        return Response(
            json.dumps({"canRecognize": False}),
            status=201,
            content_type="application/json",
        )

    _register_ping(httpserver)
    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_handler(_handle_attachment)

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", str(epub), "--wait-recognize", "0"],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    assert received.get("content_type") == "application/epub+zip"


# ---------------------------------------------------------------------------
# Test: live upload — canRecognize=true, parent found via monkeypatched poll
# ---------------------------------------------------------------------------


def test_add_file_can_recognize_true_parent_found(httpserver, tmp_path: Path):
    """With canRecognize=true, polls DB and prints parent key when found."""
    pdf = FIXTURES / "sample.pdf"

    _register_ping(httpserver)
    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_json({"canRecognize": True, "key": "ATTCH002"}, status=201)

    connector_url = httpserver.url_for("").rstrip("/")

    from pyzot.write.dedup import ItemRef as _ItemRef

    stub_parent = _ItemRef(key="PARENT01", title="The Recognised Paper", item_id=99)

    with (
        patch("pyzot.write.recognize.wait_for_recognized_parent", return_value=stub_parent),
        patch("pyzot.config.get_db_path", return_value=tmp_path / "zotero.sqlite"),
    ):
        result = _runner().invoke(
            cli,
            ["add", str(pdf), "--wait-recognize", "5"],
            env=_env(connector_url),
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    assert "PARENT01" in result.output
    assert "The Recognised Paper" in result.output


def test_add_file_can_recognize_true_timeout(httpserver, tmp_path: Path):
    """With canRecognize=true but polling times out, prints fallback message."""
    pdf = FIXTURES / "sample.pdf"

    _register_ping(httpserver)
    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_json({"canRecognize": True, "key": "ATTCH003"}, status=201)

    connector_url = httpserver.url_for("").rstrip("/")

    with patch("pyzot.write.recognize.wait_for_recognized_parent", return_value=None):
        result = _runner().invoke(
            cli,
            ["add", str(pdf), "--wait-recognize", "5"],
            env=_env(connector_url),
            catch_exceptions=False,
        )

    assert result.exit_code == 0, result.output
    # Should mention timeout and the attachment key
    out_lower = result.output.lower()
    assert "no parent" in out_lower or "recognised" in out_lower or "recognized" in out_lower


# ---------------------------------------------------------------------------
# Test: updateSession called when --tag is used
# ---------------------------------------------------------------------------


def test_add_file_calls_update_session_with_tags(httpserver, tmp_path: Path):
    """When --tag is used, updateSession is called with the tags."""
    pdf = FIXTURES / "sample.pdf"

    _register_ping(httpserver)
    httpserver.expect_request(
        "/connector/saveStandaloneAttachment", method="POST"
    ).respond_with_json({"canRecognize": False, "key": "ATTCH004"}, status=201)

    received_update = {}

    def _handle_update(request):
        received_update["body"] = request.json
        from werkzeug.wrappers import Response

        return Response("{}", status=200, content_type="application/json")

    httpserver.expect_request("/connector/updateSession", method="POST").respond_with_handler(
        _handle_update
    )

    connector_url = httpserver.url_for("").rstrip("/")
    result = _runner().invoke(
        cli,
        ["add", str(pdf), "--wait-recognize", "0", "--tag", "ml", "--tag", "pdf"],
        env=_env(connector_url),
        catch_exceptions=False,
    )

    assert result.exit_code == 0, result.output
    # updateSession should have been called with the tags
    body = received_update.get("body", {})
    assert body is not None
    tags = body.get("tags", [])
    tag_names = [t.get("tag") for t in tags]
    assert "ml" in tag_names
    assert "pdf" in tag_names
