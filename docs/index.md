# Welcome to zotcli

**zotcli** (`zot`) is a read-only Python CLI and SDK for your local Zotero library. It queries the SQLite database directly — no Zotero app or API key needed.

## Features

- **Blazing Fast**: Directly queries `zotero.sqlite`.
- **Read-Only**: Safe to use. Never writes to the database.
- **Python SDK**: Rich programmatic access to your Zotero library via Pydantic models.
- **CLI Tool**: Powerful `zot` command-line interface for browsing, searching, and exporting.
- **Full-text Retrieval Flow**: Network-first retrieval with config-auth and Playwright fallback.

## Project Layout

- `src/zotcli/db.py`: Database connection and auto-discovery.
- `src/zotcli/models.py`: Pydantic models mapping Zotero entries.
- `src/zotcli/queries/`: SQL queries to search and retrieve data.
- `src/zotcli/cli/`: Click-based CLI application.

Navigate to [Getting Started](getting_started.md) to begin.
