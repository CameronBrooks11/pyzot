"""PDF/EPUB MIME-type sniffing and human-readable size formatting.

All functions are pure — no side effects, no network, no DB access.
"""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Magic-byte signatures
# ---------------------------------------------------------------------------

_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_EPUB_MIMETYPE_ENTRY = b"mimetypeapplication/epub+zip"


def sniff_mime(path: Path) -> str | None:
    """Detect the MIME type of a local file using magic bytes.

    Supports:
    - ``application/pdf``    — file starts with ``%PDF-``
    - ``application/epub+zip`` — file is a ZIP whose first stored entry is
      ``mimetype`` containing ``application/epub+zip`` (EPUB 3 / OPS spec)
    - ``None``               — unknown / unrecognised format

    The extension is consulted only as a tiebreaker when the magic bytes are
    inconclusive (e.g., empty file or read error).

    Parameters
    ----------
    path:
        Path to the local file.

    Returns
    -------
    str or None
        MIME type string, or ``None`` if the format is not recognised.
    """
    try:
        with path.open("rb") as fh:
            header = fh.read(256)
    except OSError:
        return _extension_fallback(path)

    if not header:
        # Empty file — fall back to extension
        return _extension_fallback(path)

    # PDF: starts with %PDF-
    if header[:5] == _PDF_MAGIC:
        return "application/pdf"

    # EPUB: ZIP file whose first stored entry is the "mimetype" file
    if header[:4] == _ZIP_MAGIC:
        if _is_epub(header):
            return "application/epub+zip"
        # It's a ZIP but not an EPUB — unknown for our purposes
        return None

    # Unknown magic — fall back to extension
    return _extension_fallback(path)


def _is_epub(header: bytes) -> bool:
    """Return True if the ZIP header looks like an EPUB.

    An EPUB must have the ``mimetype`` file as its first ZIP local file header
    entry, stored uncompressed, containing exactly ``application/epub+zip``.
    We detect this by searching for the characteristic byte sequence in the
    first 256 bytes of the file.

    The EPUB spec (OPS §3.4) mandates that the ``mimetype`` entry is the first
    entry and is not compressed, so the bytes appear contiguously in the header.
    """
    # The local file header for the "mimetype" entry will contain "mimetype"
    # followed by the content "application/epub+zip" stored uncompressed.
    # We look for a compact signature in the raw header bytes.
    needle = b"mimetypeapplication/epub+zip"
    return needle in header


def _extension_fallback(path: Path) -> str | None:
    """Return a MIME type based solely on the file extension."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return "application/pdf"
    if suffix == ".epub":
        return "application/epub+zip"
    return None


# ---------------------------------------------------------------------------
# Human-readable size
# ---------------------------------------------------------------------------

def human_size(n_bytes: int) -> str:
    """Format a byte count as a human-readable string.

    Examples
    --------
    >>> human_size(0)
    '0 B'
    >>> human_size(1023)
    '1023 B'
    >>> human_size(1024)
    '1.0 KiB'
    >>> human_size(1_048_576)
    '1.0 MiB'
    >>> human_size(1_073_741_824)
    '1.0 GiB'
    """
    if n_bytes < 0:
        raise ValueError(f"n_bytes must be non-negative, got {n_bytes!r}")
    if n_bytes < 1024:
        return f"{n_bytes} B"
    for unit in ("KiB", "MiB", "GiB", "TiB"):
        n_bytes /= 1024.0
        if n_bytes < 1024.0:
            return f"{n_bytes:.1f} {unit}"
    return f"{n_bytes:.1f} PiB"


# ---------------------------------------------------------------------------
# Import format sniffing (for `zot add import`)
# ---------------------------------------------------------------------------

_IMPORT_CONTENT_TYPES: dict[str, str] = {
    ".ris": "application/x-research-info-systems",
    ".bib": "application/x-bibtex",
    ".bibtex": "application/x-bibtex",
    ".json": "application/vnd.citationstyles.csl+json",
}


def sniff_import_content_type(path: Path, data: bytes | None = None) -> str:
    """Detect the content-type for a bibliography import file.

    Strategy (in order):
    1. Extension match (.ris, .bib, .bibtex, .json).
    2. Content heuristic on the first 512 bytes:
       - Starts with ``TY  - `` → RIS
       - Starts with ``@`` → BibTeX
       - Parses as JSON → CSL-JSON
    3. Fallback: ``text/plain``.

    Parameters
    ----------
    path:
        Path to the import file (used for extension lookup).
    data:
        First bytes of the file (used for heuristic if extension is unknown).
        If ``None``, the function reads up to 512 bytes from ``path``.

    Returns
    -------
    str
        MIME type string.
    """
    # 1. Extension
    suffix = path.suffix.lower()
    if suffix in _IMPORT_CONTENT_TYPES:
        return _IMPORT_CONTENT_TYPES[suffix]

    # 2. Content heuristic
    if data is None:
        try:
            with path.open("rb") as fh:
                data = fh.read(512)
        except OSError:
            return "text/plain"

    sample = data[:512].lstrip()

    if sample[:6] == b"TY  - ":
        return "application/x-research-info-systems"

    if sample[:1] == b"@":
        return "application/x-bibtex"

    try:
        import json as _json
        _json.loads(data)
        return "application/vnd.citationstyles.csl+json"
    except Exception:
        pass

    return "text/plain"
