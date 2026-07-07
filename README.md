# pyzot (`zot`)

A "crazy" good command-line interface for your local [Zotero](https://www.zotero.org/) library. Queries `zotero.sqlite` directly — no Zotero app running and no API key required for reads. **Default: strictly read-only.** Write capabilities are opt-in and route through Zotero's own connector HTTP server — `zotero.sqlite` is **never** modified directly.

> **Provenance.** `pyzot` is an MIT-licensed source import of [`zotcli`](https://pypi.org/project/zotcli/) 0.3.0, published to PyPI by MohamedNumair. No upstream Git repository was discoverable, so this is a source import rather than a fork. The package/import name was changed from `zotcli` to `pyzot`; the console command remains `zot`. Original copyright is retained — see [`LICENSE`](LICENSE). Unrelated to `jbaiter/zotero-cli`, which merely shares the command name.

---

## Installation

```bash
# Read-only (default)
pip install pyzot

# Adds the write API client (httpx) — required for any zot add … command
pip install "pyzot[write]"

# Adds Playwright for paywalled-PDF retrieval via browser SSO
pip install "pyzot[browser]"

# Everything
pip install "pyzot[all]"
```

Verify:
```bash
zot --help
```

The database at `~/Zotero/zotero.sqlite` is auto-detected on WSL. Override anytime with `--db PATH`.

Depending on the operating system the Zotero folder can be in different locations. By default, pyzot looks for the database at `~/Zotero/zotero.sqlite`, which works for most setups. For Windows users, the Zotero folder is typically located in `C:\Users\<YourUsername>\Zotero`. For macOS users, it is usually found in `~/Zotero`. If you have a custom setup or want to specify a different path, you can use the `--db` option to point pyzot to the correct location of your `zotero.sqlite` file.

---

## Repository layout

```
pyzot/
├── PLAN.md                          # Original design document
├── PLAN_WRITE.md                    # Write-capability design document
├── SKILL.md                         # Agent skill descriptor
├── pyproject.toml                   # Package metadata and dependencies
├── docs/
│   ├── commands.md                  # Full command reference
│   └── architecture-write.md       # Write-path architecture overview
├── src/
│   └── pyzot/
│       ├── __init__.py
│       ├── __main__.py              # python -m pyzot entrypoint
│       ├── db.py                    # Read-only SQLite connection + auto-discovery
│       ├── config.py                # TOML config + [write]/[unpaywall]/[browser] sections
│       ├── paths.py                 # Cross-platform self-contained path resolution
│       ├── models.py                # Pydantic v2 models: Item, Collection, Creator, Attachment, Note
│       ├── queries/
│       │   ├── items.py             # Core item fetch
│       │   ├── collections.py       # Collection tree queries
│       │   ├── attachments.py       # Attachment path resolution helpers
│       │   ├── tags.py              # Tag queries
│       │   └── search.py            # Field search, author search, DOI, year, fulltext
│       ├── write/                   # Write-path package (requires pyzot[write])
│       │   ├── connector_client.py  # httpx client for /connector/*
│       │   ├── preflight.py         # Zotero liveness check
│       │   ├── session.py           # Session lifecycle + updateSession
│       │   ├── csl_json.py          # CSL-JSON ↔ connector item shape
│       │   ├── identifiers.py       # detect_kind: DOI / arXiv / PMID / ISBN / URL / citation
│       │   ├── dedup.py             # Read-only duplicate check against DB
│       │   ├── citation_pipeline.py # Free-text citation → DOI pipeline
│       │   ├── pdf.py               # MIME sniff + streaming upload
│       │   ├── browser.py           # Playwright headed window (lazy import; requires pyzot[browser])
│       │   ├── credentials.py       # File-based credential store (mode 0600)
│       │   └── resolvers/
│       │       ├── crossref.py      # DOI → CSL-JSON; bibliographic search
│       │       ├── arxiv.py         # arXiv ID → CSL-JSON
│       │       ├── pubmed.py        # PMID → CSL-JSON
│       │       ├── openlibrary.py   # ISBN → CSL-JSON
│       │       ├── openalex.py      # Citation/title fallback
│       │       ├── semantic_scholar.py  # Second fallback (rate-limited)
│       │       ├── unpaywall.py     # DOI → OA PDF URL (opt-in)
│       │       ├── ieee.py          # URL → DOI extraction helpers
│       │       └── sciencedirect.py # URL/PII → DOI extraction helpers
│       ├── export/
│       │   ├── json_.py             # Full-fidelity JSON dump
│       │   ├── csv_.py              # Flat CSV (one row per item)
│       │   ├── bibtex.py            # BibTeX with auto citation keys
│       │   └── markdown.py          # Markdown table report
│       └── cli/
│           ├── main.py              # Root Click group + global options
│           ├── render.py            # Shared Rich helpers (tables, panels, trees)
│           ├── add.py               # `zot add` group + auto-detect dispatcher
│           ├── config_cmd.py        # `zot config` group
│           ├── collections.py       # `zot collections` subcommands
│           ├── items.py             # `zot items` subcommands
│           ├── attachments.py       # `zot attachments` subcommands
│           ├── search.py            # `zot search`
│           ├── stats.py             # `zot stats` subcommands
│           └── export.py            # `zot export` subcommands
└── tests/
    ├── conftest.py                  # In-memory SQLite fixture with seeded test data
    ├── unit/                        # Unit tests (no network, no Zotero)
    ├── integration/                 # Integration tests (mocked connector + resolvers)
    └── e2e/                         # End-to-end (opt-in; requires real Zotero)
```

---

## Architecture

```
CLI layer  (cli/)
    ↓  Click commands call query functions
Query layer  (queries/)
    ↓  Batch SQL via sqlite3.Row
Database layer  (db.py)       ← read-only URI: file:zotero.sqlite?mode=ro
    ↓
zotero.sqlite

Write path (opt-in):
CLI layer  (cli/add.py)
    ↓  resolve identifiers via external APIs
Resolver pipeline  (write/resolvers/)
    ↓  CSL-JSON
Connector client  (write/connector_client.py)
    ↓  loopback HTTP
Zotero desktop app  →  zotero.sqlite + storage/
```

See [`docs/architecture-write.md`](docs/architecture-write.md) for the full write-path design.

---

## Global options

These go **before** the subcommand:

```
zot [--db PATH] [--library ID] [--format table|json|csv] [--no-color] <command>

Write-related globals (only relevant when write.enabled=true):
zot [--allow-write] [--connector-url URL] [--require-zotero/--no-require-zotero] <command>
```

---

## Examples with output

### `zot stats` — library overview

```bash
zot stats
```
```
   Library Summary
┌─────────────┬──────┐
│ Items       │ 3771 │
│ Collections │  200 │
│ Tags        │ 3201 │
│ Creators    │ 3959 │
└─────────────┴──────┘
       Items by Type
┏━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Type             ┃ Count ┃
┡━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ annotation       │  2188 │
│ journalArticle   │   864 │
│ conferencePaper  │   234 │
│ webpage          │   179 │
│ book             │    77 │
│ report           │    75 │
│ preprint         │    43 │
│ thesis           │    32 │
│ bookSection      │    25 │
└──────────────────┴───────┘
```

```bash
zot stats years
```
```
              Publications by Year
┏━━━━━━┳━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Year ┃ Count ┃ Bar                            ┃
┡━━━━━━╇━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ 2026 │    10 │                                │
│ 2025 │    36 │ ██                             │
│ 2024 │   110 │ █████████                      │
│ 2023 │   361 │ ██████████████████████████████ │
│ 2022 │   144 │ ███████████                    │
│ 2021 │   120 │ █████████                      │
│ 2020 │   101 │ ████████                       │
│ 2019 │    96 │ ███████                        │
└──────┴───────┴────────────────────────────────┘
```

```bash
zot stats tags --top 10
```
```
           Top 10 Tags
┏━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━┓
┃ Tag                   ┃ Items ┃
┡━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━┩
│ Topology              │    89 │
│ Voltage measurement   │    77 │
│ Network topology      │    75 │
│ State estimation      │    65 │
│ Distribution networks │    53 │
│ thesis                │    50 │
│ Smart meters          │    48 │
│ notion                │    47 │
│ Real-time systems     │    46 │
│ _EndnoteXML import    │    38 │
└───────────────────────┴───────┘
```

---

### `zot collections` — browse the library tree

```bash
zot collections list
```
```
Collections
├── 00_Reading Tracker (2)
│   ├── Read (12)
│   ├── Reading (15)
│   └── To Read (31)
├── Energy Management (6)
│   ├── AI based Energy Management (2)
│   ├── Demand Response (14)
│   │   └── Home Energy Management System (3)
│   ├── Energy Market (75)
│   ├── Energy Storage (4)
│   ├── Felixibility (8)
│   └── Power Flow (16)
├── PhD Research (...)
│   ├── Distribution Systems (...)
│   └── State Estimation (...)
└── ...
```

```bash
zot collections items "Energy Market"
```
```
                            Energy Market (73 items)
┏━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━┓
┃  # ┃ Key       ┃ Type               ┃ Title                               ┃ Authors      ┃ Year   ┃
┡━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━┩
│  1 │ RBUU6AM2  │ journalArticle     │ New coordination framework for      │ Hussain      │ 2023   │
│    │           │                    │ smart home peer-to-peer trading…    │ et al.       │        │
│  2 │ 8DE2V7ZZ  │ journalArticle     │ Integrating Distributed Flexibility │ Tsaousoglou  │ 2023   │
│    │           │                    │ into TSO-DSO Coordinated Markets…   │ et al.       │        │
│  3 │ GKG9XUBE  │ thesis             │ Adoption of Blockchain in European  │ Meyer        │ 2023   │
│    │           │                    │ Electricity Markets                 │              │        │
└────┴───────────┴────────────────────┴─────────────────────────────────────┴──────────────┴────────┘
```

Include all sub-collections recursively:
```bash
zot collections items "Energy Management" --recursive
```

---

### `zot items` — inspect individual items

```bash
zot items list --limit 5
```
```
┏━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━┳━━━━━━━━┓
┃  # ┃ Key       ┃ Type               ┃ Title                                       ┃ Authors     ┃ Year   ┃
┡━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━╇━━━━━━━━┩
│  1 │ L54VEEWV  │ journalArticle     │ Three-phase feeder parameter estimation…    │ Yang et al. │ 2026   │
│  2 │ B8CNX4LI  │ journalArticle     │ Coordinated State Estimation of Power…      │ Sharma      │ 2025   │
│  3 │ MXYF8V3J  │ journalArticle     │ Towards Digital Twin of Distribution…       │ Idlbi       │ 2026   │
│  4 │ YN89DKH4  │ book               │ 41st European Photovoltaic Solar Energy…    │             │ 2024   │
│  5 │ 5UFZMSLU  │ journalArticle     │ UNLOCKING DATA CENTRE HOSTING CAPACITY…     │ Numair      │ 2026   │
└────┴───────────┴────────────────────┴─────────────────────────────────────────────┴─────────────┴────────┘
```

```bash
zot items show 5UFZMSLU
```
```
╭────────────────── journalArticle #6439  5UFZMSLU ──────────────────╮
│ Title    UNLOCKING DATA CENTRE HOSTING CAPACITY AND FLEXIBILITY     │
│          THROUGH DYNAMIC CABLE RATING                               │
│ Authors  Numair, Mohamed; ElKholy, Ahmed M; Martins-Britto,         │
│          Amauri G; Hertem, Dirk Van; Vanin, Marta                   │
│ Year     2026                                                       │
│ abstractNote  The unprecedented pace of Distributed Energy          │
│               Resource (DER) integration and electr…               │
│ language      en                                                    │
│                                                                     │
│ Attachments                                                         │
│   ✓ Numair et al. - 2026 - UNLOCKING DATA CENTRE…pdf               │
│                                                                     │
│ Notes (1)                                                           │
│   • Annotations(2/25/2026) (Numair et al., 2026, p. 1) …           │
╰─────────────────────────────────────────────────────────────────────╯
```

---

### `zot search` — find items

**By title keyword:**
```bash
zot search "bayesian" --field title
```
```
                                5 result(s)
┏━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━┳━━━━━━━━┓
┃  # ┃ Key       ┃ Type            ┃ Title                                     ┃ Authors        ┃ Year   ┃
┡━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━╇━━━━━━━━┩
│  1 │ LVTG4KLQ  │ journalArticle  │ An Improved Recursive Bayesian Approach   │ Chen et al.    │ 2013   │
│    │           │                 │ for Transformer Tap Position Estimation   │                │        │
│  2 │ 6BR3CYQA  │ conferencePaper │ Bayesian distribution system state        │ Angioni et al. │ 2016   │
│    │           │                 │ estimation in presence of non-Gaussian…   │                │        │
└────┴───────────┴─────────────────┴───────────────────────────────────────────┴────────────────┴────────┘
```

**By author name:**
```bash
zot search --author "Numair"
```

**By DOI:**
```bash
zot search --doi "10.1016/j.epsr.2020.106394"
```

**By year range:**
```bash
zot search --year 2023 --type conferencePaper
```

---

### `zot attachments` — locate, attach, and fetch files

**Get the PDF path for a single item:**
```bash
zot attachments path 5UFZMSLU
```
```
~/Zotero/storage/RIB344FW/Numair et al. - 2026 - UNLOCKING DATA CENTRE HOSTING CAPACITY AND FLEXIBILITY THROUGH DYNAMIC CABLE RATING.pdf
```

**Find all missing attachments:**
```bash
zot attachments list --missing
```

**Open a PDF in the system viewer:**
```bash
zot attachments open 5UFZMSLU
```

**Attach a local PDF to an existing item:** (0.3.0+)
```bash
zot attachments add AB3CD7EF ~/Downloads/paper.pdf
```

**Find and attach a PDF using the 4-resolver pipeline:** (0.3.0+)
```bash
zot attachments fetch AB3CD7EF                             # one item
zot attachments fetch-collection "Smart Grid"              # whole collection
zot attachments fetch-all --limit 50                       # whole library (capped)
```

The `fetch*` commands run the same 4-resolver chain that Zotero's
*Find Available PDFs* feature uses internally: try the DOI redirect,
the item's URL field, the Zotero OA mirror
(`https://services.zotero.org/oa/search`), and any custom resolvers from
the `findPDFs.resolvers` config key. Paywalled hosts trigger a headless
Playwright Chromium that reuses cookies saved via
`zot add login --service ieee|sciencedirect`; if even that fails the
browser opens visibly so the user can log in or solve a captcha once.

---

### `zot items fulltext` — retrieve full text

```bash
zot items fulltext 5UFZMSLU
zot items fulltext 5UFZMSLU --offline
```

Retrieval order (cache moved to position 1 in 0.3.0):
1. **Local Zotero full-text cache** (`.zotero-ft-cache` inside the attachment's storage dir),
2. direct network access from DOI/URL (institution/network-location access),
3. configured credentials (`zot config library-auth`),
4. Playwright interactive login fallback,
5. metadata fallback (title/abstract/notes).

---

### `zot export` — export to files

**BibTeX:**
```bash
zot export bib --collection "Energy Market" --output refs.bib
zot export bib --item 5UFZMSLU --output ref.bib
```

**CSV / JSON / Markdown:**
```bash
zot export csv      --collection "Energy Market" --output refs.csv
zot export json     --all --output library.json
zot export markdown --all --notes --output report.md
```

---

### Workflow: search → get attachment paths

```python
from pyzot.db import ZoteroDatabase
from pyzot.queries.search import search_items, search_by_author

DB = "~/Zotero/zotero.sqlite"

with ZoteroDatabase(DB) as db:
    bayesian = search_items(db, "bayesian", fields=["title"])
    numair   = search_by_author(db, "Numair")

    seen = set()
    for item in bayesian + numair:
        if item.item_id in seen:
            continue
        seen.add(item.item_id)
        for att in item.attachments:
            if att.file_exists and "pdf" in att.content_type.lower():
                print(f"{item.key}\t{att.absolute_path}")
```

---

## Writing to your library

> **Default: strictly read-only.** Write capabilities are opt-in and route through Zotero's own connector HTTP server — `zotero.sqlite` is **never** modified directly.

**Zotero must be running** for any `zot add …` command to succeed.

### Enable write capability

```bash
# One-time setup (persists to config)
zot config set write.enabled true

# Check current status
zot config get write.enabled

# Verify Zotero is reachable
zot add status
```

### Quick-start: add items

```bash
# Add by DOI / arXiv / PMID / ISBN
zot add doi 10.1109/TPWRS.2023.1234567
zot add arxiv 2401.12345 --collection Preprints
zot add pmid 31452104
zot add isbn 978-0-262-03384-8 --collection Books

# IEEE Xplore or ScienceDirect URL (DOI is extracted automatically — no browser needed)
zot add "https://ieeexplore.ieee.org/document/9876543"
zot add "https://www.sciencedirect.com/science/article/pii/S2352467725000XYZ"

# Free-text citation string
zot add "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications…"

# Local PDF (Zotero auto-recognises the parent reference)
zot add ~/Downloads/paper.pdf

# Smart auto-detect: zot add figures out the type automatically
zot add "10.1109/TPWRS.2023.1234567"   # detected as DOI
zot add "2401.12345"                    # detected as arXiv
zot add "/home/me/paper.pdf"            # detected as file
```

### Batch add

```bash
# papers.txt: one DOI / arXiv / URL / citation per line; # = comment
zot add batch papers.txt --collection "Smart Grid" --tag imported
```

### Import from a bibliography file

```bash
# .bib, .ris, or .json (CSL-JSON)
zot add import refs.bib --collection "Imports/2026-05"
```

### Automatic PDF attachment (default since 0.3.0)

Every identifier-based `zot add` (doi / arxiv / pmid / isbn / cite / url)
runs the find-file pipeline automatically after the metadata save and
attaches an open-access PDF when one is available — no `--with-pdf`
needed. Disable per call with `--no-pdf` or globally with
`zot config set autoattach.enabled false`.

The pipeline mirrors Zotero's *Find Available PDFs* feature exactly:

1. `doi`    → `https://doi.org/{doi}` (page scrape)
2. `url`    → item's URL field (page scrape)
3. `oa`     → `POST https://services.zotero.org/oa/search` (Zotero OA mirror)
4. `custom` → user-defined resolvers (`findPDFs.resolvers` config key)

For paywalled hosts:

```bash
zot add login --service ieee           # one-time browser SSO (pyzot[browser])
zot add login --service sciencedirect
# Subsequent `zot add` / `zot attachments fetch` calls reuse the saved profile.
```

### Architecture summary

Item metadata writes go through `POST /connector/saveItems` (and related
endpoints) on Zotero's local HTTP server at `127.0.0.1:23119`. Zotero
performs every metadata transaction.

Two narrow direct-SQLite writers exist as documented exceptions:

- `zot collection assign` writes one `collectionItems` row.
- `zot attachments add | fetch*` insert `itemAttachments` rows and copy
  files into `~/Zotero/storage/<key>/`. This is the only path Zotero
  exposes for attaching files to items that weren't created in the
  current connector session.

Both use WAL journal mode and are safe to run while Zotero is open. See
[`docs/architecture-write.md`](docs/architecture-write.md) and
[`docs/fulltext-bugs-and-find-available-pdfs.md`](docs/fulltext-bugs-and-find-available-pdfs.md) for full details.

---

## Running tests

```bash
python3 -m pytest tests/ -q
```
```
441 passed in Xs
```

Tests use an in-memory SQLite fixture seeded with synthetic Zotero data. No real database needed. e2e tests (requiring a live Zotero) are opt-in:

```bash
python3 -m pytest tests/e2e -m e2e
```

---

## Configuration

Self-contained config at `<pyzot-home>/config.toml`. Run `zot config path` to find the directory.

```toml
[database]
path = ""                        # empty = auto-detect zotero.sqlite

[output]
default_format = "table"
color = true
page_size = 50

[write]
enabled = false                  # opt-in; set true once with: zot config set write.enabled true
connector_url = "http://127.0.0.1:23119"
require_zotero = true

[unpaywall]
enabled = false                  # opt-in; set up with: zot add login --service unpaywall
email = ""

[browser]
headless = false                 # SSO/captcha needs headed browser

[library_auth.1]
institution = "KU Leuven"
username = "alice"
password = "token"
```

Override `<pyzot-home>` with the `PYZOT_HOME` environment variable.

---

## Safety

- Database opened with `sqlite3://…?mode=ro` — the OS-level read-only URI flag makes direct writes impossible
- WAL journal detection warns if Zotero is currently open (pending writes may not be visible yet)
- Network retrieval is optional and only used by `zot items fulltext` unless `--offline` is passed
- Write operations route through Zotero's own connector HTTP server — never via direct SQLite mutation
- Default is read-only; writes require explicit opt-in (`zot config set write.enabled true`)
- No Zotero API key required
