"""Integration tests for --with-pdf flag.

End-to-end with mocked connector + mocked Unpaywall.

Test cases:
1. [unpaywall].enabled=true + Unpaywall hit → save_attachment called once with PDF bytes.
2. --non-interactive + [unpaywall].enabled=false → save_attachment NOT called, exit 0.
3. First-time prompt with 'Y' answer → unpaywall login flow runs (mock email prompt) → PDF fetch.
4. First-time prompt with 'N' answer → skips PDF, exits 0.
5. First-time prompt with 'q' answer → aborts (exit != 0).
"""

from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from click.testing import CliRunner


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    """Redirect ZOTCLI_HOME to tmp_path and enable write mode."""
    monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))
    monkeypatch.setenv("ZOTCLI_ALLOW_WRITE", "1")
    yield tmp_path


def _make_csl_response():
    """A minimal CSL-JSON Crossref response."""
    return {
        "status": "ok",
        "message": {
            "DOI": "10.1038/s41586-020-2649-2",
            "title": ["Test Paper"],
            "author": [{"family": "Smith", "given": "John"}],
            "issued": {"date-parts": [[2024]]},
            "container-title": ["Nature"],
            "volume": "583",
            "issue": "7818",
            "page": "357-362",
            "type": "journal-article",
        },
    }


def _make_save_items_response():
    """Fake connector saveItems response."""
    return {"items": [{"key": "ABCD1234", "itemType": "journalArticle"}]}


@pytest.mark.skip(
    reason="Test targets the pre-0.3.0 Unpaywall-direct path. The new "
    "find_file pipeline uses Zotero's OA endpoint and does not call "
    "find_oa_pdf_url. New unit tests in tests/unit/test_find_file.py cover "
    "the replacement behaviour."
)
class TestWithPdfUnpaywallHit:
    """Unpaywall enabled + OA PDF found → save_attachment called once."""

    def test_unpaywall_hit_attaches_pdf(self, tmp_path, monkeypatch):
        """Full happy path: Unpaywall returns a PDF URL, it's downloaded and attached."""
        # Configure Unpaywall
        from zotcli.write import credentials as creds
        from zotcli.config import set_config_value

        creds.set("unpaywall", "email", "test@example.com")
        set_config_value("unpaywall.enabled", "true")

        # Fake PDF bytes (minimal valid PDF magic)
        fake_pdf = b"%PDF-1.4 fake content"

        save_attachment_calls = []

        def mock_save_attachment(**kwargs):
            save_attachment_calls.append(kwargs)
            return {"status_code": 201}

        with (
            patch("zotcli.write.connector_client.ConnectorClient.ping",
                  return_value={"zotero": "5.0"}),
            patch("zotcli.write.connector_client.ConnectorClient.get_selected_collection",
                  return_value={"name": "My Library"}),
            patch("zotcli.write.connector_client.ConnectorClient.save_items",
                  return_value=_make_save_items_response()),
            patch("zotcli.write.connector_client.ConnectorClient.update_session",
                  return_value={}),
            patch("zotcli.write.connector_client.ConnectorClient.save_attachment",
                  side_effect=mock_save_attachment),
            patch("zotcli.write.resolvers.crossref.resolve",
                  return_value={
                      "DOI": "10.1038/s41586-020-2649-2",
                      "title": "Test Paper",
                      "author": [{"family": "Smith", "given": "John"}],
                      "issued": {"date-parts": [[2024]]},
                      "container-title": ["Nature"],
                      "type": "journal-article",
                  }),
            patch("zotcli.write.resolvers.unpaywall.find_oa_pdf_url",
                  return_value="https://example.com/paper.pdf"),
            patch("httpx.Client") as mock_client_cls,
        ):
            # Mock httpx for the PDF download
            mock_http_ctx = MagicMock()
            mock_http_ctx.__enter__ = MagicMock(return_value=mock_http_ctx)
            mock_http_ctx.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = fake_pdf
            mock_http_ctx.get.return_value = mock_resp
            mock_client_cls.return_value = mock_http_ctx

            from zotcli.cli.main import cli
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["add", "doi", "10.1038/s41586-020-2649-2", "--with-pdf"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, f"Output: {result.output}"
        assert len(save_attachment_calls) == 1
        call = save_attachment_calls[0]
        assert call["parent_item_id"] == "ABCD1234"
        assert call["session_id"] is not None
        # Check the output mentions the attachment
        assert "Attached OA PDF" in result.output


class TestWithPdfNonInteractiveSkip:
    """--non-interactive + [unpaywall].enabled=false → skips PDF, exits 0."""

    def test_non_interactive_skips_pdf_gracefully(self, tmp_path, monkeypatch):
        """With --non-interactive and Unpaywall not configured, PDF is skipped silently."""
        save_attachment_calls = []

        with (
            patch("zotcli.write.connector_client.ConnectorClient.ping",
                  return_value={"zotero": "5.0"}),
            patch("zotcli.write.connector_client.ConnectorClient.get_selected_collection",
                  return_value={"name": "My Library"}),
            patch("zotcli.write.connector_client.ConnectorClient.save_items",
                  return_value=_make_save_items_response()),
            patch("zotcli.write.connector_client.ConnectorClient.update_session",
                  return_value={}),
            patch("zotcli.write.connector_client.ConnectorClient.save_attachment",
                  side_effect=lambda **kw: save_attachment_calls.append(kw) or {}),
            patch("zotcli.write.resolvers.crossref.resolve",
                  return_value={
                      "DOI": "10.1038/test",
                      "title": "Test Paper",
                      "author": [],
                      "type": "journal-article",
                  }),
        ):
            from zotcli.cli.main import cli
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["add", "doi", "10.1038/test", "--with-pdf", "--non-interactive"],
                catch_exceptions=False,
            )

        assert result.exit_code == 0, f"Output: {result.output}"
        assert len(save_attachment_calls) == 0  # No PDF attached
        # No interactive prompt was shown
        assert "Press Y" not in result.output


@pytest.mark.skip(
    reason="The first-time Unpaywall prompt is no longer part of the "
    "--with-pdf flow as of 0.3.0. The find_file pipeline uses Zotero's OA "
    "mirror which does not require an Unpaywall email."
)
class TestWithPdfFirstTimePromptY:
    """First-time prompt: user presses Y → Unpaywall configured → PDF fetch attempted."""

    def test_prompt_y_configures_unpaywall(self, tmp_path, monkeypatch):
        """When user presses Y at the Unpaywall prompt, email is requested and PDF is fetched."""
        fake_pdf = b"%PDF-1.4 test"

        save_attachment_calls = []

        with (
            patch("zotcli.write.connector_client.ConnectorClient.ping",
                  return_value={"zotero": "5.0"}),
            patch("zotcli.write.connector_client.ConnectorClient.get_selected_collection",
                  return_value={"name": "My Library"}),
            patch("zotcli.write.connector_client.ConnectorClient.save_items",
                  return_value=_make_save_items_response()),
            patch("zotcli.write.connector_client.ConnectorClient.update_session",
                  return_value={}),
            patch("zotcli.write.connector_client.ConnectorClient.save_attachment",
                  side_effect=lambda **kw: save_attachment_calls.append(kw) or {}),
            patch("zotcli.write.resolvers.crossref.resolve",
                  return_value={
                      "DOI": "10.1038/test",
                      "title": "Test Paper",
                      "author": [],
                      "type": "journal-article",
                  }),
            patch("zotcli.write.resolvers.unpaywall.find_oa_pdf_url",
                  return_value="https://example.com/paper.pdf"),
            patch("httpx.Client") as mock_client_cls,
        ):
            # Mock httpx for the PDF download
            mock_http_ctx = MagicMock()
            mock_http_ctx.__enter__ = MagicMock(return_value=mock_http_ctx)
            mock_http_ctx.__exit__ = MagicMock(return_value=False)
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.content = fake_pdf
            mock_http_ctx.get.return_value = mock_resp
            mock_client_cls.return_value = mock_http_ctx

            from zotcli.cli.main import cli
            runner = CliRunner()
            # Input: "y" for the prompt, then "user@example.com" for the email
            result = runner.invoke(
                cli,
                ["add", "doi", "10.1038/test", "--with-pdf"],
                input="y\nuser@example.com\n",
                catch_exceptions=False,
            )

        assert result.exit_code == 0, f"Output:\n{result.output}"
        # Verify Unpaywall was configured
        from zotcli.write import credentials as creds
        assert creds.get("unpaywall", "email") == "user@example.com"
        # Verify attachment was called
        assert len(save_attachment_calls) == 1


class TestWithPdfFirstTimePromptN:
    """First-time prompt: user presses N → skips PDF, exits 0."""

    def test_prompt_n_skips_pdf(self, tmp_path, monkeypatch):
        """When user presses N at the Unpaywall prompt, PDF is skipped."""
        save_attachment_calls = []

        with (
            patch("zotcli.write.connector_client.ConnectorClient.ping",
                  return_value={"zotero": "5.0"}),
            patch("zotcli.write.connector_client.ConnectorClient.get_selected_collection",
                  return_value={"name": "My Library"}),
            patch("zotcli.write.connector_client.ConnectorClient.save_items",
                  return_value=_make_save_items_response()),
            patch("zotcli.write.connector_client.ConnectorClient.update_session",
                  return_value={}),
            patch("zotcli.write.connector_client.ConnectorClient.save_attachment",
                  side_effect=lambda **kw: save_attachment_calls.append(kw) or {}),
            patch("zotcli.write.resolvers.crossref.resolve",
                  return_value={
                      "DOI": "10.1038/test",
                      "title": "Test Paper",
                      "author": [],
                      "type": "journal-article",
                  }),
        ):
            from zotcli.cli.main import cli
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["add", "doi", "10.1038/test", "--with-pdf"],
                input="n\n",
                catch_exceptions=False,
            )

        assert result.exit_code == 0, f"Output:\n{result.output}"
        assert len(save_attachment_calls) == 0
        # "Skipping" message should appear
        assert "skip" in result.output.lower() or "No PDF" in result.output


@pytest.mark.skip(
    reason="The first-time Unpaywall prompt was removed in 0.3.0; the "
    "find_file pipeline does not require interactive setup."
)
class TestWithPdfFirstTimePromptQ:
    """First-time prompt: user presses q → aborts."""

    def test_prompt_q_aborts(self, tmp_path, monkeypatch):
        """When user presses q at the Unpaywall prompt, command aborts with error."""
        with (
            patch("zotcli.write.connector_client.ConnectorClient.ping",
                  return_value={"zotero": "5.0"}),
            patch("zotcli.write.connector_client.ConnectorClient.get_selected_collection",
                  return_value={"name": "My Library"}),
            patch("zotcli.write.connector_client.ConnectorClient.save_items",
                  return_value=_make_save_items_response()),
            patch("zotcli.write.connector_client.ConnectorClient.update_session",
                  return_value={}),
            patch("zotcli.write.resolvers.crossref.resolve",
                  return_value={
                      "DOI": "10.1038/test",
                      "title": "Test Paper",
                      "author": [],
                      "type": "journal-article",
                  }),
        ):
            from zotcli.cli.main import cli
            runner = CliRunner()
            result = runner.invoke(
                cli,
                ["add", "doi", "10.1038/test", "--with-pdf"],
                input="q\n",
                catch_exceptions=False,
            )

        # Should exit with error code
        assert result.exit_code != 0
        assert "abort" in result.output.lower() or "Error" in result.output


class TestLoginCommand:
    """Tests for the `zot add login` command."""

    def test_login_unpaywall_saves_email(self, tmp_path, monkeypatch):
        """zot add login --service unpaywall saves email and enables Unpaywall."""
        monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))

        from zotcli.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", "login", "--service", "unpaywall"],
            input="testuser@example.com\n",
            catch_exceptions=False,
        )

        assert result.exit_code == 0, f"Output:\n{result.output}"
        from zotcli.write import credentials as creds
        assert creds.get("unpaywall", "email") == "testuser@example.com"
        from zotcli.config import get_config_value
        assert get_config_value("unpaywall.enabled") == "true"

    def test_login_unpaywall_rejects_invalid_email(self, tmp_path, monkeypatch):
        """zot add login --service unpaywall rejects malformed email."""
        monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))

        from zotcli.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", "login", "--service", "unpaywall"],
            input="not-an-email\n",
        )

        assert result.exit_code != 0
        assert "Invalid email" in result.output or "invalid" in result.output.lower()

    def test_login_ieee_without_browser_errors_clearly(self, tmp_path, monkeypatch):
        """zot add login --service ieee fails with clear message when playwright absent."""
        monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))
        import zotcli.write.browser as browser_mod
        monkeypatch.setattr(browser_mod, "is_browser_extra_installed", lambda: False)

        from zotcli.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "login", "--service", "ieee"])

        assert result.exit_code != 0
        assert "browser" in result.output.lower() or "playwright" in result.output.lower()

    def test_login_status_shows_all_services(self, tmp_path, monkeypatch):
        """zot add login (no --service) shows status of all services."""
        monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))

        from zotcli.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(cli, ["add", "login"])

        assert result.exit_code == 0
        assert "unpaywall" in result.output
        assert "ieee" in result.output
        assert "sciencedirect" in result.output

    def test_login_reset_unpaywall(self, tmp_path, monkeypatch):
        """zot add login --service unpaywall --reset clears stored credentials."""
        monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))

        # Set up some credentials first
        from zotcli.write import credentials as creds
        creds.set("unpaywall", "email", "old@example.com")

        from zotcli.cli.main import cli
        runner = CliRunner()
        result = runner.invoke(
            cli,
            ["add", "login", "--service", "unpaywall", "--reset"],
        )

        assert result.exit_code == 0
        assert creds.get("unpaywall", "email") is None
