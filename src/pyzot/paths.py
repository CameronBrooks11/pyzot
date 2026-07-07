"""Cross-platform self-contained path resolution for pyzot home directory.

Resolution order (per PLAN_WRITE.md §7.1):
1. PYZOT_HOME env var, if set.
2. Walk up from this file's directory looking for a sibling SKILL.md →
   use <that-dir>/.pyzot/.
3. Final fallback: Path.home() / ".pyzot".

Directory creation is lazy — only created when a write-path helper is called.
Pure functions; no heavy deps imported.
"""

from __future__ import annotations

import os
from pathlib import Path


def _find_skill_root() -> Path | None:
    """Walk up from this file's location looking for a directory containing SKILL.md.

    Returns the directory containing SKILL.md, or None if not found before
    reaching the filesystem root.
    """
    current = Path(__file__).resolve().parent
    # Walk up a reasonable number of levels (stop at filesystem root)
    for _ in range(20):
        if (current / "SKILL.md").exists():
            return current
        parent = current.parent
        if parent == current:
            # Reached filesystem root
            break
        current = parent
    return None


def pyzot_home() -> Path:
    """Return the pyzot home directory (does NOT create it).

    Resolution order:
    1. PYZOT_HOME env var.
    2. Sibling SKILL.md search → <skill-root>/.pyzot/
    3. Path.home() / ".pyzot"
    """
    env_home = os.environ.get("PYZOT_HOME")
    if env_home:
        return Path(env_home)

    skill_root = _find_skill_root()
    if skill_root is not None:
        return skill_root / ".pyzot"

    return Path.home() / ".pyzot"


def _ensure(p: Path) -> Path:
    """Create directory (and parents) if it doesn't exist, then return it."""
    p.mkdir(parents=True, exist_ok=True)
    return p


def config_path() -> Path:
    """Return path to config.toml (parent dir created lazily)."""
    p = pyzot_home() / "config.toml"
    _ensure(p.parent)
    return p


def credentials_path() -> Path:
    """Return path to credentials.json (parent dir created lazily)."""
    p = pyzot_home() / "credentials.json"
    _ensure(p.parent)
    return p


def cookies_root() -> Path:
    """Return path to cookies/ directory (created lazily)."""
    p = pyzot_home() / "cookies"
    return _ensure(p)


def cache_root() -> Path:
    """Return path to cache/ directory (created lazily)."""
    p = pyzot_home() / "cache"
    return _ensure(p)


def sessions_path() -> Path:
    """Return path to cache/sessions.jsonl (parent dir created lazily)."""
    p = pyzot_home() / "cache" / "sessions.jsonl"
    _ensure(p.parent)
    return p


def logs_path() -> Path:
    """Return path to logs/zot.log (parent dir created lazily)."""
    p = pyzot_home() / "logs" / "zot.log"
    _ensure(p.parent)
    return p
