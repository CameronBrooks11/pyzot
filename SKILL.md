---
name: pyzot
description: CLI for querying, browsing, exporting, and adding items to a local Zotero library (SQLite). Search by title, author, tag, DOI, or year; browse collections; resolve PDF attachment paths; export to JSON/CSV/BibTeX/Markdown; add items via DOI, arXiv, PMID, ISBN, IEEE/ScienceDirect URL, free-text citation, local PDF, or bibliography file. Auto-attach PDFs to new items and find-and-attach PDFs for existing items via the same 4-resolver pipeline (doi → url → Zotero OA endpoint → custom) that Zotero's "Find Available PDFs" feature uses. Use when asked to find papers, list references, get PDF paths, export a Zotero collection, add new items, or attach full-text PDFs to items already in the library.
---

# pyzot (`zot`)

A Python CLI for your local Zotero library. Queries the SQLite database directly for reads — no Zotero app or API key needed for read-only commands. **Default is strictly read-only.** Write capabilities (adding items) are opt-in and route through Zotero's own connector HTTP server — `zotero.sqlite` is never modified directly.

## Installation

```bash
# Read-only (default)
pip install pyzot

# Adds write API client — required for any zot add … command
pip install "pyzot[write]"

# Adds Playwright for paywalled-PDF retrieval via browser SSO
pip install "pyzot[browser]"

# Everything
pip install "pyzot[all]"
```

---

## For agents using this skill

> **Before invoking any `zot add` or `zot attachments add|fetch*` command, ensure write capability is enabled.**
> Run `zot config set write.enabled true` once (it persists), or pass `--allow-write` on each call. If unsure, run `zot config get write.enabled` first.
>
> The default install (`pip install pyzot`) is read-only. For writes you also need: `pip install "pyzot[write]"`. For paywalled-PDF retrieval (Playwright SSO): `pip install "pyzot[browser]"`.
>
> Zotero must be running for any `zot add …` to succeed. The `zot attachments add|fetch*` commands write directly to `zotero.sqlite` and tolerate a running Zotero (WAL mode), but Zotero must be running to *see* the new attachments without restart.
>
> **Auto-attach default (0.3.0+):** `zot add` runs the find-file pipeline automatically — the new item gets a PDF attached when one is available. To opt out of PDF attachment for one call use `--no-pdf`; to disable globally use `zot config set autoattach.enabled false`.
>
> **IMPORTANT — Agent protocol when Zotero is unreachable:**
> If any `zot add` command fails with a connection error (e.g. "Connection refused", "Zotero not running", "connector unreachable") or `zot add status` reports Zotero as offline:
> 1. **Stop immediately** — do not retry the command.
> 2. **Halt and ask the user** to open Zotero, using a message like:
>    > "The Zotero desktop application is not running. Please open Zotero and then reply here so I can add the reference."
> 3. Wait for the user's confirmation before retrying.
> 4. After confirmation, run `zot add status` to verify connectivity, then retry the original command.

### Configuration directory

All pyzot config, credentials, cache, and logs live under `<pyzot-home>`. Run `zot config path` to find the exact directory — do not make OS-specific assumptions.

`<pyzot-home>` is resolved in order:
1. `PYZOT_HOME` environment variable (if set and writable).
2. A `.pyzot/` sibling to the nearest `SKILL.md` found by walking up from the pyzot package directory (portable skill checkout).
3. `~/.pyzot` — cross-platform fallback (same path on Linux, macOS, Windows).

Layout:
```
<pyzot-home>/
  config.toml         # [write], [unpaywall], [browser] sections
  credentials.json    # Unpaywall email, service login markers (mode 0600)
  cookies/<service>/  # Playwright persistent profiles
  cache/sessions.jsonl
  logs/zot.log        # rotating, 1 MB × 3 backups
```

To inspect or modify config without OS-specific file path assumptions:
```bash
zot config path                         # print <pyzot-home>
zot config get write.enabled            # read a value
zot config set write.enabled true       # write a value
```

---

## Database path

The database is auto-detected at `~/Zotero/zotero.sqlite`. Override with `--db`:

```bash
zot --db ~/Zotero/zotero.sqlite stats
```

Or set permanently in `<pyzot-home>/config.toml`:
```toml
[database]
path = "~/Zotero/zotero.sqlite"
```

---

## Quick orientation (read-only)

```bash
zot stats              # Library summary
zot stats types        # Break down by item type
zot stats years        # Publication year histogram
zot collections list   # Full collection tree
```

---

## Core workflow: search → inspect → get attachment paths

### Step 1 — Search by title keyword

```bash
zot search "bayesian" --field title
```

### Step 2 — Search by author name

```bash
zot search --author "Numair"
```

### Step 3 — Inspect a single item

```bash
zot items show 5UFZMSLU
```

### Step 4 — Get the PDF path

```bash
zot attachments path 5UFZMSLU
```

### Step 5 — Export a collection

```bash
zot export bib --collection "Energy Market" --output refs.bib
zot export json --all --output library.json
```

---

## Adding items to the library

> **Zotero must be running** for all `zot add …` commands.

### Supported sources

| Source | Example |
|---|---|
| DOI | `zot add doi 10.1109/TPWRS.2023.1234567` |
| arXiv ID | `zot add arxiv 2401.12345` |
| PubMed ID (PMID) | `zot add pmid 31452104` |
| ISBN | `zot add isbn 978-0-262-03384-8` |
| IEEE Xplore URL | `zot add url https://ieeexplore.ieee.org/document/9876543` |
| ScienceDirect URL | `zot add url https://www.sciencedirect.com/science/article/pii/S…` |
| Generic URL | `zot add url https://example.org/paper.html` |
| Free-text citation | `zot add cite "Zhang, J. et al. (2025) Beyond simplifications…"` |
| Local PDF / EPUB | `zot add file ~/Downloads/paper.pdf` |
| RIS / BibTeX / CSL-JSON import | `zot add import refs.bib` |

IEEE Xplore and ScienceDirect URLs are resolved to DOIs via Crossref — no browser needed for metadata. A browser is only required to retrieve paywalled PDFs.

### Enable writes (one-time)

```bash
zot config set write.enabled true
```

### Smart auto-detect

The bare `zot add "<anything>"` form figures out the input type automatically:

```bash
zot add "10.1109/TPWRS.2023.1234567"        # detected as DOI
zot add "2401.12345"                        # detected as arXiv
zot add "https://ieeexplore.ieee.org/document/9876543"  # IEEE URL
zot add "Zhang, J. et al. (2025) Beyond…"  # detected as citation
zot add "/home/me/Downloads/paper.pdf"      # detected as local file
```

### Explicit subcommands (preferred for scripts)

```bash
zot add doi    10.1109/TPWRS.2023.1234567   --collection "Smart Grid" --tag to-read
zot add arxiv  2401.12345                   --collection Preprints
zot add pmid   31452104
zot add isbn   978-0-262-03384-8            --collection Books
zot add url    https://ieeexplore.ieee.org/document/9876543
zot add cite   "Zhang, J. et al. (2025) Beyond simplifications…"
zot add file   ~/Downloads/paper.pdf        --collection Inbox --tag ml
zot add import refs.bib                     --collection "Imports/2026-05"
```

### Batch add

```bash
# papers.txt: one input per line (DOI / arXiv / URL / citation / file path)
# Lines starting with # or blank are skipped
zot add batch papers.txt --collection "Smart Grid"
cat dois.txt | zot add batch - --tag imported
```

### Check Zotero status

```bash
zot add status   # prints reachability, selected collection, connector URL
```

### Automatic PDF attachment (default since 0.3.0)

Every `zot add …` runs the **find-file pipeline** by default after the
metadata save — a Python port of Zotero's *Find Available PDFs* feature.
Resolver chain (matches Zotero `getFileResolvers`):

1. `doi`    → `https://doi.org/{doi}` → follow redirects, scrape the landing page for the PDF link
2. `url`    → item's URL field → same page-scraping logic
3. `oa`     → `POST https://services.zotero.org/oa/search` (Zotero's Unpaywall mirror) → direct PDF URL or page URL
4. `custom` → user-defined resolvers (config `findPDFs.resolvers`)

For paywalled hosts that block plain HTTP, the pipeline transparently
escalates to a **headless Playwright Chromium** reusing the cookies saved
by `zot add login --service ieee|sciencedirect`. If even the cookied
headless attempt fails the browser opens visibly so the user can complete
SSO / captcha **once** — subsequent items reuse the new session silently.

Per-call overrides:

```bash
zot add doi 10.1109/X --no-pdf          # opt out for one command
zot add doi 10.1109/X --with-pdf        # force on if the global default is off
```

Global toggle:

```bash
zot config set autoattach.enabled false  # disable for all `zot add` calls
zot config set autoattach.enabled true   # restore default
```

### Browser SSO setup (paywalled PDFs, optional)

```bash
zot add login --service ieee             # opens headed Chromium; sign in once
zot add login --service sciencedirect    # ditto
zot add login --install-browser          # first-time Chromium install for Playwright
```

After login, future `zot add` and `zot attachments fetch …` calls reuse
the saved profile silently for that publisher.

### Find/attach PDFs for items already in the library

For items added before 0.3.0 (or imported without `--with-pdf`):

```bash
zot attachments add  AB3CD7EF /path/to/paper.pdf      # attach a local file directly
zot attachments fetch AB3CD7EF                        # run the 4-resolver pipeline for one item
zot attachments fetch-collection "Smart Grid"         # bulk for one collection
zot attachments fetch-all --limit 50                  # bulk for the whole library
```

`fetch*` skips items that already have a PDF attached (override with
`--include-with-pdf`). All four commands write directly into
`zotero.sqlite` and copy the file into `~/Zotero/storage/<key>/<filename>`,
then mark the parent unsynced so Zotero's sync engine re-uploads it. This
is a SECOND explicit exception to the "no direct SQLite writes" rule
(alongside `zot collection assign`).

Resolver subset and browser fallback controls:

```bash
zot attachments fetch ABCD1234 --methods doi,oa      # only those two resolvers
zot attachments fetch ABCD1234 --no-browser          # plain HTTP only (no Playwright)
zot attachments fetch ABCD1234 --no-headed           # cookied headless only
```

### Duplicate handling

When a duplicate identifier is detected, pyzot reports the existing item key and title, then exits 0. If `--collection NAME` was also passed, the item is **assigned to that collection** if it is not already a member (additive — existing collection memberships are never removed). This is the default `--on-duplicate=report` behaviour.

To assign an already-known item to a collection without going through `zot add`:

```bash
zot collection assign AB3CD7EF "Smart Grid"
zot collection assign AB3CD7EF "[Paper] LV_UG_Cable_Models_DSSE"
```

---

## All commands at a glance

```bash
# Read-only — no Zotero app required
zot stats [types | tags | years | collections]
zot collections list [--flat]
zot collections show <id|name>
zot collections items <id|name> [--recursive]
zot collection assign <KEY> <COLLECTION_NAME>
zot items list [--type TYPE] [--collection NAME] [--limit N]
zot items show <id|key>
zot items attachments <id|key>
zot items notes <id|key>
zot items fulltext <id|key> [--offline] [--playwright-auth/--no-playwright-auth]

# Search
zot search "query" [--field title] [--field abstract] [--type TYPE]
zot search --author "Name"
zot search --doi 10.xxxx/yyyy
zot search --tag "tag-name"
zot search --year 2020-2024
zot search "query" --fulltext

# Attachments (read-only)
zot attachments list [--missing] [--type pdf]
zot attachments path <id|key>
zot attachments open <id|key>

# Attachments (write — requires write.enabled=true)
zot attachments add <KEY> <FILE> [--title T] [--source-url URL]
zot attachments fetch <KEY> [--methods doi,url,oa,custom] [--no-browser] [--no-headed]
zot attachments fetch-collection <NAME> [--include-with-pdf] [--methods ...]
zot attachments fetch-all [--limit N] [--methods ...]

zot export json|csv|bib|markdown --collection "Name" [--output file]
zot export json|csv|bib|markdown --all [--output file]
zot export markdown --all --notes --output report.md

# Config (read-only-safe)
zot config path
zot config get <key>
zot config set <key> <value>
zot config library-auth --library 1 --institution "KU Leuven" --username "alice" --password "token"
zot config library-auth --library 1 --show

# Write — requires write.enabled=true and Zotero running
# (--with-pdf is the default since 0.3.0; use --no-pdf to opt out for one call,
#  or `zot config set autoattach.enabled false` to disable globally.)
zot add status
zot add doi <DOI> [--collection NAME] [--tag TAG] [--dry-run] [--with-pdf/--no-pdf]
zot add arxiv <ID> [--collection NAME] [--tag TAG] [--with-pdf/--no-pdf]
zot add pmid <ID> [--collection NAME] [--tag TAG]
zot add isbn <ISBN> [--collection NAME] [--tag TAG]
zot add url <URL> [--collection NAME] [--with-pdf/--no-pdf]
zot add cite "<text>" [--file PATH] [--collection NAME]
zot add file <path> [--collection NAME] [--wait-recognize N]
zot add import <path> [--collection NAME]
zot add batch <file> [--collection NAME] [--jobs N]
zot add login [--service unpaywall|ieee|sciencedirect] [--reset] [--install-browser]
```

Full reference: [`docs/commands.md`](docs/commands.md)

---

## Zotero-not-running failure protocol (MANDATORY for agents)

> **When any `zot add …` command fails because the Zotero connector is unreachable (connection
> refused, server not reachable, timeout, or `zot add status` shows Zotero is not running),
> you MUST follow this protocol exactly:**

1. **STOP immediately.** Do not retry the `zot add` command.
2. **Tell the user** that Zotero needs to be open and ask them to start it. Use a message like:
   > "The Zotero desktop application needs to be running to add references. Please open Zotero,
   > then let me know when it's ready and I'll continue adding the reference."
3. **Wait for explicit user confirmation** (e.g. "open", "ready", "done") before retrying.
4. After confirmation, optionally run `zot add status` to verify connectivity, then retry the
   original `zot add` command.

You can proactively check before any add operation with:
```bash
zot add status
```
If it shows unreachable, trigger the protocol above **before** attempting the add.

**Do NOT:** silently retry, skip adding the reference, or proceed without user confirmation.

---

## Safety guarantees

- Database opened in **strict read-only URI mode** (`sqlite3://…?mode=ro`) for all read commands — impossible to corrupt the library via direct SQL.
- WAL journal detection: warns if Zotero is currently running (changes may not be visible yet).
- Network calls are optional and used only by `zot items fulltext` and the find-file pipeline.
- Item *data* writes go through Zotero's own connector HTTP server. Default is read-only; writes require explicit opt-in (`zot config set write.enabled true`).
- **Two documented exceptions** that write directly to `zotero.sqlite` (using WAL mode so they coexist safely with a running Zotero):
  1. `zot collection assign` (and `zot add … --collection` on a duplicate) writes one row into the `collectionItems` join table. No sync-critical metadata involved.
  2. `zot attachments add | fetch | fetch-collection | fetch-all` insert into `items` + `itemAttachments` + `itemData`, copy the PDF to `~/Zotero/storage/<key>/<filename>`, and mark the parent unsynced so the sync engine re-uploads it. This is the only path Zotero exposes for attaching files to items that weren't created in the current connector session.
- No Zotero API key required.
- All credentials stored at rest in `<pyzot-home>/credentials.json` (mode 0600 on POSIX).

### Full-text retrieval strategy

`zot items fulltext` uses this order (the on-disk cache check moved to position 1 in 0.3.0):

1. **Local Zotero full-text cache** — `~/Zotero/storage/<attachment-key>/.zotero-ft-cache`, the same plain-text file Zotero's own indexer writes. Cheapest and most reliable when a PDF is already attached.
2. direct network access (institution/network location),
3. config credentials (`zot config library-auth`),
4. Playwright interactive authentication fallback,
5. metadata fallback (title/abstract/notes).

For attaching PDFs (rather than just reading them), use the find-file pipeline — see *Automatic PDF attachment* and *Find/attach PDFs for items already in the library* above.

## Running tests

```bash
python3 -m pytest tests/ -q          # unit + integration tests (in-memory DB fixture)
python3 -m pytest tests/e2e -m e2e   # End-to-end against real zotero.sqlite (slow)
```
