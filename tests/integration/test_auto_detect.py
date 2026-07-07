"""Integration tests for M5: auto-detect dispatcher (``zot add "<anything>"``).

Uses monkeypatching — no live network, no live Zotero.
"""

from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli

# ---------------------------------------------------------------------------
# Shared mock CSL records
# ---------------------------------------------------------------------------

MOCK_DOI_CSL = {
    "type": "journal-article",
    "title": ["Array programming with NumPy"],
    "author": [{"given": "Charles R.", "family": "Harris"}],
    "issued": {"date-parts": [[2020, 9, 16]]},
    "DOI": "10.1038/s41586-020-2649-2",
    "container-title": ["Nature"],
    "volume": "585",
    "page": "357-362",
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

MOCK_ISBN_CSL = {
    "type": "book",
    "title": "Introduction to Algorithms",
    "author": [{"given": "Thomas H.", "family": "Cormen"}],
    "issued": {"date-parts": [[2009]]},
    "ISBN": "9780262033848",
    "publisher": "MIT Press",
}

MOCK_PMID_CSL = {
    "type": "journal-article",
    "title": "Test PMID Paper",
    "author": [{"given": "A.", "family": "Author"}],
    "issued": {"date-parts": [[2019]]},
    "DOI": "10.1007/test",
    "container-title": ["Test Journal"],
}

MOCK_CITE_CSL = {
    "type": "journal-article",
    "title": ["Beyond simplifications"],
    "author": [{"given": "J.", "family": "Zhang"}],
    "issued": {"date-parts": [[2025]]},
    "DOI": "10.1016/j.segan.2025.01.001",
    "container-title": ["SEGAN"],
}


@pytest.fixture
def runner():
    return CliRunner()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _invoke_dry_run(runner, args: list[str], monkeypatch) -> str:
    """Invoke the CLI with PYZOT_ALLOW_WRITE set, return output."""
    monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
    result = runner.invoke(cli, args)
    return result


# ---------------------------------------------------------------------------
# Removed legacy commands
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("legacy_name", "value", "replacement"),
    [
        ("doi", "10.1038/example", "zot add <DOI>"),
        ("arxiv", "1706.03762", "zot add <ID>"),
        ("pmid", "31452104", "zot add <PMID>"),
        ("isbn", "9780262033848", "zot add <ISBN>"),
        ("url", "https://example.org/article", "zot add <URL>"),
        ("file", "paper.pdf", "zot add <PATH>"),
        ("import", "refs.bib", "zot add <PATH>"),
    ],
)
def test_removed_legacy_commands_show_migration_hint(
    runner, legacy_name: str, value: str, replacement: str
):
    result = runner.invoke(cli, ["add", legacy_name, value])

    assert result.exit_code != 0
    assert "has been removed" in result.output
    assert replacement in result.output


# ---------------------------------------------------------------------------
# DOI auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectDoi:
    def test_bare_doi_dry_run_payload(self, runner, monkeypatch):
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "10.1038/s41586-020-2649-2", "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "journalArticle"
        assert payload["sessionID"] == "<dry-run>"

    def test_doi_with_prefix_detected(self, runner, monkeypatch):
        """DOI with https://doi.org/ prefix is auto-detected as doi kind."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(
            cli, ["add", "https://doi.org/10.1038/s41586-020-2649-2", "--dry-run"]
        )
        # doi.org URLs are detected as "url" kind and routed through _run_url
        # which also resolves to doi pipeline — exit 0 expected
        assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# arXiv auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectArxiv:
    def test_bare_arxiv_payload(self, runner, monkeypatch):
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "1706.03762", "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "preprint"


# ---------------------------------------------------------------------------
# ISBN auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectIsbn:
    def test_bare_isbn_payload(self, runner, monkeypatch):
        monkeypatch.setattr(
            "pyzot.write.resolvers.openlibrary.resolve",
            lambda isbn: MOCK_ISBN_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "978-0-262-03384-8", "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "book"


# ---------------------------------------------------------------------------
# URL auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectUrl:
    def test_bare_arxiv_url(self, runner, monkeypatch):
        """https://arxiv.org/abs/... is detected as 'url' kind (routed via _run_url)."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "https://arxiv.org/abs/1706.03762", "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "preprint"

    def test_bare_url_routes_by_pattern(self, runner, monkeypatch):
        """``zot add https://arxiv.org/abs/X`` routes through URL handling."""
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "https://arxiv.org/abs/1706.03762", "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "preprint"


# ---------------------------------------------------------------------------
# Citation string auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectCitation:
    def test_bare_citation_dispatches_to_cite(self, runner, monkeypatch):
        """A multi-word string is detected as 'citation' kind."""
        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            lambda text, *, threshold, gap, interactive, console=None: MOCK_CITE_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        citation = "Zhang, J. et al. (2025) Beyond simplifications."
        result = runner.invoke(cli, ["add", citation, "--dry-run"])
        assert result.exit_code == 0, result.output
        payload = json.loads(result.output)
        assert payload["items"][0]["itemType"] == "journalArticle"

    def test_bare_citation_non_interactive(self, runner, monkeypatch):
        """--non-interactive propagates to citation pipeline."""

        def mock_resolve(text, *, threshold, gap, interactive, console=None):
            if not interactive:
                return None  # Simulate ambiguous non-interactive
            return MOCK_CITE_CSL

        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            mock_resolve,
        )
        monkeypatch.setattr("pyzot.cli.add.pipeline._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add.pipeline._open_db", lambda: None)
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        citation = "Zhang, J. et al. (2025) Beyond simplifications."
        result = runner.invoke(cli, ["add", citation, "--dry-run", "--non-interactive"])
        # Should fail because resolve returns None in non-interactive mode
        assert result.exit_code != 0


# ---------------------------------------------------------------------------
# Filepath auto-detect
# ---------------------------------------------------------------------------


class TestAutoDetectFilepath:
    def test_bare_filepath_pdf_dispatches_to_file(self, runner, monkeypatch, tmp_path):
        """A path to a PDF file is detected as 'filepath' kind, dispatched to _run_file."""
        import shutil
        from pathlib import Path

        sample_pdf = Path(__file__).parent.parent / "fixtures" / "sample.pdf"
        if not sample_pdf.exists():
            pytest.skip("sample.pdf fixture not found")

        # Copy to tmp_path so we have a reliable path
        dest = tmp_path / "paper.pdf"
        shutil.copy(sample_pdf, dest)

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", str(dest), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Dry-run" in result.output
        assert "application/pdf" in result.output

    def test_bare_filepath_bib_dispatches_to_import(self, runner, monkeypatch, tmp_path):
        """A path to a .bib file is detected as 'filepath' kind, dispatched to _run_import."""
        bib_content = b"""@article{test2025,
  author = {Smith, John},
  title = {Test Paper},
  journal = {Journal of Tests},
  year = {2025},
}
"""
        bib_file = tmp_path / "refs.bib"
        bib_file.write_bytes(bib_content)

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", str(bib_file), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Content-Type" in result.output
        assert "bibtex" in result.output.lower()


# ---------------------------------------------------------------------------
# Unknown input
# ---------------------------------------------------------------------------


class TestAutoDetectUnknown:
    def test_unknown_input_gives_clear_error(self, runner, monkeypatch):
        """An unrecognisable token produces a helpful ClickException."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        result = runner.invoke(cli, ["add", "xyzzy"])
        # Single-word, no match → "unknown" kind → ClickException
        assert result.exit_code != 0
        assert "Cannot determine" in result.output or "Supported kinds" in result.output
