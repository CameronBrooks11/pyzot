# `zot` Command Reference

Global options go before the subcommand:

```bash
zot [--db PATH] [--library ID] [--format table|json|csv] [--no-color] <command>
```

Write-related globals:

```bash
zot [--allow-write] [--connector-url URL] [--require-zotero/--no-require-zotero] <command>
```

## Read Commands

```bash
zot stats [summary|types|tags|years|collections]
zot collections list [--flat]
zot collections show <id|name>
zot collections items <id|name> [--recursive] [--type TYPE]
zot items list [--type TYPE] [--collection NAME] [--limit N]
zot items show <id|key>
zot items attachments <id|key>
zot items notes <id|key>
zot items fulltext <id|key> [--offline]
zot search "query" [--field FIELD] [--type TYPE]
zot search --author "Name"
zot search --doi 10.xxxx/yyyy
zot search --tag "tag-name"
zot search --year 2020-2024
zot search "query" --fulltext
zot attachments list [--missing] [--type pdf]
zot attachments path <id|key>
zot attachments open <id|key>
zot export json|csv|bib|markdown --collection "Name" [--output file]
zot export json|csv|bib|markdown --all [--output file]
```

## Config

```bash
zot config path
zot config get write.enabled
zot config set write.enabled true
zot config set write.connector_url http://127.0.0.1:23119
```

Config is stored under `<pyzot-home>/config.toml`. Use `zot config path` to see
the active directory.

## Add Items

Writes require `write.enabled=true`, `--allow-write`, or `PYZOT_ALLOW_WRITE=1`.
Zotero must be running unless `--dry-run` is used.

```bash
zot add status
zot add <input> [--collection NAME] [--tag TEXT] [--dry-run]
zot add batch <file|->
```

`zot add <input>` auto-detects:

| Input | Example |
|---|---|
| DOI | `zot add "10.1038/s41586-020-2649-2"` |
| arXiv ID | `zot add "2401.12345"` |
| PMID | `zot add "31452104"` |
| ISBN | `zot add "9780262033848"` |
| URL | `zot add "https://arxiv.org/abs/1706.03762"` |
| Citation | `zot add "Smith, J. (2020) My Paper. Nature"` |
| Local PDF/EPUB | `zot add ~/Downloads/paper.pdf` |
| RIS/BibTeX/CSL-JSON | `zot add ~/Downloads/refs.bib` |

Thin compatibility subcommands remain available for scripts:

```bash
zot add doi <DOI>
zot add arxiv <ID>
zot add pmid <PMID>
zot add isbn <ISBN>
zot add url <URL>
zot add cite "<citation>"
zot add file <PDF_OR_EPUB>
zot add import <RIS_BIB_OR_CSL_JSON>
```

These subcommands route into the same add pipeline as auto-detect.

## Attachments

```bash
zot attachments add <PARENT_KEY> <FILE_PATH> [--title T] [--source-url URL]
zot attachments fetch <PARENT_KEY> [--methods doi,url,custom]
zot attachments fetch-collection <NAME> [--include-with-pdf] [--methods doi,url,custom]
zot attachments fetch-all [--limit N] [--methods doi,url,custom]
```

`attachments fetch` is HTTP-only. It tries DOI landing pages, item URLs, and
custom resolver URLs, then attaches the first downloaded PDF/EPUB.
