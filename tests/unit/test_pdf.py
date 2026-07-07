"""Unit tests for src/pyzot/write/pdf.py.

Tests sniff_mime, human_size, and sniff_import_content_type.
Uses tmp_path + the committed fixtures in tests/fixtures/.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from pyzot.write.pdf import human_size, sniff_import_content_type, sniff_mime

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FIXTURES = Path(__file__).parent.parent / "fixtures"


def _make_zip_with_mimetype(dest: Path, mimetype_content: str) -> Path:
    """Create a ZIP file whose first stored entry is 'mimetype'."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as zf:
        info = zipfile.ZipInfo("mimetype")
        info.compress_type = zipfile.ZIP_STORED
        zf.writestr(info, mimetype_content)
        zf.writestr("dummy.txt", "content")
    dest.write_bytes(buf.getvalue())
    return dest


# ---------------------------------------------------------------------------
# sniff_mime — committed fixtures
# ---------------------------------------------------------------------------


def test_sniff_pdf_fixture():
    """sniff_mime on tests/fixtures/sample.pdf returns application/pdf."""
    assert sniff_mime(FIXTURES / "sample.pdf") == "application/pdf"


def test_sniff_epub_fixture():
    """sniff_mime on tests/fixtures/sample.epub returns application/epub+zip."""
    assert sniff_mime(FIXTURES / "sample.epub") == "application/epub+zip"


# ---------------------------------------------------------------------------
# sniff_mime — synthetic PDF
# ---------------------------------------------------------------------------


def test_sniff_pdf_magic(tmp_path: Path):
    """Any file starting with %PDF- is detected as PDF."""
    f = tmp_path / "doc.pdf"
    f.write_bytes(b"%PDF-1.4\n%Some PDF content here\n%%EOF\n")
    assert sniff_mime(f) == "application/pdf"


def test_sniff_pdf_magic_no_extension(tmp_path: Path):
    """PDF detected even with no extension."""
    f = tmp_path / "noexit"
    f.write_bytes(b"%PDF-1.7\n1 0 obj\n%%EOF\n")
    assert sniff_mime(f) == "application/pdf"


# ---------------------------------------------------------------------------
# sniff_mime — synthetic EPUB
# ---------------------------------------------------------------------------


def test_sniff_epub_magic(tmp_path: Path):
    """A proper EPUB ZIP is detected as application/epub+zip."""
    f = tmp_path / "book.epub"
    _make_zip_with_mimetype(f, "application/epub+zip")
    assert sniff_mime(f) == "application/epub+zip"


def test_sniff_zip_not_epub(tmp_path: Path):
    """A plain ZIP (non-EPUB) returns None, not epub+zip."""
    f = tmp_path / "archive.zip"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("hello.txt", "hello world")
    f.write_bytes(buf.getvalue())
    result = sniff_mime(f)
    assert result is None


# ---------------------------------------------------------------------------
# sniff_mime — unknown file
# ---------------------------------------------------------------------------


def test_sniff_unknown_no_extension(tmp_path: Path):
    """Random binary with no known extension → None."""
    f = tmp_path / "data"
    f.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR")  # PNG header
    assert sniff_mime(f) is None


def test_sniff_unknown_extension_fallback(tmp_path: Path):
    """Extension .pdf but wrong magic → still returns pdf (extension fallback)."""
    # Write a file that starts with non-PDF bytes but has .pdf suffix
    f = tmp_path / "fake.pdf"
    f.write_bytes(b"\x00\x00\x00\x00\x00")  # not %PDF-
    # Should fall back to extension
    result = sniff_mime(f)
    assert result == "application/pdf"


def test_sniff_txt_extension(tmp_path: Path):
    """A .txt file returns None (not a supported type)."""
    f = tmp_path / "notes.txt"
    f.write_bytes(b"Hello world\n")
    assert sniff_mime(f) is None


# ---------------------------------------------------------------------------
# sniff_mime — edge cases
# ---------------------------------------------------------------------------


def test_sniff_empty_file_with_pdf_extension(tmp_path: Path):
    """Empty file with .pdf extension → extension fallback → application/pdf."""
    f = tmp_path / "empty.pdf"
    f.write_bytes(b"")
    assert sniff_mime(f) == "application/pdf"


def test_sniff_empty_file_no_extension(tmp_path: Path):
    """Empty file with no known extension → None."""
    f = tmp_path / "empty"
    f.write_bytes(b"")
    assert sniff_mime(f) is None


def test_sniff_very_small_file(tmp_path: Path):
    """A 3-byte file that starts with %PD (incomplete PDF magic) → extension fallback."""
    f = tmp_path / "small.txt"
    f.write_bytes(b"%PD")
    assert sniff_mime(f) is None  # txt extension not recognised


def test_sniff_epub_extension_fallback(tmp_path: Path):
    """Empty file with .epub extension → extension fallback → application/epub+zip."""
    f = tmp_path / "empty.epub"
    f.write_bytes(b"")
    assert sniff_mime(f) == "application/epub+zip"


def test_sniff_missing_file(tmp_path: Path):
    """sniff_mime on a non-existent file → extension fallback / None."""
    f = tmp_path / "ghost.xyz"
    # File does not exist — should not raise; extension xyz → None
    result = sniff_mime(f)
    assert result is None


# ---------------------------------------------------------------------------
# human_size
# ---------------------------------------------------------------------------


def test_human_size_zero():
    assert human_size(0) == "0 B"


def test_human_size_bytes():
    assert human_size(512) == "512 B"
    assert human_size(1023) == "1023 B"


def test_human_size_kib():
    assert human_size(1024) == "1.0 KiB"
    assert human_size(2048) == "2.0 KiB"
    assert human_size(1536) == "1.5 KiB"


def test_human_size_mib():
    assert human_size(1024 * 1024) == "1.0 MiB"


def test_human_size_gib():
    assert human_size(1024**3) == "1.0 GiB"


def test_human_size_negative_raises():
    with pytest.raises(ValueError, match="non-negative"):
        human_size(-1)


# ---------------------------------------------------------------------------
# sniff_import_content_type
# ---------------------------------------------------------------------------


def test_import_ct_bib_extension(tmp_path: Path):
    f = tmp_path / "refs.bib"
    f.write_bytes(b"@article{x, title={test}}")
    assert sniff_import_content_type(f) == "application/x-bibtex"


def test_import_ct_bibtex_extension(tmp_path: Path):
    f = tmp_path / "refs.bibtex"
    f.write_bytes(b"@article{x, title={test}}")
    assert sniff_import_content_type(f) == "application/x-bibtex"


def test_import_ct_ris_extension(tmp_path: Path):
    f = tmp_path / "refs.ris"
    f.write_bytes(b"TY  - JOUR\nER  -")
    assert sniff_import_content_type(f) == "application/x-research-info-systems"


def test_import_ct_json_extension(tmp_path: Path):
    f = tmp_path / "refs.json"
    f.write_bytes(b'[{"title": "test"}]')
    assert sniff_import_content_type(f) == "application/vnd.citationstyles.csl+json"


def test_import_ct_bib_content_heuristic(tmp_path: Path):
    """Without a known extension, @ prefix → BibTeX."""
    f = tmp_path / "refs.txt"
    f.write_bytes(b"@article{key, title={Test}}")
    assert sniff_import_content_type(f) == "application/x-bibtex"


def test_import_ct_ris_content_heuristic(tmp_path: Path):
    """Without a known extension, TY  -  prefix → RIS."""
    f = tmp_path / "refs.data"
    f.write_bytes(b"TY  - JOUR\nAU  - Smith, J.\nER  -\n")
    assert sniff_import_content_type(f) == "application/x-research-info-systems"


def test_import_ct_json_content_heuristic(tmp_path: Path):
    """Without a known extension, valid JSON → CSL-JSON."""
    import json

    f = tmp_path / "refs.data"
    f.write_bytes(json.dumps([{"title": "test"}]).encode())
    assert sniff_import_content_type(f) == "application/vnd.citationstyles.csl+json"


def test_import_ct_fallback(tmp_path: Path):
    """Unknown extension + unknown content → text/plain."""
    f = tmp_path / "refs.xyz"
    f.write_bytes(b"something random here that is not ris bibtex or json\n")
    assert sniff_import_content_type(f) == "text/plain"


def test_import_ct_fixture_bib():
    """Fixture sample.bib is detected as BibTeX."""
    assert sniff_import_content_type(FIXTURES / "sample.bib") == "application/x-bibtex"


def test_import_ct_fixture_ris():
    """Fixture sample.ris is detected as RIS."""
    assert (
        sniff_import_content_type(FIXTURES / "sample.ris") == "application/x-research-info-systems"
    )


def test_import_ct_with_data_arg(tmp_path: Path):
    """sniff_import_content_type accepts pre-read data bytes."""
    f = tmp_path / "refs.unknown"
    data = b"@book{key, title={Test}}"
    f.write_bytes(data)
    assert sniff_import_content_type(f, data=data) == "application/x-bibtex"
