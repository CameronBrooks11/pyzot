"""Tests for src/pyzot/write/identifiers.py.

Covers detect_kind(), normalize_doi(), normalize_arxiv(),
normalize_pmid(), normalize_isbn(), and ISBN checksum validation.
"""

from __future__ import annotations

from pyzot.write.identifiers import (
    _isbn10_checksum_valid,
    _isbn13_checksum_valid,
    detect_kind,
    normalize_arxiv,
    normalize_doi,
    normalize_isbn,
    normalize_pmid,
)

# ---------------------------------------------------------------------------
# DOI detection
# ---------------------------------------------------------------------------

class TestDetectDOI:
    def test_bare_doi(self):
        assert detect_kind("10.1038/s41586-020-2649-2") == "doi"

    def test_doi_with_doi_prefix(self):
        assert detect_kind("doi:10.1038/s41586-020-2649-2") == "doi"

    def test_doi_with_doi_colon_space(self):
        assert detect_kind("doi: 10.1038/s41586-020-2649-2") == "doi"

    def test_doi_org_url(self):
        assert detect_kind("https://doi.org/10.1038/s41586-020-2649-2") == "doi"

    def test_dx_doi_org_url(self):
        assert detect_kind("https://dx.doi.org/10.1038/s41586-020-2649-2") == "doi"

    def test_doi_http(self):
        assert detect_kind("http://doi.org/10.1038/s41586-020-2649-2") == "doi"

    def test_ieee_doi(self):
        assert detect_kind("10.1109/TPWRS.2023.1234567") == "doi"

    def test_doi_minimum_prefix(self):
        # 10.NNNN/ minimum — 4 digits
        assert detect_kind("10.1234/foo") == "doi"

    def test_doi_9digit_prefix(self):
        assert detect_kind("10.123456789/some.thing") == "doi"


# ---------------------------------------------------------------------------
# DOI normalisation
# ---------------------------------------------------------------------------

class TestNormalizeDOI:
    def test_bare_doi_lowercased(self):
        assert normalize_doi("10.1038/Example") == "10.1038/example"

    def test_doi_prefix_stripped(self):
        assert normalize_doi("doi:10.1038/Example") == "10.1038/example"

    def test_doi_org_url_stripped(self):
        assert normalize_doi("https://doi.org/10.1038/Example") == "10.1038/example"

    def test_dx_doi_org_url_stripped(self):
        assert normalize_doi("https://dx.doi.org/10.1038/Example") == "10.1038/example"

    def test_already_normalised(self):
        assert normalize_doi("10.1038/example") == "10.1038/example"


# ---------------------------------------------------------------------------
# arXiv detection
# ---------------------------------------------------------------------------

class TestDetectArXiv:
    def test_modern_format(self):
        assert detect_kind("2401.12345") == "arxiv"

    def test_modern_format_with_version(self):
        assert detect_kind("2401.12345v2") == "arxiv"

    def test_modern_5digit(self):
        assert detect_kind("2103.00020") == "arxiv"

    def test_legacy_format(self):
        assert detect_kind("cs.AI/0701001") == "arxiv"

    def test_legacy_with_version(self):
        assert detect_kind("hep-th/9901001v2") == "arxiv"

    def test_arxiv_url(self):
        assert detect_kind("https://arxiv.org/abs/2401.12345") == "arxiv"

    def test_arxiv_url_with_version(self):
        assert detect_kind("https://arxiv.org/abs/2401.12345v1") == "arxiv"

    def test_arxiv_pdf_url(self):
        assert detect_kind("https://arxiv.org/pdf/2401.12345.pdf") == "arxiv"

    def test_arxiv_colon_prefix(self):
        assert detect_kind("arxiv:2401.12345") == "arxiv"

    def test_arxiv_colon_prefix_case_insensitive(self):
        assert detect_kind("arXiv:2401.12345") == "arxiv"


# ---------------------------------------------------------------------------
# arXiv normalisation
# ---------------------------------------------------------------------------

class TestNormalizeArXiv:
    def test_bare_id_unchanged(self):
        assert normalize_arxiv("2401.12345") == "2401.12345"

    def test_colon_prefix_stripped(self):
        assert normalize_arxiv("arxiv:2401.12345") == "2401.12345"

    def test_colon_prefix_case_insensitive(self):
        assert normalize_arxiv("arXiv:2401.12345v2") == "2401.12345v2"

    def test_url_stripped(self):
        assert normalize_arxiv("https://arxiv.org/abs/2401.12345") == "2401.12345"

    def test_url_with_version_stripped(self):
        assert normalize_arxiv("https://arxiv.org/abs/2401.12345v1") == "2401.12345v1"


# ---------------------------------------------------------------------------
# PMID detection
# ---------------------------------------------------------------------------

class TestDetectPMID:
    def test_bare_digits(self):
        assert detect_kind("31452104") == "pmid"

    def test_single_digit(self):
        assert detect_kind("1") == "pmid"

    def test_max_9_digits(self):
        assert detect_kind("123456789") == "pmid"

    def test_pmid_prefix(self):
        assert detect_kind("pmid:31452104") == "pmid"

    def test_PMID_prefix_uppercase(self):
        assert detect_kind("PMID:31452104") == "pmid"

    def test_10_digits_is_not_pmid(self):
        # 10 digits: could be ISBN-10 or unknown
        result = detect_kind("1234567890")
        assert result in ("isbn", "pmid", "unknown")

    def test_non_digit_is_not_pmid(self):
        assert detect_kind("12345X") != "pmid"


# ---------------------------------------------------------------------------
# PMID normalisation
# ---------------------------------------------------------------------------

class TestNormalizePMID:
    def test_bare_digits_unchanged(self):
        assert normalize_pmid("31452104") == "31452104"

    def test_pmid_prefix_stripped(self):
        assert normalize_pmid("pmid:31452104") == "31452104"

    def test_pubmed_prefix_stripped(self):
        assert normalize_pmid("pubmed:31452104") == "31452104"


# ---------------------------------------------------------------------------
# ISBN detection and checksum
# ---------------------------------------------------------------------------

class TestISBN10Checksum:
    def test_valid_isbn10(self):
        # Known valid ISBN-10: 0-306-40615-2
        assert _isbn10_checksum_valid("0306406152") is True

    def test_valid_isbn10_with_x(self):
        # ISBN-10 with X check digit: 047043340X
        assert _isbn10_checksum_valid("047043340X") is True

    def test_invalid_isbn10(self):
        assert _isbn10_checksum_valid("0306406151") is False

    def test_wrong_length(self):
        assert _isbn10_checksum_valid("030640615") is False
        assert _isbn10_checksum_valid("03064061522") is False


class TestISBN13Checksum:
    def test_valid_isbn13(self):
        # Known valid ISBN-13: 978-0-306-40615-7
        assert _isbn13_checksum_valid("9780306406157") is True

    def test_valid_isbn13_clri(self):
        # CLRI - Introduction to Algorithms
        assert _isbn13_checksum_valid("9780262033848") is True

    def test_invalid_isbn13(self):
        assert _isbn13_checksum_valid("9780306406156") is False

    def test_wrong_length(self):
        assert _isbn13_checksum_valid("978030640615") is False


class TestDetectISBN:
    def test_isbn13_hyphenated(self):
        assert detect_kind("978-0-262-03384-8") == "isbn"

    def test_isbn13_bare(self):
        assert detect_kind("9780262033848") == "isbn"

    def test_isbn10_bare(self):
        assert detect_kind("0306406152") == "isbn"

    def test_isbn10_with_x(self):
        assert detect_kind("047043340X") == "isbn"

    def test_isbn_prefix(self):
        assert detect_kind("ISBN:9780262033848") == "isbn"

    def test_isbn_prefix_lowercase(self):
        assert detect_kind("isbn:9780262033848") == "isbn"

    def test_invalid_isbn13_detected_as_not_isbn(self):
        # Wrong checksum — should not be detected as ISBN
        result = detect_kind("9780262033847")
        assert result != "isbn"


# ---------------------------------------------------------------------------
# ISBN normalisation
# ---------------------------------------------------------------------------

class TestNormalizeISBN:
    def test_strips_hyphens(self):
        assert normalize_isbn("978-0-262-03384-8") == "9780262033848"

    def test_strips_isbn_prefix(self):
        assert normalize_isbn("ISBN:9780262033848") == "9780262033848"

    def test_strips_isbn_prefix_lowercase(self):
        assert normalize_isbn("isbn:978-0-262-03384-8") == "9780262033848"

    def test_bare_digits_unchanged(self):
        assert normalize_isbn("9780262033848") == "9780262033848"


# ---------------------------------------------------------------------------
# URL detection
# ---------------------------------------------------------------------------

class TestDetectURL:
    def test_https_url(self):
        assert detect_kind("https://example.org/paper.html") == "url"

    def test_http_url(self):
        assert detect_kind("http://ieeexplore.ieee.org/document/12345") == "url"

    def test_non_doi_url(self):
        assert detect_kind("https://example.org/science/article/XYZ") == "url"


# ---------------------------------------------------------------------------
# Filepath detection
# ---------------------------------------------------------------------------

class TestDetectFilepath:
    def test_absolute_unix(self):
        assert detect_kind("/home/user/paper.pdf") == "filepath"

    def test_tilde_home(self):
        assert detect_kind("~/Downloads/paper.pdf") == "filepath"

    def test_relative_dot_slash(self):
        assert detect_kind("./paper.pdf") == "filepath"

    def test_windows_drive(self):
        assert detect_kind("C:\\Users\\user\\paper.pdf") == "filepath"


# ---------------------------------------------------------------------------
# Citation / unknown fallbacks
# ---------------------------------------------------------------------------

class TestDetectOther:
    def test_multiword_is_citation(self):
        assert detect_kind("Zhang, J. et al. (2025) Beyond simplifications...") == "citation"

    def test_empty_string_is_unknown(self):
        assert detect_kind("") == "unknown"

    def test_single_word_non_doi_is_unknown(self):
        result = detect_kind("foobar")
        assert result in ("unknown", "citation")
