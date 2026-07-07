"""Database layer — read-only SQLite connection with auto-discovery."""

from __future__ import annotations

import os
import sqlite3
import sys
from pathlib import Path


def _default_db_paths() -> list[Path]:
    """Return candidate zotero.sqlite paths for the current platform."""
    candidates: list[Path] = []

    # WSL: Windows user directory mounted under /mnt/c
    if sys.platform == "linux" and Path("/mnt/c/Users").exists():
        for user_dir in Path("/mnt/c/Users").iterdir():
            p = user_dir / "Zotero" / "zotero.sqlite"
            candidates.append(p)

    home = Path.home()

    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        candidates.append(appdata / "Zotero" / "Zotero" / "zotero.sqlite")

    # macOS and Linux (and WSL fallback)
    candidates.append(home / "Zotero" / "zotero.sqlite")

    return candidates


def discover_db() -> Path:
    """Find the first existing zotero.sqlite on this system."""
    for p in _default_db_paths():
        if p.exists():
            return p
    raise FileNotFoundError(
        "Could not auto-detect zotero.sqlite. "
        "Pass --db PATH or set [database] path in ~/.config/pyzot/config.toml"
    )


def _check_wal_lock(db_path: Path) -> bool:
    """Return True if a WAL journal file exists (Zotero may be running)."""
    return db_path.with_suffix(".sqlite-wal").exists()


def _check_schema_version(conn: sqlite3.Connection) -> int:
    """Read and validate the Zotero schema version."""
    try:
        row = conn.execute("SELECT value FROM version WHERE schema = 'userdata'").fetchone()
    except sqlite3.OperationalError:
        # Older schema uses a different table
        row = conn.execute("SELECT MAX(version) FROM version").fetchone()

    if row is None:
        raise RuntimeError("Cannot determine Zotero schema version.")

    version = int(row[0])
    return version


class ZoteroDatabase:
    """Context-manager wrapper around a read-only sqlite3 connection."""

    def __init__(self, path: Path | str | None = None, warn_if_open: bool = True):
        if path is None:
            path = discover_db()
        self.path = Path(path)

        if warn_if_open and _check_wal_lock(self.path):
            import warnings

            warnings.warn(
                f"Zotero appears to be running (WAL journal found at {self.path}-wal). "
                "Changes made in Zotero may not be visible until it closes.",
                UserWarning,
                stacklevel=2,
            )

        uri = f"file:{self.path}?mode=ro"
        self._conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA query_only = ON")

        self.schema_version = _check_schema_version(self._conn)

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def fetchall(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def fetchone(self, sql: str, params: tuple = ()) -> sqlite3.Row | None:
        return self._conn.execute(sql, params).fetchone()

    def close(self) -> None:
        self._conn.close()

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> ZoteroDatabase:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"ZoteroDatabase(path={self.path!r}, schema_version={self.schema_version})"
