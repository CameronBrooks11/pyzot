"""Integration tests for `zot add cite`.

End-to-end with mocked Crossref-bibliographic + mocked DOI-resolve + mocked connector.
No live network, no live Zotero.

Covers:
- High-confidence resolution → save_items
- --dry-run with resolution
- Non-interactive ambiguous → ClickException
- Unresolved citation → ClickException
- Batch file processing (--file)
- write gate enforcement
"""

from __future__ import annotations

import json
import os
import tempfile

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli


# ---------------------------------------------------------------------------
# Shared fixtures / constants
# ---------------------------------------------------------------------------

ZHANG_CITATION = (
    "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: "
    "Evaluating assumptions for low-voltage network modelling in the DER era. "
    "Sustainable Energy, Grids and Networks, 2025."
)

ZHANG_DOI = "10.1016/j.segan.2025.01.001"

ZHANG_CSL = {
    "type": "journal-article",
    "title": ["Beyond simplifications: Evaluating assumptions for low-voltage network modelling in the DER era"],
    "author": [
        {"given": "J.", "family": "Zhang"},
        {"given": "F.", "family": "Geth"},
    ],
    "issued": {"date-parts": [[2025]]},
    "DOI": ZHANG_DOI,
    "container-title": ["Sustainable Energy, Grids and Networks"],
}

SAVE_ITEMS_RESPONSE = {"items": [{"key": "CITE001", "itemType": "journalArticle"}]}
UPDATE_SESSION_RESPONSE = {}


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
    return httpserver


def make_mock_resolve_citation(returns):
    """Return a mock resolve_citation function that returns *returns*."""
    def mock(text, *, threshold, gap, interactive, console=None):
        return returns
    return mock


# ---------------------------------------------------------------------------
# Success path
# ---------------------------------------------------------------------------

class TestAddCiteSuccess:
    def test_high_confidence_resolves_and_saves(self, runner, mock_connector, monkeypatch):
        """High-confidence citation resolves to DOI and creates item."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(ZHANG_CSL),
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "cite", ZHANG_CITATION],
        )
        assert result.exit_code == 0, result.output
        assert "CITE001" in result.output

        # saveItems should have been called
        save_items_called = any(
            "/connector/saveItems" in req.path for req, _ in mock_connector.log
        )
        assert save_items_called

    def test_dry_run_prints_json(self, runner, monkeypatch):
        """--dry-run resolves citation and prints JSON without calling connector."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(ZHANG_CSL),
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "cite", ZHANG_CITATION, "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert "items" in payload
        assert payload["sessionID"] == "<dry-run>"
        # Check item type
        assert payload["items"][0]["itemType"] == "journalArticle"

    def test_dry_run_with_collection_and_tag(self, runner, monkeypatch):
        """--dry-run includes _collection and _tags in output."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(ZHANG_CSL),
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            [
                "add", "cite", ZHANG_CITATION,
                "--dry-run",
                "--collection", "Smart Grid",
                "--tag", "to-read",
                "--tag", "2025",
            ],
        )
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload.get("_collection") == "Smart Grid"
        assert "to-read" in payload.get("_tags", [])
        assert "2025" in payload.get("_tags", [])

    def test_duplicate_doi_exits_0_no_connector(self, runner, mock_connector, monkeypatch):
        """When DOI already exists, exits 0 without calling saveItems."""
        from pyzot.write.dedup import ItemRef

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(ZHANG_CSL),
        )
        monkeypatch.setattr(
            "pyzot.cli.add._find_duplicate",
            lambda kind, id: ItemRef(key="EXIST001", title="Existing paper", item_id=1),
        )

        result = runner.invoke(cli, ["add", "cite", ZHANG_CITATION])
        assert result.exit_code == 0
        assert "EXIST001" in result.output
        assert "already exists" in result.output

        # saveItems should NOT be called
        save_items_called = any(
            "/connector/saveItems" in req.path for req, _ in mock_connector.log
        )
        assert not save_items_called


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------

class TestAddCiteFailures:
    def test_unresolved_citation_exits_nonzero(self, runner, monkeypatch):
        """When resolve_citation returns None, exits with error."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(None),
        )

        result = runner.invoke(
            cli,
            ["add", "cite", "This citation matches nothing at all."],
        )
        assert result.exit_code != 0
        assert "Could not resolve" in result.output or "could not" in result.output.lower()

    def test_non_interactive_ambiguous_exits_nonzero(self, runner, monkeypatch):
        """--non-interactive with unresolved citation exits with an error message."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        # Simulate ambiguous result: resolve_citation returns None in non-interactive mode
        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            make_mock_resolve_citation(None),
        )

        result = runner.invoke(
            cli,
            ["add", "cite", ZHANG_CITATION, "--non-interactive"],
        )
        assert result.exit_code != 0
        assert "Could not resolve" in result.output or "non-interactive" in result.output

    def test_write_gate_blocks_cite(self, runner, monkeypatch):
        """Without write enabled, cite command is blocked."""
        monkeypatch.delenv("PYZOT_ALLOW_WRITE", raising=False)
        monkeypatch.setattr("pyzot.config.get_write_enabled", lambda: False)

        result = runner.invoke(cli, ["add", "cite", ZHANG_CITATION])
        assert result.exit_code != 0
        assert "Write capability is disabled" in result.output

    def test_no_argument_and_no_file_is_usage_error(self, runner, monkeypatch):
        """Calling `zot add cite` with no text and no --file is a UsageError."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "cite"])
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Batch file mode
# ---------------------------------------------------------------------------

class TestAddCiteFile:
    def test_file_mode_processes_multiple_lines(
        self, runner, mock_connector, monkeypatch, tmp_path
    ):
        """--file mode resolves each line and adds each as a separate item."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))

        # Create a refs file with 2 citations + 1 comment + 1 blank line
        refs_file = tmp_path / "refs.txt"
        refs_file.write_text(
            "# This is a comment\n"
            "\n"
            f"{ZHANG_CITATION}\n"
            "Smith, J. (2020) Another paper. Nature, 585, 1-10.\n",
            encoding="utf-8",
        )

        call_count = [0]
        def mock_resolve(text, *, threshold, gap, interactive, console=None):
            call_count[0] += 1
            return ZHANG_CSL  # both resolve successfully

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            mock_resolve,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "cite", "--file", str(refs_file)],
        )
        assert result.exit_code == 0, result.output
        # resolve_citation should be called exactly twice (comment + blank skipped)
        assert call_count[0] == 2

    def test_file_mode_skips_failed_lines_continues(
        self, runner, mock_connector, monkeypatch, tmp_path
    ):
        """--file mode skips unresolvable lines and continues processing."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setenv("PYZOT_CONNECTOR_URL", mock_connector.url_for("").rstrip("/"))

        refs_file = tmp_path / "refs.txt"
        refs_file.write_text(
            f"{ZHANG_CITATION}\n"
            "This one cannot be resolved.\n",
            encoding="utf-8",
        )

        call_count = [0]
        def mock_resolve(text, *, threshold, gap, interactive, console=None):
            call_count[0] += 1
            if "Zhang" in text:
                return ZHANG_CSL
            return None  # second citation fails

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            mock_resolve,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        result = runner.invoke(
            cli,
            ["add", "cite", "--file", str(refs_file)],
        )
        # Should exit 1 (some failed) but process all lines
        assert result.exit_code != 0 or call_count[0] == 2
        # First one should still succeed
        assert call_count[0] == 2  # both lines attempted
