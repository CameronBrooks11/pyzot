# Welcome to pyzot

> **Status: prototype, in maintenance.** Active development has moved to
> [zotgo](https://cameronbrooks11.github.io/zotgo/), a Go rewrite built on
> Zotero's local HTTP API (Zotero 7+). pyzot is kept as a working reference.

**pyzot** (`zot`) is a read-only Python CLI and SDK for your local Zotero library. It queries the SQLite database directly — no Zotero app or API key needed.

## Features

- **Blazing Fast**: Directly queries `zotero.sqlite`.
- **Read-Only**: Safe to use. Never writes to the database.
- **Python SDK**: Rich programmatic access to your Zotero library via Pydantic models.
- **CLI Tool**: Powerful `zot` command-line interface for browsing, searching, and exporting.
- **Full-text Retrieval Flow**: Local cache, direct network retrieval, and metadata fallback.

## Project Layout

- `src/pyzot/db.py`: Database connection and auto-discovery.
- `src/pyzot/models.py`: Pydantic models mapping Zotero entries.
- `src/pyzot/queries/`: SQL queries to search and retrieve data.
- `src/pyzot/cli/`: Click-based CLI application.

Navigate to [Getting Started](getting-started.md) to begin.
