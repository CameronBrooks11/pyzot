"""Integration tests for M5: verbose HTTP tracing (``-v`` / ``--verbose``).

Covers:
- ``zot add <DOI> -v --dry-run`` produces resolver trace lines on stderr.
- With ``--dry-run``, no real HTTP request is made but the outgoing request
  description IS echoed (because the connector client doesn't make the call
  but the verbose flag is passed through).
- The ConnectorClient emits ``[http]`` lines when verbose=True and a real
  request is made (tested against a mock httpserver).
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

MOCK_DOI_CSL = {
    "type": "journal-article",
    "title": ["NumPy"],
    "author": [{"given": "C.", "family": "Harris"}],
    "issued": {"date-parts": [[2020]]},
    "DOI": "10.1038/s41586-020-2649-2",
    "container-title": ["Nature"],
}

SAVE_ITEMS_RESPONSE = {"items": [{"key": "TESTKEY1", "itemType": "journalArticle"}]}


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def runner_mixed():
    # click >= 8.2 always separates stdout/stderr; consumers must inspect
    # result.stderr for stderr-bound output.
    return CliRunner()


# ---------------------------------------------------------------------------
# Verbose dry-run: resolver verbose output
# ---------------------------------------------------------------------------


class TestVerboseDryRun:
    def test_verbose_dry_run_prints_resolver_trace(self, runner_mixed, monkeypatch):
        """``-v --dry-run`` prints resolver trace lines (not [http] since no request made)."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner_mixed.invoke(cli, ["add", "10.1038/s41586-020-2649-2", "-v", "--dry-run"])
        assert result.exit_code == 0, result.output
        # --dry-run means no connector call; but verbose should print at least
        # the resolution trace ("Resolving doi:..." or "Resolved: ...") to stderr.
        combined = result.output + (result.stderr or "")
        assert "Resolving doi:" in combined or "Resolved" in combined

    def test_non_verbose_dry_run_is_clean(self, runner_mixed, monkeypatch):
        """Without ``-v``, dry-run output is clean JSON only."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner_mixed.invoke(cli, ["add", "10.1038/s41586-020-2649-2", "--dry-run"])
        assert result.exit_code == 0, result.output
        # Output should be valid JSON and nothing else
        payload = json.loads(result.output)
        assert "items" in payload


# ---------------------------------------------------------------------------
# Verbose with live connector: [http] lines emitted
# ---------------------------------------------------------------------------


class TestVerboseConnector:
    def test_verbose_emits_http_trace(self, runner_mixed, monkeypatch, httpserver):
        """``-v`` causes ``[http]`` trace lines to appear in stderr for each connector call."""
        httpserver.expect_request("/connector/ping").respond_with_json({"version": "7.0.0"})
        httpserver.expect_request("/connector/saveItems").respond_with_json(
            SAVE_ITEMS_RESPONSE, status=201
        )
        httpserver.expect_request("/connector/updateSession").respond_with_json({})

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", httpserver.url_for("").rstrip("/"))
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)

        result = runner_mixed.invoke(cli, ["add", "10.1038/s41586-020-2649-2", "-v"])
        assert result.exit_code == 0, result.output
        # At least one [http] trace line should be present (stderr in click 8.2+)
        combined = result.output + (result.stderr or "")
        assert "[http]" in combined

    def test_verbose_http_line_contains_url(self, runner_mixed, monkeypatch, httpserver):
        """``[http]`` trace includes the request URL."""
        httpserver.expect_request("/connector/ping").respond_with_json({"version": "7.0.0"})
        httpserver.expect_request("/connector/saveItems").respond_with_json(
            SAVE_ITEMS_RESPONSE, status=201
        )
        httpserver.expect_request("/connector/updateSession").respond_with_json({})

        connector_url = httpserver.url_for("").rstrip("/")
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", connector_url)
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)

        result = runner_mixed.invoke(cli, ["add", "10.1038/s41586-020-2649-2", "-v"])
        assert result.exit_code == 0, result.output
        # The [http] line should mention the connector endpoint
        combined = result.output + (result.stderr or "")
        http_lines = [line for line in combined.splitlines() if "[http]" in line]
        assert any(connector_url in line or "connector" in line.lower() for line in http_lines), (
            f"No [http] line with connector URL found.\nLines: {http_lines}"
        )


# ---------------------------------------------------------------------------
# ConnectorClient._trace unit-level test
# ---------------------------------------------------------------------------


class TestConnectorClientTrace:
    def test_trace_writes_to_logger_when_not_verbose(self):
        """_trace always calls logger.debug() even when verbose=False."""
        import logging

        from pyzot.write.connector_client import ConnectorClient

        captured: list[str] = []

        class CapturingHandler(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        conn_logger = logging.getLogger("pyzot.connector")
        handler = CapturingHandler()
        handler.setLevel(logging.DEBUG)
        conn_logger.addHandler(handler)
        conn_logger.setLevel(logging.DEBUG)

        try:
            client = ConnectorClient(verbose=False)
            client._trace("test message from unit test")
            assert any("test message from unit test" in msg for msg in captured)
        finally:
            conn_logger.removeHandler(handler)

    def test_trace_calls_click_echo_when_verbose(self, capsys):
        """_trace calls click.echo(err=True) when verbose=True."""
        from pyzot.write.connector_client import ConnectorClient

        # Directly test the _trace method
        client = ConnectorClient(verbose=True)

        import click as _click

        recorded: list[str] = []

        original_echo = _click.echo

        def patched_echo(msg=None, **kwargs):
            if kwargs.get("err") and msg and "[http]" in str(msg):
                recorded.append(str(msg))
            else:
                original_echo(msg, **kwargs)

        _click.echo = patched_echo
        try:
            client._trace("verbose trace test")
        finally:
            _click.echo = original_echo

        assert any("verbose trace test" in m for m in recorded)
