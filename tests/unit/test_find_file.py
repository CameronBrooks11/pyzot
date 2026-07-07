"""Unit tests for pyzot.write.find_file (resolver pipeline)."""

from __future__ import annotations

from unittest.mock import patch


def test_build_resolvers_empty_inputs():
    from pyzot.write.find_file import build_resolvers
    assert build_resolvers(doi=None, item_url=None) == []
    assert build_resolvers(doi="", item_url="") == []


def test_build_resolvers_doi_first():
    from pyzot.write.find_file import build_resolvers
    entries = build_resolvers(
        doi="10.1/x",
        item_url="https://example.org/paper",
        methods=("doi", "url"),
    )
    assert len(entries) == 2
    assert entries[0].page_url == "https://doi.org/10.1/x"
    assert entries[0].access_method == "doi"
    assert entries[1].page_url == "https://example.org/paper"
    assert entries[1].access_method == "url"


def test_extract_pdf_url_meta_tag():
    from pyzot.write.find_file import _extract_pdf_url
    html = '<html><head><meta name="citation_pdf_url" content="https://x/paper.pdf"></head></html>'
    assert _extract_pdf_url(html, "https://base/") == "https://x/paper.pdf"


def test_extract_pdf_url_href_pdf():
    from pyzot.write.find_file import _extract_pdf_url
    html = '<html><body><a href="/download/paper.pdf?token=x">Download</a></body></html>'
    assert _extract_pdf_url(html, "https://base.org/article/123") == "https://base.org/download/paper.pdf?token=x"


def test_extract_pdf_url_keyword_fallback():
    from pyzot.write.find_file import _extract_pdf_url
    html = '<html><body><a href="https://wiley/pdfdirect/10.X">PDF</a></body></html>'
    assert _extract_pdf_url(html, "https://x/") == "https://wiley/pdfdirect/10.X"


def test_extract_pdf_url_no_match():
    from pyzot.write.find_file import _extract_pdf_url
    assert _extract_pdf_url("<html><body>no link</body></html>", "https://x") is None


def test_find_file_returns_none_when_no_inputs():
    from pyzot.write.find_file import find_file
    assert find_file(doi=None, item_url=None) is None


def test_find_file_returns_first_successful_download(tmp_path):
    """find_file should return the first PDF-magic-bearing payload from any resolver."""
    from pyzot.write.find_file import FindFileResult, find_file

    fake_pdf = b"%PDF-1.4 fake content"

    with (
        patch("pyzot.write.find_file._scrape_pdf_url_from_page", return_value="https://x/paper.pdf"),
        patch("pyzot.write.find_file._http_get_pdf", return_value=fake_pdf),
    ):
        r = find_file(doi="10.1/x", methods=("doi",))
    assert isinstance(r, FindFileResult)
    assert r.access_method == "doi"
    try:
        assert r.path.read_bytes() == fake_pdf
    finally:
        r.path.unlink()
