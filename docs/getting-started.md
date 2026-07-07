# Getting Started

## Installation

This project uses [`uv`](https://docs.astral.sh/uv/). Sync a development
environment with all optional features:

```bash
uv sync --all-extras
```

To build and serve the documentation locally, sync the `docs` extra and run
mkdocs:

```bash
uv sync --extra docs
uv run mkdocs serve
```

## Basic Usage (CLI)

The CLI tool auto-discovers your local Zotero database.

```bash
# View library stats
zot stats

# Search for papers with "bayesian" in the title
zot search "bayesian" --field title

# Get attachment paths for a specific item
zot attachments path <ITEM_ID_OR_KEY>

# Retrieve full text (network-first, then auth/local fallbacks)
zot items fulltext <ITEM_ID_OR_KEY>
zot items fulltext <ITEM_ID_OR_KEY> --offline
```

## Programmatic Usage (SDK)

`pyzot` provides a robust Python SDK for custom scripts.

### Usage Example: Search and Extract PDF Paths

```python
from pyzot.db import ZoteroDatabase
from pyzot.queries.search import search_items, search_by_author

def extract_pdfs():
    # Use ZoteroDatabase context manager for safe, read-only DB access
    with ZoteroDatabase() as db:
        # Search library by title
        bayesian = search_items(db, "bayesian", fields=["title"])
        
        # Search library by author
        numair = search_by_author(db, "Smith")
        
        seen = set()
        for item in bayesian + numair:
            if item.item_id in seen:
                continue
            seen.add(item.item_id)
            
            # Iterate through attachments and find valid PDFs
            for att in item.attachments:
                if att.file_exists and "pdf" in att.content_type.lower():
                    print(f"{item.key}\t{att.absolute_path}")

print("Extracting PDFs...")
extract_pdfs()
```
