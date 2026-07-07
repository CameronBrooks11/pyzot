# pyzot (`zot`)

A command-line interface for a local [Zotero](https://www.zotero.org/) library.
Read commands query `zotero.sqlite` directly in read-only mode. Write commands
are opt-in and use Zotero's local connector HTTP server for item creation;
`zotero.sqlite` is never mutated directly by the add pipeline.

## Installation

```bash
pip install pyzot
pip install "pyzot[write]"   # required for `zot add ...`
pip install "pyzot[all]"     # write + optional export helpers
```

Verify:

```bash
zot --help
```

By default pyzot looks for `~/Zotero/zotero.sqlite`; override with `--db PATH`
or set `database.path` in the config.

## What It Does

- Browse items, collections, tags, notes, attachments, and library statistics.
- Search by title, author, DOI, tag, year, item type, and Zotero full-text index.
- Export items as JSON, CSV, BibTeX, or Markdown.
- Add items through Zotero's connector from DOI, arXiv ID, PMID, ISBN, URL,
  citation string, local PDF/EPUB, RIS, BibTeX, or CSL-JSON.
- Attach a local file to an existing item, or run an HTTP-only PDF finder for
  existing items.

## Safety Model

Read commands open the database as read-only. Connector add commands require one
of:

```bash
zot config set write.enabled true
zot --allow-write add "10.1038/s41586-020-2649-2"
PYZOT_ALLOW_WRITE=1 zot add "10.1038/s41586-020-2649-2"
```

Zotero must be running for connector writes.

## Common Commands

```bash
zot stats
zot collections list
zot items list --limit 20
zot items show ABCD1234
zot search "state estimation" --field title
zot attachments path ABCD1234
zot export bib --collection "Smart Grid" --output refs.bib
```

Add examples:

```bash
zot add "10.1038/s41586-020-2649-2" --dry-run
zot add "2401.12345" --collection Preprints
zot add "9780262033848" --tag book
zot add "https://arxiv.org/abs/1706.03762"
zot add "~/Downloads/paper.pdf" --collection Inbox
zot add "~/Downloads/refs.bib" --tag imported
zot add batch papers.txt --collection Inbox
```

`zot add <input>` is the primary interface; it auto-detects the input type.
`zot add batch` processes one mixed input per line.

## Repository Layout

```text
src/pyzot/
  cli/                  Click commands
  queries/              Read-only SQLite query layer
  export/               JSON/CSV/BibTeX/Markdown exporters
  write/                Connector client, add pipeline, resolvers, attachment helpers
tests/                  Unit and integration tests
docs/                   Maintainer and command documentation
```

## Development

```bash
just setup   # sync all extras + dev group
just check   # ruff format --check + ruff check + mypy
just test    # pytest with all extras
```
