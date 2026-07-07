# Changelog

All notable changes to this project will be documented in this file.

## [0.3.0] — 2026-05-24

### Added

- **Find-file pipeline (`pyzot.write.find_file`)** — Python port of Zotero's
  *Find Available PDFs* feature. Four ordered resolvers matching
  `attachments.js::getFileResolvers`:
  1. `doi`    — `https://doi.org/{doi}` followed by HTML page scraping
     (`<meta name="citation_pdf_url">`, then `<a href="*.pdf">`, then
     `pdf|pdfdirect|pdfft` heuristics).
  2. `url`    — same logic on the item's URL field.
  3. `oa`     — `POST https://services.zotero.org/oa/search` (Zotero's
     Unpaywall mirror) for direct PDF URLs and landing pages.
  4. `custom` — user-defined resolvers from the `findPDFs.resolvers` config
     key (same JSON shape as Zotero's pref).
  Each resolver tries direct download first, then page scraping. On a
  paywall it transparently escalates to a headless Playwright Chromium
  reusing the saved IEEE / ScienceDirect cookies. If the cookied headless
  attempt fails the browser opens visibly so the user can solve a captcha
  or complete SSO once — subsequent requests reuse the new session silently.
- **`zot attachments add <KEY> <FILE>`** — attach an existing local PDF to
  an existing Zotero item. Inserts rows into `items` + `itemAttachments` +
  `itemData` and copies the file into `~/Zotero/storage/<new-key>/`.
- **`zot attachments fetch <KEY>`** — run the 4-resolver pipeline for one
  existing item and attach the result. Skips items that already have a
  PDF (override with `--include-with-pdf` on the bulk variants).
- **`zot attachments fetch-collection <NAME>`** — bulk-fetch for every
  item in a collection that lacks a PDF.
- **`zot attachments fetch-all`** — library-wide bulk fetch. Use `--limit`
  to cap the run.
- **`autoattach.enabled` config key** — controls whether `zot add` runs
  the find-file pipeline after the metadata save. Default: `true`.
  `--with-pdf` / `--no-pdf` flags still override per call.
- **`write.BrowserSession.fetch_html()`** — render a paywalled landing
  page through cookied headless Chromium for find-file's page-scraping
  step.
- **`write.BrowserSession` "default" service** — cookieless stealth
  Chromium profile (real TLS fingerprint, `navigator.webdriver` patched,
  `--disable-blink-features=AutomationControlled`) for OA sites with
  basic bot protection.
- **`write.attach_existing`** module — direct SQLite + filesystem writer
  for `itemAttachments` rows. Documented second exception to the "no
  direct SQLite writes for item data" rule (alongside `collection_assign`).
- **Documentation:** `docs/fulltext-bugs-and-find-available-pdfs.md` —
  reverse-engineering of Zotero's PDF lookup with a per-DOI map of OA
  availability for the LV_UG cable-models collection.
- **19 new unit tests** in `tests/unit/` covering `oa_search`,
  `find_file`, and `attach_existing` (with an in-memory mini-schema
  fixture so tests don't touch the user's real library).

### Changed

- **`zot items fulltext` strategy order** — local Zotero full-text cache
  (`.zotero-ft-cache`) is now checked *before* the network. Cheapest and
  most reliable when a PDF is already attached. Previous order is
  preserved for the remaining fallbacks.
- **`--with-pdf` is now opt-out, not opt-in.** Default flips to `True`
  (controlled by `autoattach.enabled`). Use `--no-pdf` for one command.
- **`_run_pdf_attachment` in `cli/add.py`** rewritten to delegate to the
  find-file pipeline. The old Unpaywall-only flow and the first-time
  email-setup prompt are gone (no Unpaywall account required; Zotero's
  mirror handles that).
- **Direct-SQLite writers (`collection_assign`, `attach_existing`)** now
  open with `PRAGMA journal_mode=WAL;` to coexist safely with a running
  Zotero. Previously the default rollback-journal mode could leave a hot
  `-journal` file that blocked all subsequent reads.

### Fixed

- **`zot items fulltext --offline` crash** — the previous SQL referenced
  a `fi.tokenCount` column that does not exist in the actual Zotero
  schema, raising `sqlite3.OperationalError: no such column` on every
  invocation. Replaced the bag-of-words reconstruction with reading the
  on-disk `.zotero-ft-cache` file, which is what Zotero itself uses.

### Removed

- The first-time interactive Unpaywall email prompt — the new pipeline
  uses Zotero's OA mirror which does not require user registration. The
  `zot add login --service unpaywall` command still works for users who
  want to call Unpaywall directly via the legacy resolver.

### Migration notes

- Existing users do not need to change anything: defaults shift toward
  more automation (PDFs attached on add by default). To restore the 0.2.x
  behaviour: `zot config set autoattach.enabled false`.
- Test suites that exercise `zot add` and don't expect a connector
  `saveAttachment` call should add `--no-pdf` or monkeypatch
  `pyzot.cli.add._autoattach_enabled` to return `False`. The bundled
  integration-test conftest does the latter automatically.

## [0.2.2] — 2026-05-19

### Added

- **`zot items fulltext`** — retrieve item full text with a tiered fallback strategy: direct network access (DOI/URL) → configured library credentials → Playwright interactive auth → local Zotero fulltext index → metadata fallback (title/abstract/notes). Supports `--offline`, `--playwright-auth/--no-playwright-auth`, `--max-chars`.
- **`zot config library-auth`** — store or display per-library institution/username/password credentials used by `zot items fulltext` for paywalled retrieval. Credentials persist under `[library_auth.<id>]` in `config.toml`.
- **Fulltext search** — `zot search "query" --fulltext` searches against the local Zotero fulltext index.

### Fixed

- **`save_config` crashed on `None` values** — when calling `tomli_w.dump`, `None` defaults (e.g. `database.path = None`) raised `TypeError: Object of type 'NoneType' is not TOML serializable`. Now strips `None` entries before serialising.

### Merged

- Combined `feat/write-capability` (M1–M6 write subsystem) with PR #1 (network-first fulltext retrieval) onto a single linear history on `master`.

## [0.2.1] — 2026-05-17

### Added

- **`zot collections assign`** — assign an existing item to a collection. Writes a single row to the `collectionItems` join table (no sync-critical metadata involved; safe while Zotero is open).
- **Collection membership check** — `zot collections show` now indicates whether a given item belongs to the collection.

### Fixed

- `updateSession` payload — connector requires `target` as a flat string, not a wrapped object; saveItems calls with an empty body no longer fail.

## [0.2.0] — 2026-05-10

### Added

- **`zot add` command group** — adds items to Zotero via its local connector HTTP server (port 23119). Zotero must be running; `zotero.sqlite` is never modified directly.
- **Smart auto-detect dispatcher** — bare `zot add "<anything>"` identifies DOI, arXiv ID, PMID, ISBN, IEEE/ScienceDirect URL, citation string, or local file path automatically.
- **`zot add doi`** — resolve via Crossref, send to Zotero. Supports `--collection`, `--tag`, `--dry-run`, `--with-pdf`, `--on-duplicate`.
- **`zot add arxiv`** — resolve via arXiv Atom feed → CSL-JSON.
- **`zot add pmid`** — resolve via NCBI eutils.
- **`zot add isbn`** — resolve via OpenLibrary (Google Books fallback).
- **`zot add cite`** — free-text citation string → Crossref bibliographic search → DOI; fallback OpenAlex then Semantic Scholar. Interactive disambiguation table when confidence is low. `--file` for batch citation files.
- **`zot add url`** — auto-routes arXiv/PubMed/IEEE/ScienceDirect/doi.org URLs to the relevant resolver; generic URLs fall back to `saveSnapshot`.
- **`zot add file`** — stream a local PDF or EPUB to `/connector/saveStandaloneAttachment`; polls for Zotero's `RecognizeDocument` result (configurable timeout, default 30 s).
- **`zot add import`** — POST raw RIS / BibTeX / CSL-JSON bytes to `/connector/import`.
- **`zot add batch`** — process a file of mixed inputs (one per line); summary table at end; non-zero exit if any line failed.
- **`zot add login`** — manage service credentials: Unpaywall (email), IEEE Xplore (browser SSO), ScienceDirect (browser SSO). `--reset` to clear. `--install-browser` for first-time Playwright Chromium install.
- **`--with-pdf` flag** on doi/arxiv/pmid/isbn/cite/url — attach an open-access PDF using Unpaywall; fall back to publisher cookies (IEEE/Elsevier) if browser-authenticated.
- **`zot add status`** — preflight check: reports Zotero reachability, selected collection, and connector URL.
- **`zot config` command group** — `get`, `set`, `path` subcommands for reading and writing `<pyzot-home>/config.toml`.
- **Self-contained data directory** (`<pyzot-home>`) — resolved via `PYZOT_HOME` env → SKILL.md sibling search → `~/.pyzot`. Holds `config.toml`, `credentials.json`, `cookies/`, `cache/`, `logs/`.
- **Write gate** — `write.enabled = false` by default. Enable once with `zot config set write.enabled true`, or pass `--allow-write` / set `PYZOT_ALLOW_WRITE=1` per command.
- **Duplicate detection** (report-only by default) — on duplicate DOI/arXiv, prints existing item key + title and exits 0; no mutation.
- **`--dry-run`** on all add subcommands — resolves metadata and prints the payload that would be sent, without contacting the connector.
- **`-v` / `--verbose`** — echoes every HTTP request and response to stderr.
- **`--non-interactive`** — suppresses all prompts; used in scripts and agent contexts.
- **Rotating log** at `<pyzot-home>/logs/zot.log` (1 MB × 3 backups).
- **Optional dependency groups**: `write = ["httpx>=0.27"]`, `browser = ["playwright>=1.40"]`, `all` aggregates all extras.
- **441 unit + integration tests** (up from 40 in v0.1.3). e2e tests are opt-in (`pytest -m e2e`).
- **`docs/architecture-write.md`** — maintainer-facing overview of the write-path design.

### Changed

- `README.md` and `SKILL.md` updated to document write capability and correct the "never writes" framing. The accurate framing is: default is strictly read-only; writes require opt-in and go through Zotero's connector.
- `pyproject.toml` description updated; version bumped to 0.2.0.
- `docs/commands.md` extended with full `zot add` and `zot config` reference.
- SKILL.md `description:` frontmatter now advertises both reading and writing.

### Fixed

- Click 8.2 `mix_stderr` keyword removal (M5 fix).
- `RotatingFileHandler` lock-pairing bug in logging setup (M5 fix).
- `updateSession` target correctly sent as flat string, not nested object (M2 fix).

### Deferred to v0.3

- Edit / delete existing items — blocked on Zotero local API not yet supporting writes, or requires shipping a `.xpi` plugin. Tracked in `PLAN_WRITE.md §12`.
- Parallel connector calls in `zot add batch` (`--jobs N` accepted but no-op; sequential connector calls are safe; parallel resolver lookups deferred).
- Group library targeting beyond current-selection default.

### Manual smoke test

Run the following commands against a live Zotero instance before tagging v0.2.0:

```bash
# Sanity
zot --version
zot stats

# Write gate
zot config set write.enabled true
zot config get write.enabled        # should print "true"
zot config path                     # should print <pyzot-home>

# Preflight
zot add status                      # should report Zotero as reachable

# Add by identifier
zot add doi 10.1038/s41586-020-2649-2 --collection Inbox --dry-run
zot add doi 10.1038/s41586-020-2649-2 --collection Inbox --tag smoke-test
zot add arxiv 2401.12345 --collection Preprints
zot add pmid 31452104
zot add isbn 978-0-262-03384-8 --collection Books

# Add by URL
zot add url https://ieeexplore.ieee.org/document/9876543
zot add url https://www.sciencedirect.com/science/article/pii/S2352467725000102

# Free-text citation
zot add cite "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: Evaluating assumptions for low-voltage network modelling in the DER era."

# Local file
zot add file ./paper.pdf --collection Inbox

# Import
zot add import refs.bib --collection "Imports/test"

# Batch
printf '10.1109/TPWRS.2023.1234567\n2401.12345\n' > /tmp/papers.txt
zot add batch /tmp/papers.txt --collection "Batch Test"

# Paywalled PDF (optional: requires prior login)
zot add login --service unpaywall
zot add doi 10.1038/s41586-020-2649-2 --with-pdf
```

---

## [0.1.3] — 2026-04-13

### Added

- Item export command (`zot export`) with JSON, CSV, BibTeX, and Markdown formats.
- Collection display improvements and recursive collection traversal.

### Fixed

- Removed unsupported schema version warnings from schema validation.
- Database path auto-detection clarified for Linux, macOS, and Windows.
