# Write-Path Architecture

`pyzot` never creates Zotero parent items by writing directly to
`zotero.sqlite`. Item creation goes through Zotero's local connector server at
`127.0.0.1:23119`.

## Flow

```text
zot add <input>
  -> detect DOI / arXiv / PMID / ISBN / URL / citation / file / import
  -> resolve metadata when needed
  -> convert CSL-JSON to connector item shape
  -> POST to Zotero connector
  -> update connector session for target collection and tags
```

Endpoints used:

| Endpoint | Purpose |
|---|---|
| `GET /connector/ping` | Liveness check |
| `GET /connector/getSelectedCollection` | Current Zotero target |
| `POST /connector/saveItems` | Save metadata items |
| `POST /connector/saveSnapshot` | Save generic webpages |
| `POST /connector/saveStandaloneAttachment` | Import local PDF/EPUB |
| `POST /connector/import` | Import RIS/BibTeX/CSL-JSON |
| `POST /connector/updateSession` | Apply collection and tags |

## Kept Inputs

| Source | Path |
|---|---|
| DOI | Crossref |
| arXiv | arXiv Atom feed |
| PubMed PMID | NCBI eUtils |
| ISBN | OpenLibrary |
| Citation string | Crossref search, then OpenAlex, then Semantic Scholar |
| URL | arXiv/PubMed/DOI pattern routing, otherwise connector snapshot |
| Local PDF/EPUB | Connector standalone attachment |
| RIS/BibTeX/CSL-JSON | Connector import |

## Removed Scope

The Tier-B scrub removed publisher-specific PDF scraping, service login flows,
cookie/profile management, and automatic open-access PDF lookup. Users can still
attach a local file directly, and `zot attachments fetch` keeps a plain HTTP
resolver path for existing items.

## Data Directory

`pyzot_home()` resolves:

1. `PYZOT_HOME`, if set.
2. A parent directory containing `pyproject.toml`, using `<that-dir>/.pyzot/`.
3. `~/.pyzot`.

The directory is created lazily for config, cache, sessions, and logs.
