"""Identifier detection and normalisation for pyzot write pipeline.

Pure functions — no I/O, no external deps.

detect_kind(s) → one of:
    "doi" | "arxiv" | "pmid" | "isbn" | "url" | "citation" | "filepath" | "unknown"
"""

from __future__ import annotations

import re
from typing import Literal

# ---------------------------------------------------------------------------
# Type alias
# ---------------------------------------------------------------------------

Kind = Literal["doi", "arxiv", "pmid", "isbn", "url", "citation", "filepath", "unknown"]


# ---------------------------------------------------------------------------
# Regexes (pre-compiled for speed)
# ---------------------------------------------------------------------------

# DOI canonical: 10.NNNN/ ...
_DOI_CANONICAL = re.compile(r"^10\.\d{4,9}/\S+$")
# DOI with common prefixes that should be stripped
_DOI_PREFIX = re.compile(
    r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)(10\.\d{4,9}/\S+)$",
    re.IGNORECASE,
)

# arXiv — modern format: YYMM.NNNNN or YYMM.NNNNNvN
_ARXIV_MODERN = re.compile(r"^\d{4}\.\d{4,5}(?:v\d+)?$")
# arXiv — legacy format: archive/NNNNNNN (e.g. cs.AI/0701001)
_ARXIV_LEGACY = re.compile(r"^[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?$")
# arXiv with URL prefix
_ARXIV_URL = re.compile(
    r"^https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)(?:\.pdf)?$",
    re.IGNORECASE,
)
# arXiv with prefix "arxiv:"
_ARXIV_COLON = re.compile(r"^arxiv:\s*(.+)$", re.IGNORECASE)

# PMID — digits only, length 1-9
_PMID = re.compile(r"^\d{1,9}$")
# PMID with explicit prefix
_PMID_PREFIX = re.compile(r"^(?:pmid:?\s*|pubmed:?\s*)(\d{1,9})$", re.IGNORECASE)

# URL
_URL = re.compile(r"^https?://\S+$", re.IGNORECASE)

# Filepath heuristics: starts with / or ~ or ./ or .\
_FILEPATH = re.compile(r"^[/~]|^\./|^\.\\|^[A-Za-z]:\\")


# ---------------------------------------------------------------------------
# ISBN helpers
# ---------------------------------------------------------------------------

def _strip_isbn(s: str) -> str:
    """Remove hyphens and spaces from an ISBN string."""
    return re.sub(r"[\s\-]", "", s)


def _isbn10_checksum_valid(s: str) -> bool:
    """Validate an ISBN-10 checksum (last digit may be X)."""
    if len(s) != 10:
        return False
    total = 0
    for i, ch in enumerate(s[:-1]):
        if not ch.isdigit():
            return False
        total += int(ch) * (10 - i)
    last = s[-1].upper()
    if last == "X":
        total += 10
    elif last.isdigit():
        total += int(last)
    else:
        return False
    return total % 11 == 0


def _isbn13_checksum_valid(s: str) -> bool:
    """Validate an ISBN-13 checksum."""
    if len(s) != 13 or not s.isdigit():
        return False
    total = sum(
        int(ch) * (1 if i % 2 == 0 else 3)
        for i, ch in enumerate(s)
    )
    return total % 10 == 0


def _looks_like_isbn(raw: str) -> bool:
    """Return True if raw looks like a (possibly hyphenated) ISBN-10 or ISBN-13."""
    # Strip the "ISBN:" prefix if present
    s = re.sub(r"^isbn:?\s*", "", raw, flags=re.IGNORECASE)
    stripped = _strip_isbn(s)
    if len(stripped) == 10:
        return _isbn10_checksum_valid(stripped)
    if len(stripped) == 13:
        return _isbn13_checksum_valid(stripped)
    return False


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------

def normalize_doi(s: str) -> str:
    """Strip common DOI prefixes and return a lowercase DOI.

    E.g. "https://doi.org/10.1038/foo" → "10.1038/foo"
    """
    s = s.strip()
    m = _DOI_PREFIX.match(s)
    if m:
        return m.group(1).lower()
    return s.lower()


def normalize_arxiv(s: str) -> str:
    """Strip "arxiv:" prefix and URL prefix; return bare arXiv ID.

    E.g. "arXiv:2401.12345v2" → "2401.12345v2"
         "https://arxiv.org/abs/2401.12345" → "2401.12345"
    """
    s = s.strip()
    # URL form
    m = _ARXIV_URL.match(s)
    if m:
        return m.group(1)
    # "arxiv:" prefix
    m = _ARXIV_COLON.match(s)
    if m:
        return m.group(1).strip()
    return s


def normalize_pmid(s: str) -> str:
    """Strip "pmid:" / "pubmed:" prefix and return bare digit string."""
    s = s.strip()
    m = _PMID_PREFIX.match(s)
    if m:
        return m.group(1)
    return s


def normalize_isbn(s: str) -> str:
    """Strip ISBN prefix and hyphens, return digit string (with possible trailing X)."""
    s = re.sub(r"^isbn:?\s*", "", s.strip(), flags=re.IGNORECASE)
    return _strip_isbn(s)


# ---------------------------------------------------------------------------
# Main dispatcher
# ---------------------------------------------------------------------------

def detect_kind(s: str) -> Kind:
    """Detect the kind of identifier in *s*.

    Returns one of:
        "doi" | "arxiv" | "pmid" | "isbn" | "url" | "citation" | "filepath" | "unknown"

    Detection is purely syntactic (regex + checksum for ISBN).
    """
    s = s.strip()
    if not s:
        return "unknown"

    # --- DOI ---
    # Accept "doi:" prefix or https://doi.org/ prefix
    candidate = s
    m = _DOI_PREFIX.match(s)
    if m:
        candidate = m.group(1)
    if _DOI_CANONICAL.match(candidate):
        return "doi"

    # --- arXiv ---
    arxiv_candidate = normalize_arxiv(s)
    if _ARXIV_MODERN.match(arxiv_candidate) or _ARXIV_LEGACY.match(arxiv_candidate):
        return "arxiv"
    # arXiv URL form
    if _ARXIV_URL.match(s):
        return "arxiv"

    # --- ISBN (before PMID — must check digits-only with length / checksum) ---
    # Explicit "isbn:" prefix
    if re.match(r"^isbn:?\s*", s, re.IGNORECASE):
        raw_isbn = re.sub(r"^isbn:?\s*", "", s, flags=re.IGNORECASE)
        stripped = _strip_isbn(raw_isbn)
        if len(stripped) in (10, 13):
            return "isbn"
    # Otherwise: looks like a hyphenated ISBN or 13-digit bare string
    if _looks_like_isbn(s):
        return "isbn"

    # --- PMID (digits only, 1-9 chars) — after ISBN to avoid collision ---
    # Also accept explicit "pmid:" prefix
    pmid_candidate = normalize_pmid(s)
    if _PMID_PREFIX.match(s):
        if _PMID.match(pmid_candidate):
            return "pmid"
    # Bare digits that are NOT a valid ISBN — could be PMID
    if _PMID.match(s):
        # Only accept if short enough to plausibly be a PMID (max 9 digits)
        return "pmid"

    # --- URL ---
    if _URL.match(s):
        return "url"

    # --- Filepath ---
    if _FILEPATH.match(s):
        return "filepath"

    # --- Citation string (fallback for anything multi-word / author-like) ---
    # If it contains at least one space, treat as a free-text citation
    if " " in s:
        return "citation"

    return "unknown"
