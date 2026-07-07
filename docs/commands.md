# `zot` — Command Reference

All commands share global options that must come **before** the subcommand:

```
zot [--db PATH] [--library ID] [--format table|json|csv] [--no-color] <command>
```

| Global option | Default | Description |
|---|---|---|
| `--db PATH` | auto-detected | Path to `zotero.sqlite` |
| `--library INT` | `1` | Library ID (1 = personal library) |
| `--format` | `table` | Output format for list views |
| `--no-color` | off | Disable Rich colour output |

Auto-detection order: `~/.config/pyzot/config.toml` → `/mnt/c/Users/<user>/Zotero/zotero.sqlite` (WSL) → `~/Zotero/zotero.sqlite`.

---

## `zot stats`

Library statistics dashboard.

```bash
zot stats                  # Overall summary (item count, collections, tags, creators)
zot stats summary          # Same as above
zot stats types            # Items per item type (journalArticle, book, …)
zot stats tags [--top N]   # Top N tags by frequency (default: 20)
zot stats years            # Publication year histogram
zot stats collections [--top N]  # Collections by item count (default: 20)
```

---

## `zot collections`

Browse the collection tree. The `assign` subcommand is the only write operation that touches the database directly (see [Architecture → collection assign](architecture-write.md)).

```bash
zot collections list               # Rich tree view of all collections
zot collections list --flat        # Flat table: ID, Key, Name, Parent, Item count

zot collections show <id|name>     # Details for one collection
zot collections show "Energy Market"

zot collections items <id|name>               # Items in a collection
zot collections items "Energy Market"
zot collections items 42 --recursive          # Include all sub-collections
zot collections items "NLP" --type journalArticle  # Filter by item type

zot collection assign <KEY> <COLLECTION_NAME> # Assign an existing item to a collection
zot collection assign AB3CD7EF "Smart Grid"
zot collection assign AB3CD7EF "[Paper] LV_UG_Cable_Models_DSSE"
```

`<id|name>` accepts a numeric collection ID or an exact/fuzzy collection name.

### `zot collection assign`

Assign an existing item (identified by its 8-character Zotero key) to a collection. The item is not removed from any collection it is currently in — the operation is additive only.

Does not require Zotero to be running. Writes a single row to the `collectionItems` join table; Zotero picks up the change on next UI refresh.

**Synopsis:** `zot collection assign KEY COLLECTION_NAME`

```bash
zot collection assign AB3CD7EF "Smart Grid"
zot collection assign 5UFZMSLU "[Paper] LV_UG_Cable_Models_DSSE"
```

If the item is already in that collection, the command exits with an informational message and no change.

---

## `zot items`

Browse individual items.

```bash
zot items list                             # Paginated item list (default: 50)
zot items list --limit 100                 # Override page size
zot items list --type journalArticle       # Filter by item type
zot items list --collection "Energy Market"

zot items show <id|key>                    # Full detail panel for one item
zot items show 1234
zot items show AABB0001

zot items attachments <id|key>             # Attachments with path + existence check
zot items notes <id|key>                   # Attached notes (HTML stripped)
zot items fulltext <id|key>                # Network-first full-text retrieval
zot items fulltext <id|key> --offline      # Only local Zotero fulltext/metadata
```

`<id|key>` accepts a numeric item ID or the 8-character Zotero key (e.g. `AABB0001`).

---

## `zot search`

Search across fields, authors, tags, DOIs, and years.

```bash
# General field search (all fields if no --field given)
zot search "deep learning"
zot search "bayesian" --field title
zot search "state estimation" --field title --field abstract
zot search "power flow" --type journalArticle

# Author search (queries creators table — first/last name, partial match)
zot search --author "Smith"
zot search --author "Smith" --type conferencePaper

# Exact DOI lookup
zot search --doi 10.1038/example
zot search --doi "https://doi.org/10.1109/TPWRS.2023.1234"

# Tag filter
zot search --tag "machine-learning"

# Year range
zot search --year 2023          # Single year
zot search --year 2020-2024     # Range (inclusive)

# Full-text index (uses Zotero's fulltextWords table — requires Zotero to have indexed files)
zot search "demand response" --fulltext
```

### Search fields reference

Common `--field` values:

| Field name | Description |
|---|---|
| `title` | Item title |
| `abstract` | Abstract / short description |
| `publicationTitle` | Journal or conference name |
| `publisher` | Publisher |
| `place` | Place of publication |
| `date` | Date string (use `--year` for year filtering) |
| `DOI` | Digital Object Identifier |
| `url` | URL |
| `extra` | Extra / notes field |
| `volume` | Volume |
| `issue` | Issue |
| `pages` | Page range |

---

## `zot attachments`

Browse, open, and (since 0.3.0) add or fetch attachment files.

### Read-only browsing

```bash
zot attachments list                        # All attachments with resolved paths
zot attachments list --missing              # Only attachments where the file is absent
zot attachments list --type pdf             # Filter by content type (partial match)

zot attachments path <id|key>               # Print absolute path(s) for an item's attachments
zot attachments open <id|key>               # Open first attachment with system default app
                                            # (uses wslview on WSL, open on macOS, xdg-open on Linux)
```

### Attach a local file to an existing item

```bash
zot attachments add <PARENT_KEY> <FILE_PATH> \
    [--title "Custom title"] [--source-url "https://..."]
```

Inserts an `itemAttachments` row pointing at `~/Zotero/storage/<new-key>/<filename>`
and copies the file there. Idempotent: re-running with the same filename
under the same parent returns the existing attachment key instead of
duplicating.

Requires `write.enabled = true` (or `--allow-write`). Safe to run while
Zotero is open (the writer uses WAL journal mode).

### Find and attach PDFs via the 4-resolver pipeline

This replicates Zotero's *Find Available PDFs* feature for items already
in your library. Resolver order: `doi → url → oa → custom`. For each
resolver: tries direct download first, then page scraping; falls back to
cookied Playwright Chromium for paywalled hosts.

```bash
# One item
zot attachments fetch <PARENT_KEY>

# All items in a collection that don't yet have a PDF
zot attachments fetch-collection "Smart Grid"
zot attachments fetch-collection "Smart Grid" --include-with-pdf   # also re-fetch

# Library-wide (long-running)
zot attachments fetch-all --limit 50
```

Tuning flags (applied to `fetch`, `fetch-collection`, and `fetch-all`):

| Flag | Effect |
|---|---|
| `--methods doi,url,oa,custom` | Restrict to a subset of resolvers (default: all). |
| `--no-browser` | Plain HTTP only; skip Playwright fallback. Useful in CI/scripts. |
| `--no-headed` | Allow headless browser with saved cookies, but never pop a visible window for SSO. Set this in non-interactive environments. |
| `--include-with-pdf` | (bulk variants only) Also process items that already have a PDF. |
| `--limit N` | (`fetch-all` only) Cap the number of candidate items processed. |

**Custom resolvers.** Set `findPDFs.resolvers` to a JSON array (same shape
as Zotero's pref) to add institution-specific resolvers:

```bash
zot config set findPDFs.resolvers '[
  {
    "name": "MyUniProxy",
    "method": "GET",
    "url": "https://proxy.example.edu/doi/{doi}",
    "mode": "html",
    "selector": "a.pdf-link",
    "attribute": "href"
  }
]'
```

---

## `zot export`

Export items to a file or stdout.

```bash
# Export a specific collection
zot export json     --collection "Energy Market" --output energy.json
zot export csv      --collection "Energy Market" --output energy.csv
zot export bib      --item 5UFZMSLU --output article.bib
zot export markdown --collection "Energy Market" --output energy.md

# Export the entire library
zot export json     --all --output library.json
zot export bib      --all --output library.bib
zot export markdown --all --notes --output library.md   # Include notes sections

# Print to stdout (omit --output)
zot export bib --collection "NLP"
```

### Export format details

| Format | Command | Notes |
|---|---|---|
| JSON | `export json` | Full-fidelity Pydantic dump; one object per item |
| CSV | `export csv` | One row per item; creators flattened to `author_1`, `author_2`, … |
| BibTeX | `export bib` | Uses Better BibTeX `citationKey` if present, else auto-generates `LastName2023word` |
| Markdown | `export markdown` | Table of items + optional `## Notes` sections per item |

---

## `zot config`

Manage local CLI configuration values.

```bash
zot config library-auth --library 1 --institution "KU Leuven" --username "alice" --password "token"
zot config library-auth --library 1 --show
```

`library-auth` stores optional per-library institutional/login details used when direct network-location access to full text fails.

### Full-text retrieval strategy (`zot items fulltext`)

The command follows this order (the cache check moved to position 1 in
0.3.0; it's cheap and reliable when a PDF is already attached):

1. **Local Zotero full-text cache** — `~/Zotero/storage/<attachment-key>/.zotero-ft-cache`.
   Plain UTF-8 text produced by Zotero's own indexer.
2. **Direct network access** from DOI/URL (works immediately on institutional networks like campus/VPN).
3. **Config credentials** from `zot config library-auth` (username/password flow).
4. **Playwright-assisted login** (interactive browser fallback).
5. **Metadata fallback** (title/abstract/notes).

To *download and attach* a PDF rather than just read existing text, use
`zot attachments fetch <KEY>` (or one of its bulk variants).

The previous implementation queried a non-existent `fulltextItems.tokenCount`
column and crashed under `--offline`; that bug was fixed in 0.3.0.

---

## Item types reference

Common values for `--type`:

`journalArticle` · `conferencePaper` · `book` · `bookSection` · `thesis` · `report` · `preprint` · `webpage` · `blogPost` · `patent` · `dataset` · `software` · `manuscript`

Run `zot stats types` to see all types present in your library.

---

## `zot config`

Read and write pyzot configuration. Config is stored in `<pyzot-home>/config.toml`.

### `zot config path`

Print the `<pyzot-home>` directory path. Use this to find config / credentials / cache without making OS-specific assumptions.

```bash
zot config path
# /home/user/.pyzot
```

### `zot config get`

Print the value of a config key. Keys use `section.key` dotted form.

```
zot config get <key>
```

```bash
zot config get write.enabled
zot config get write.connector_url
zot config get unpaywall.email
```

Exits with code 1 if the key is not set.

### `zot config set`

Set a config key and persist it to `<pyzot-home>/config.toml`.

```
zot config set <key> <value>
```

```bash
zot config set write.enabled true
zot config set write.connector_url http://127.0.0.1:23119
zot config set unpaywall.email user@example.com
```

Supported keys include any `section.key` pair matching the `config.toml` schema (see `PLAN_WRITE.md §7.2`).

---

## `zot add`

Add items to your Zotero library via the local connector HTTP server. **Requires Zotero to be running.** Write capability must be enabled first:

```bash
zot config set write.enabled true
```

All subcommands support `--dry-run` (print payload without sending), `-v` / `--verbose` (echo HTTP requests), and `--non-interactive` (suppress prompts).

**Auto-attach (0.3.0+):** All identifier-based add commands run the
*find-file pipeline* (see `zot attachments fetch`) after the metadata
save and attach an open-access or saved-cookie PDF when one is found.
This is controlled by the `autoattach.enabled` config key (default
`true`). Use `--no-pdf` to opt out for a single call, or `--with-pdf` to
force the pipeline on when the global default is off.

### `zot add status`

Check whether Zotero is running. Prints reachability, selected collection, and connector URL.

**Synopsis:** `zot add status`

```bash
zot add status
# Zotero reachable at http://127.0.0.1:23119
# Selected collection: My Library
# write.enabled: true
```

---

### `zot add doi`

Add an item by DOI. Resolves via Crossref.

**Synopsis:** `zot add doi [OPTIONS] DOI_VALUE`

| Option | Description |
|---|---|
| `-c, --collection NAME` | Collection name to add the item to |
| `-t, --tag TEXT` | Tag to apply (repeatable) |
| `--dry-run` | Print the JSON payload without sending |
| `--on-duplicate [report\|skip\|force-add]` | Duplicate behaviour (default: report) |
| `-v, --verbose` | Print HTTP request/response info |
| `--with-pdf / --no-pdf` | Run the find-file pipeline (default: enabled via `autoattach.enabled`). Resolvers: `doi → url → oa → custom`; falls back to cookied headless browser. |
| `--non-interactive` | Suppress prompts; skip PDF silently if unavailable |

**Example:**
```bash
zot add doi 10.1038/s41586-020-2649-2 --collection Inbox --tag to-read
zot add doi 10.1109/X --with-pdf --dry-run
```

DOI_VALUE may be a bare DOI, `doi:` prefixed, or a full `https://doi.org/…` URL.

**Duplicate behaviour with `--collection`:** If the DOI already exists in the library (`--on-duplicate=report`, the default), pyzot prints the existing key and title, then assigns the item to the requested collection if it is not already a member. Existing collection memberships are never removed.

---

### `zot add arxiv`

Add an item by arXiv ID. Resolves via the arXiv Atom feed.

**Synopsis:** `zot add arxiv [OPTIONS] ARXIV_ID`

Options: same as `doi` (including `--with-pdf`).

**Example:**
```bash
zot add arxiv 2401.12345 --collection Preprints
zot add arxiv arxiv:2401.12345v2 --with-pdf
```

ARXIV_ID accepts modern `YYMM.NNNNN`, legacy `archive/NNNNNNN`, with or without `arxiv:` prefix or version suffix.

---

### `zot add pmid`

Add an item by PubMed ID. Resolves via NCBI eutils.

**Synopsis:** `zot add pmid [OPTIONS] PMID_VALUE`

Options: same as `doi` (including `--with-pdf`).

**Example:**
```bash
zot add pmid 31452104 --collection Biology
```

---

### `zot add isbn`

Add an item by ISBN (10 or 13 digit). Resolves via OpenLibrary with Google Books fallback.

**Synopsis:** `zot add isbn [OPTIONS] ISBN_VALUE`

Options: same as `doi` (excluding `--with-pdf`).

**Example:**
```bash
zot add isbn 978-0-262-03384-8 --collection Books
zot add isbn 0262033844
```

ISBN_VALUE may include hyphens or spaces.

---

### `zot add url`

Add an item from a URL. Auto-routes based on URL pattern.

**Synopsis:** `zot add url [OPTIONS] URL_VALUE`

| Route | How it's handled |
|---|---|
| `arxiv.org/abs/…` | arXiv ID extracted → arXiv resolver |
| `pubmed.ncbi.nlm.nih.gov/…` | PMID extracted → PubMed resolver |
| `ieeexplore.ieee.org/document/…` | DOI extracted → Crossref; fallback Playwright snapshot |
| `sciencedirect.com/science/article/pii/…` | PII extracted → Crossref; fallback Playwright snapshot |
| `doi.org/…` | DOI extracted → Crossref |
| Any other URL | `saveSnapshot` — Zotero translators run on fetched HTML |

Options: same as `doi` (including `--with-pdf`).

**Example:**
```bash
zot add url https://ieeexplore.ieee.org/document/9876543
zot add url https://www.sciencedirect.com/science/article/pii/S2352467725000102
zot add url https://arxiv.org/abs/2401.12345
```

---

### `zot add cite`

Add an item from a free-text citation string. Runs the Crossref bibliographic search pipeline with OpenAlex and Semantic Scholar fallbacks.

**Synopsis:** `zot add cite [OPTIONS] [CITATION_TEXT]`

| Option | Description |
|---|---|
| `-f, --file PATH` | File with one citation per line |
| `--threshold INT` | Minimum Crossref score for auto-accept (default: 50) |
| `--gap FLOAT` | Minimum top/second score ratio for auto-accept (default: 1.4) |
| `-c, --collection NAME` | Collection name |
| `-t, --tag TEXT` | Tag (repeatable) |
| `--dry-run` | Print payload without sending |
| `--with-pdf / --no-pdf` | Attach OA PDF |
| `--non-interactive` | Never prompt; error on ambiguous citations |

**Example:**
```bash
zot add cite "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: Evaluating assumptions for low-voltage network modelling in the DER era."
zot add cite --file refs.txt --collection Inbox --tag to-read
```

---

### `zot add file`

Upload a local PDF or EPUB as a standalone attachment. Zotero automatically attempts to recognise the parent reference via `RecognizeDocument`.

**Synopsis:** `zot add file [OPTIONS] PATH`

| Option | Description |
|---|---|
| `-c, --collection NAME` | Collection name |
| `-t, --tag TEXT` | Tag (repeatable) |
| `--dry-run` | Print upload metadata without sending |
| `--wait-recognize N` | Seconds to poll for recognised parent (default: 30; 0 to skip) |
| `-v, --verbose` | Print HTTP info |

**Example:**
```bash
zot add file ~/Downloads/paper.pdf --collection Inbox --tag ml
zot add file ~/Downloads/paper.pdf --wait-recognize 60
```

---

### `zot add import`

Import a bibliography file. Sends raw bytes to Zotero's `/connector/import` endpoint; format is auto-detected.

**Synopsis:** `zot add import [OPTIONS] PATH`

| Format | Extension | Content-Type |
|---|---|---|
| RIS | `.ris` | `application/x-research-info-systems` |
| BibTeX | `.bib`, `.bibtex` | `application/x-bibtex` |
| CSL-JSON | `.json` | `application/vnd.citationstyles.csl+json` |

| Option | Description |
|---|---|
| `-c, --collection NAME` | Collection name |
| `-t, --tag TEXT` | Tag (repeatable) |
| `--dry-run` | Print first 200 bytes and content-type without importing |
| `-v, --verbose` | Print HTTP info |

**Example:**
```bash
zot add import refs.bib --collection "Imports/2026-05"
zot add import refs.ris --tag imported --dry-run
```

---

### `zot add batch`

Process a file of inputs (one per line). Each line is passed through the same auto-detect dispatcher as `zot add "<anything>"`. Prints a summary table on completion; exits 1 if any line failed.

**Synopsis:** `zot add batch [OPTIONS] FILE`

FILE may be `-` to read from stdin. Lines starting with `#` or blank are skipped.

| Option | Description |
|---|---|
| `-c, --collection NAME` | Collection applied to all items |
| `-t, --tag TEXT` | Tag applied to all items (repeatable) |
| `--dry-run` | Resolve and print without sending to connector |
| `--on-duplicate [report\|skip\|force-add]` | Duplicate behaviour (default: report) |
| `-v, --verbose` | Print HTTP info |
| `--non-interactive` | Never prompt; fail/skip ambiguous citations |
| `--jobs N` | Reserved for parallel resolver lookups (stub; currently no-op) |

**Example:**
```bash
zot add batch papers.txt --collection "Smart Grid"
cat dois.txt | zot add batch - --tag imported
```

---

### `zot add login`

Manage authentication for PDF retrieval services.

**Synopsis:** `zot add login [OPTIONS]`

| Option | Description |
|---|---|
| `-s, --service [unpaywall\|ieee\|sciencedirect]` | Service to authenticate with |
| `--reset` | Clear stored credentials/cookies for the service |
| `--install-browser` | Install Chromium via `playwright install chromium` |

**Service behaviour:**

| Service | Mechanism | What's stored |
|---|---|---|
| `unpaywall` | Prompts for email address | `credentials.json` + sets `unpaywall.enabled = true` |
| `ieee` | Opens headed Chromium; user signs in via institutional SSO | Playwright profile at `<pyzot-home>/cookies/ieee/` |
| `sciencedirect` | Opens headed Chromium; user signs in via Elsevier SSO | Playwright profile at `<pyzot-home>/cookies/sciencedirect/` |

**Example:**
```bash
zot add login --service unpaywall         # save email; opt-in to Unpaywall
zot add login --service ieee              # browser SSO for IEEE Xplore
zot add login --service sciencedirect     # browser SSO for ScienceDirect
zot add login --service ieee --reset      # clear IEEE cookies
zot add login --install-browser           # install Chromium (first time)
```

After `zot add login --service ieee` you can retrieve paywalled PDFs:
```bash
zot add doi 10.1109/TPWRS.2023.1234567 --with-pdf
```
