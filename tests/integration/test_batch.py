"""Integration tests for M5: ``zot add batch <file>``.

Covers:
- Mixed input file (DOI, arXiv, citation, file path).
- Per-line outcome reporting (ok / fail).
- Summary line ("X added, Y skipped, Z failed.").
- Exit code: 0 when all succeed, 1 when any fail.
- Failure mid-batch does not abort remaining lines.
- --dry-run passes through to all dispatched handlers.
- Blank lines and # comments are skipped.
- Connector calls are sequential (not concurrent).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli

FIXTURES = Path(__file__).parent.parent / "fixtures"

# ---------------------------------------------------------------------------
# Shared mock data
# ---------------------------------------------------------------------------

MOCK_DOI_CSL = {
    "type": "journal-article",
    "title": ["NumPy"],
    "author": [{"given": "Charles", "family": "Harris"}],
    "issued": {"date-parts": [[2020]]},
    "DOI": "10.1038/s41586-020-2649-2",
    "container-title": ["Nature"],
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
# Helper to build a batch input file
# ---------------------------------------------------------------------------


def _batch_file(tmp_path: Path, lines: list[str]) -> Path:
    p = tmp_path / "batch.txt"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# All-success batch (dry-run to avoid connector)
# ---------------------------------------------------------------------------


class TestBatchAllSuccess:
    def test_all_lines_processed_and_summary_ok(self, runner, monkeypatch, tmp_path):
        """All lines succeed → summary shows N added, 0 failed; exit 0."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = [
            "# This is a comment — should be skipped",
            "",  # blank — skipped
            "10.1038/s41586-020-2649-2",  # DOI
            "1706.03762",  # arXiv
        ]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "2 added" in result.output
        assert "0 failed" in result.output

    def test_comments_and_blanks_skipped(self, runner, monkeypatch, tmp_path):
        """Lines starting with # and blank lines are silently skipped."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = [
            "# comment 1",
            "   ",  # whitespace only
            "10.1038/s41586-020-2649-2",
            "# comment 2",
        ]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "1 added" in result.output


# ---------------------------------------------------------------------------
# Batch with failures
# ---------------------------------------------------------------------------


class TestBatchWithFailures:
    def test_failure_mid_batch_does_not_abort(self, runner, monkeypatch, tmp_path):
        """A failing line is reported but subsequent lines are still processed."""
        from pyzot.write.resolvers import IdentifierNotFound

        call_order: list[str] = []

        def mock_crossref_resolve(doi: str):
            call_order.append(doi)
            if "bad" in doi:
                raise IdentifierNotFound("doi", doi, "Not found in test")
            return MOCK_DOI_CSL

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr("pyzot.write.resolvers.crossref.resolve", mock_crossref_resolve)
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = [
            "10.1038/s41586-020-2649-2",  # ok DOI
            "10.9999/bad-doi",  # bad DOI — will fail
            "10.1038/s41586-020-2649-2",  # ok DOI again
        ]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])

        # Exit code should be 1 (failures present)
        assert result.exit_code == 1, result.output

        # Both ok DOIs should have been processed
        assert call_order.count("10.1038/s41586-020-2649-2") == 2

        # Summary should show 2 added, 1 failed
        assert "2 added" in result.output
        assert "1 failed" in result.output

    def test_all_fail_exits_1(self, runner, monkeypatch, tmp_path):
        """All lines fail → exit code 1."""
        from pyzot.write.resolvers import IdentifierNotFound

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: (_ for _ in ()).throw(IdentifierNotFound("doi", doi, "Not found")),
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = ["10.9999/bad1", "10.9999/bad2"]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 1
        assert "0 added" in result.output
        assert "2 failed" in result.output

    def test_all_succeed_exits_0(self, runner, monkeypatch, tmp_path):
        """All lines succeed → exit code 0."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = ["10.1038/s41586-020-2649-2"]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Batch with mixed kinds
# ---------------------------------------------------------------------------


class TestBatchMixedKinds:
    def test_mixed_doi_arxiv_processes_all(self, runner, monkeypatch, tmp_path):
        """A file with DOI and arXiv inputs processes all correctly."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv.resolve",
            lambda arxiv_id: MOCK_ARXIV_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = [
            "10.1038/s41586-020-2649-2",  # DOI
            "1706.03762",  # arXiv
        ]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "2 added" in result.output

    def test_file_path_in_batch(self, runner, monkeypatch, tmp_path):
        """A file path in a batch file is dispatched to the file/import handler."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        bib_content = b"""@article{test2025,
  author = {Smith, John},
  title = {Test Paper},
  journal = {Test Journal},
  year = {2025},
}
"""
        bib_file = tmp_path / "refs.bib"
        bib_file.write_bytes(bib_content)

        lines = [str(bib_file)]  # filepath
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "1 added" in result.output


# ---------------------------------------------------------------------------
# Batch options
# ---------------------------------------------------------------------------


class TestBatchOptions:
    def test_non_interactive_propagates_to_citation(self, runner, monkeypatch, tmp_path):
        """--non-interactive makes ambiguous citations fail rather than prompt."""

        def mock_resolve_ambiguous(text, *, threshold, gap, interactive, console=None):
            if not interactive:
                return None
            return MOCK_CITE_CSL

        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.citation_pipeline.resolve_citation",
            mock_resolve_ambiguous,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        citation = "Zhang, J. et al. (2025) Beyond simplifications."
        lines = [citation]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run", "--non-interactive"])
        assert result.exit_code == 1
        assert "1 failed" in result.output

    def test_jobs_stub_warning(self, runner, monkeypatch, tmp_path):
        """--jobs N > 1 emits a stub warning and still runs sequentially."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")
        monkeypatch.setattr(
            "pyzot.write.resolvers.crossref.resolve",
            lambda doi: MOCK_DOI_CSL,
        )
        monkeypatch.setattr("pyzot.cli.add._find_duplicate", lambda kind, id: None)
        monkeypatch.setattr("pyzot.cli.add._open_db", lambda: None)

        lines = ["10.1038/s41586-020-2649-2"]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch), "--dry-run", "--jobs", "4"])
        assert result.exit_code == 0, result.output
        # Warning about --jobs stub should appear on stderr (captured in output for CliRunner)
        assert "stub" in result.output.lower() or "sequentially" in result.output.lower()

    def test_empty_file_exits_0(self, runner, monkeypatch, tmp_path):
        """Empty batch file exits 0 with a message."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        batch = _batch_file(tmp_path, ["# only comments", ""])

        result = runner.invoke(cli, ["add", "batch", str(batch)])
        assert result.exit_code == 0

    def test_missing_file_exits_nonzero(self, runner, monkeypatch):
        """Non-existent batch file gives an error."""
        monkeypatch.setenv("PYZOT_ALLOW_WRITE", "1")

        result = runner.invoke(cli, ["add", "batch", "/nonexistent/path.txt"])
        assert result.exit_code != 0

    def test_write_gate_enforced(self, runner, monkeypatch, tmp_path):
        """Batch respects the write gate even though it delegates to _dispatch."""
        monkeypatch.delenv("PYZOT_ALLOW_WRITE", raising=False)
        monkeypatch.setattr("pyzot.config.get_write_enabled", lambda: False)

        lines = ["10.1038/s41586-020-2649-2"]
        batch = _batch_file(tmp_path, lines)

        result = runner.invoke(cli, ["add", "batch", str(batch)])
        assert result.exit_code != 0
        assert "Write capability is disabled" in result.output
