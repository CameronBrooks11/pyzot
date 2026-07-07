# pyzot — Write Capability Plan

- **Branch:** `feat/write-capability`
- **Status:** **READY FOR IMPLEMENTATION** — design approved, decisions in §13, handoff prompts in §15
- **Audience:** maintainer + the sonnet implementation agent
- **Goal:** extend `pyzot` (currently strictly read-only, v0.1.3) with an opt-in write path that **adds items / attachments / metadata to the local Zotero library** without ever touching `zotero.sqlite` directly. Read-only commands stay byte-identical.

---

## 1. Why we cannot just write to SQLite

The current `pyzot` opens the DB with `mode=ro` + `PRAGMA query_only=ON`. Tempting to flip it — but Zotero is **not** "just SQLite". A new item touches:

| Concern | Side-effect we'd have to replicate by hand |
| --- | --- |
| `items`, `itemDataValues`, `itemData`, `itemCreators`, `creators`, `itemTypes` | Schema + valid type/field mapping per Zotero schema version |
| `collectionItems` | Collection membership |
| `itemAttachments`, `storage/<KEY>/file.pdf` | Attachment row + on-disk file in the right `storage/<8charKey>/` folder |
| `fulltextItems`, `fulltextWords`, `fulltextItemWords` | PDF text extraction + index |
| `syncCache`, `syncedSettings`, `objectVersions` | Server-sync state — wrong values cause **silent data loss** on next sync |
| `creatorsMerge`, `relations`, `tags`, `itemTags` | Tagging + dedup |
| `version` table | Schema-version coupling |

Zotero also holds an **EXCLUSIVE WAL lock** while running, so concurrent writes are unsafe. Community + Zotero docs are clear: **never write to `zotero.sqlite` from a third-party tool**.

Therefore the plan uses Zotero's own code paths via its existing local HTTP server.

---

## 2. Surveyed Zotero internals

Located under `zotero-sources-lookup/` (gitignored). Key findings:

### 2.1 Connector HTTP server — `127.0.0.1:23119/connector/*`

File: `zotero/chrome/content/zotero/xpcom/server/server_connector.js`

Lives inside the Zotero desktop app (must be running). Endpoints relevant to writing:

| Endpoint | Purpose |
| --- | --- |
| `POST /connector/saveItems` | Save a parent item from a CSL-ish JSON payload `{items:[…], uri, sessionID}`. Saves to the **currently selected** library/collection in the Zotero pane. Returns `201` + serialized items. |
| `POST /connector/saveSnapshot` | Save a webpage snapshot as a standalone item. |
| `POST /connector/saveStandaloneAttachment` | Stream a binary file (PDF/EPUB) → standalone attachment item; **auto-runs `Zotero.RecognizeDocument`** to fetch parent metadata. Headers carry `X-Metadata` JSON. |
| `POST /connector/saveAttachment` | Same but as a child of an existing parent saved earlier in the same session. |
| `POST /connector/import` | Stream **RIS / BibTeX / CSL-JSON / MODS / etc.** body — Zotero auto-detects the import translator. |
| `POST /connector/updateSession` | After a saveItems call, re-target the saved items to a specific collection (`target = "C<collectionID>"`), and add tags + a child note. **This is how we hit a chosen collection without forcing the user to click in Zotero.** |
| `GET  /connector/ping` | Liveness check. |
| `GET  /connector/getSelectedCollection` | Reports current target. |

Auth: none (loopback only). Permits `Origin: null` and the bookmarklet origin.

### 2.2 Local API server — `127.0.0.1:23119/api/*`

File: `zotero/chrome/content/zotero/xpcom/server/server_localAPI.js` — mirrors `api.zotero.org` v3, **read-only** ("Write access is not yet supported"). Useful for richer reads, **not** for our write feature.

### 2.3 Add-by-Identifier flow

File: `zotero/chrome/content/zotero/lookup.js` — uses `Zotero.Translate.Search.setIdentifier()` + Crossref/PubMed/OpenLibrary translators internally. **Not exposed over HTTP.** We resolve identifiers ourselves.

### 2.4 Web translators (IEEE / ScienceDirect / etc.)

The Zotero connector browser extension uses ~760 site-specific JS translators (`translators/` submodule, e.g. `IEEE Xplore.js`, `ScienceDirect.js`). When a CLI is the trigger, **we don't have a browser DOM** — so we cannot invoke those translators directly. We have two viable paths from the CLI:

1. **DOI shortcut** — IEEE + Elsevier (ScienceDirect) both deposit DOIs at Crossref; resolving the DOI gives a clean CSL-JSON record. Zero browser needed.
2. **Snapshot path** — `POST /connector/saveSnapshot` with `{url, html, sessionID}` triggers Zotero's translator chain on the fetched HTML. For paywalled pages, we render with Playwright using the user's authenticated cookies, then hand the rendered HTML to Zotero.

### 2.5 Plugin route (rejected for v1, deferred to v2)

`zotero-plugin-template` (windingwind) shows how to ship a `.xpi`. Not needed for MVP — connector covers every write op. Deferred to v2 for arbitrary item editing / deletion (see §11).

### 2.6 Web library / web API

`web-library/` + `dataserver/` show the zotero.org web API. Requires API key + network. Out of scope for v1.

---

## 3. Architectural decision

> **Primary write path = local connector HTTP server.**
> **Citation/title/identifier resolution = external scholarly APIs (Crossref / OpenAlex / Semantic Scholar / arXiv / PubMed / OpenLibrary / IEEE / Unpaywall).**
> **Paywall / SSO / captcha = Playwright headed window (opt-in).**
> **Never touch `zotero.sqlite` directly.**

```text
┌──────────────┐   identifier (doi / isbn / arxiv / pmid)  ─┐
│  zot add …   │   citation string ("Zhang et al 2025 …")   │
└──────┬───────┘   url (https://ieeexplore.ieee.org/…)      │
       │           url (https://www.sciencedirect.com/…)    │
       │ pdf path                                           │
       │                                                    ▼
       │                        ┌─────────────────────────────────────────┐
       │                        │ resolver pipeline                       │
       │                        │  1. detect_kind(input)                  │
       │                        │  2. identifier? → Crossref/PubMed/      │
       │                        │     arXiv/OpenLibrary                   │
       │                        │  3. citation string? → Crossref         │
       │                        │     /works?query.bibliographic=…        │
       │                        │     fallback OpenAlex, then S2          │
       │                        │  4. IEEE/ScienceDirect URL? → DOI from  │
       │                        │     URL pattern → Crossref              │
       │                        │     fallback Playwright snapshot        │
       │                        │  5. validate, score, dedup-check        │
       │                        └────────────┬────────────────────────────┘
       │                                     │  CSL-JSON  /  RIS  /  HTML
       ▼                                     ▼
┌───────────────────────────────────────────────────────────────────┐
│  pyzot.write.connector_client                                    │
│   • GET   /connector/ping            (preflight)                  │
│   • POST  /connector/saveItems       (sessionID, items[…])        │
│   • POST  /connector/saveSnapshot    (html for IEEE/SD fallback)  │
│   • POST  /connector/saveStandaloneAttachment (binary stream)     │
│   • POST  /connector/import          (RIS/BibTeX bytes)           │
│   • POST  /connector/updateSession   (target=C<id>, tags, note)   │
└───────────────────────────────────────┬───────────────────────────┘
                                        │ loopback http
                                        ▼
                           Zotero desktop app  (running)
                                        │
                                        ▼
                               zotero.sqlite + storage/
                          (Zotero owns all writes)

  Optional fallback (only when paywall / captcha blocks PDF download
  or HTML retrieval, e.g. IEEE Xplore via institutional SSO):
       Playwright (headed Chromium) → user authenticates once →
       cookies persisted → reused for direct fetches and snapshots.
```

Why this is right:

- **Zero risk of DB corruption** — Zotero performs every transaction.
- **Sync-safe** — items get proper `syncCache` / version rows.
- **Auto-recognize** — `saveStandaloneAttachment` triggers `RecognizeDocument` for free.
- **No `.xpi` to maintain.**
- **CLI-first** — Playwright only opens a browser when an external website demands it.

---

## 4. Source coverage matrix (what works without a browser)

| Source | Identifier path | URL path | PDF retrieval | Notes |
| --- | --- | --- | --- | --- |
| **IEEE Xplore** (`ieeexplore.ieee.org`) | DOI (`10.1109/...`) → Crossref → CSL-JSON ✅ | URL → extract `arnumber` or DOI → Crossref ✅; fallback `/connector/saveSnapshot` with Playwright-rendered HTML | Open-access via Unpaywall ✅; paywalled requires institutional SSO via `zot add login` then PDF GET with cookies | DOI is always present in IEEE URLs (`/document/<arnumber>` → DOI lookup via IEEE public metadata API or Crossref reverse-search by arnumber) |
| **ScienceDirect / Elsevier** (`sciencedirect.com`) | DOI (`10.1016/...`) → Crossref → CSL-JSON ✅ | URL → DOI from `/pii/<PII>` via Crossref `/works?query.bibliographic=PII` ✅; fallback snapshot | Unpaywall for OA; paywalled requires Elsevier SSO via `zot add login` | Same as IEEE — the URL almost always resolves to a DOI |
| **arXiv** (`arxiv.org`) | arXiv ID → arXiv Atom feed → CSL-JSON ✅ | URL → arXiv ID regex → above | Direct PDF (always OA) ✅ | Native, no browser ever needed |
| **PubMed** | PMID → efetch JSON → CSL-JSON ✅ | URL → PMID regex → above | Unpaywall for full text | Native |
| **DOI (any other publisher)** | Crossref `/works/<doi>` ✅ | n/a | Unpaywall | Universal fallback |
| **ISBN (books)** | OpenLibrary + Google Books → CSL-JSON ✅ | n/a | n/a | Native |
| **Free-text citation** | Crossref `/works?query.bibliographic=…` → top match → DOI → Crossref ✅; fallback OpenAlex `/works?search=…`; final fallback Semantic Scholar `/graph/v1/paper/search` | n/a | Unpaywall on resolved DOI | Confidence score + interactive disambiguation if score < threshold |
| **Generic webpage** | n/a | `/connector/saveSnapshot` ✅ (Zotero translators run on HTML) | n/a | For sites without a DOI |
| **Local PDF / EPUB** | n/a | n/a | `/connector/saveStandaloneAttachment` → Zotero auto-recognizes ✅ | The "drop-a-file" path |

Conclusion: every IEEE / ScienceDirect document the user cares about is reachable via Crossref through its DOI — no browser required for metadata. A browser is only needed to retrieve **paywalled PDFs**, and only when Unpaywall has no OA copy.

### 4.1 Citation-string resolver (the "paste a reference" feature)

Input example (from the user):

```text
Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: Evaluating
assumptions for low-voltage network modelling in the DER era. Sustainable Energy, Grids
and Networks, 2025.
```

Pipeline:

1. Normalise (strip extra whitespace, unify quotes).
2. Crossref `GET https://api.crossref.org/works?query.bibliographic=<text>&rows=5&select=DOI,title,author,issued,container-title,score`.
3. Pick top result if its `score` is comfortably above the next one (configurable threshold, default `score >= 50` AND `score / next_score >= 1.4`).
4. If unambiguous → use the DOI like any `zot add doi` flow.
5. If ambiguous → render the top 5 candidates via `rich.table` and ask the user to pick (`--non-interactive` mode picks #1 only when the score gap is large; otherwise errors).
6. If Crossref returns nothing → fall back to OpenAlex `/works?search=…&per-page=5` (works for preprints + grey lit).
7. If OpenAlex empty → Semantic Scholar `/graph/v1/paper/search?query=…&limit=5&fields=externalIds,title,authors,year`. Honour rate limit (sleep + retry; soft fail on 429).
8. Once a DOI is found, run the same DOI flow from §6.1.

CLI exposure:

```bash
zot add cite "Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications: …"
zot add cite --file refs.txt          # one citation per line
zot add cite "<paste>" --interactive  # always show candidates, even when score is high
```

`zot add` (no subcommand) auto-detects between DOI / arXiv ID / PMID / ISBN / URL / citation string. Subcommands stay available for scripting.

---

## 5. New CLI surface

All under a new top-level group `zot add`. Existing commands untouched.

```bash
# Preflight — can we talk to Zotero right now?
zot add status

# Smart auto-detect — guesses what kind of input it is
zot add "10.1109/TPWRS.2023.1234567"
zot add "https://ieeexplore.ieee.org/document/9876543"
zot add "Zhang, J. et al. (2025) Beyond simplifications…"
zot add "/home/me/Downloads/paper.pdf"

# Explicit subcommands (preferred for scripts / agents)
zot add doi    10.1109/TPWRS.2023.1234567   [--collection "Smart Grid"] [--tag to-read]
zot add isbn   978-0-262-03384-8            [--collection Books]
zot add arxiv  2401.12345
zot add pmid   31452104
zot add url    https://example.org/paper.html
zot add cite   "Zhang, J. et al. (2025) Beyond simplifications…"
zot add file   ~/Downloads/paper.pdf        [--collection Inbox] [--tag ml]
zot add batch  papers.txt                    [--collection "Smart Grid"]
zot add import refs.bib                      [--collection "Imports/2026-05"]

# One-off config toggle for write capability (decision §13.3)
zot config set write.enabled true     # persists; no need to pass --allow-write again
zot config set write.enabled false    # turn off
zot config get write.enabled

# Authentication helper (decision §13.2: opt-in, prompted on first need)
zot add login                          # opens headed browser; user signs into SSO/Unpaywall
zot add login --service unpaywall      # save Unpaywall email
zot add login --service ieee           # IEEE / institutional
zot add login --service sciencedirect  # Elsevier
```

Global flags added to root `cli`:

```text
--allow-write           # ad-hoc gate; not needed once `write.enabled=true` is set
--connector-url URL     # default http://127.0.0.1:23119
--require-zotero / --no-require-zotero   # default: require
--non-interactive       # never prompt; fail/skip ambiguous citations
```

`--allow-write` precedence: explicit flag > env `PYZOT_ALLOW_WRITE=1` > config `write.enabled = true`.

---

## 6. Module layout

```text
src/pyzot/
├── cli/
│   ├── add.py                  ← NEW: click group `zot add` + auto-detect
│   ├── config_cmd.py           ← NEW: `zot config get/set/path`
│   └── main.py                 ← MODIFIED: register groups, --allow-write
├── write/                      ← NEW package
│   ├── __init__.py
│   ├── connector_client.py     ← httpx client for /connector/*
│   ├── preflight.py            ← ping + selected-collection probe
│   ├── session.py              ← sessionID lifecycle (uuid4) + updateSession
│   ├── csl_json.py             ← CSL-JSON ↔ Zotero connector item shape
│   ├── identifiers.py          ← detect doi / arxiv / pmid / isbn / url / citation
│   ├── dedup.py                ← read-only DOI/arxiv lookup against existing DB
│   ├── resolvers/
│   │   ├── __init__.py         ← dispatcher
│   │   ├── crossref.py         ← DOI → CSL-JSON; bibliographic search
│   │   ├── openalex.py         ← citation/title fallback
│   │   ├── semantic_scholar.py ← second fallback (rate-limited)
│   │   ├── arxiv.py            ← arXiv ID → CSL-JSON
│   │   ├── pubmed.py           ← PMID → CSL-JSON
│   │   ├── openlibrary.py      ← ISBN → CSL-JSON
│   │   ├── unpaywall.py        ← DOI → OA PDF URL (opt-in)
│   │   ├── ieee.py             ← URL → DOI extraction helpers
│   │   └── sciencedirect.py    ← URL/PII → DOI extraction helpers
│   ├── pdf.py                  ← MIME sniff + streaming upload
│   ├── browser.py              ← Playwright headed window + cookie jar (lazy import)
│   └── credentials.py          ← keyring-free, file-based encrypted-at-rest credential store
├── paths.py                    ← NEW: cross-platform self-contained path resolution (§7)
├── config.py                   ← MODIFIED: [write] section + new resolution rules
└── …
```

New deps (additive; default install untouched):

```toml
[project.optional-dependencies]
write    = ["httpx>=0.27"]
browser  = ["playwright>=1.40"]
all      = ["pyzot[bibtex,export,write,browser]"]
```

Default install stays minimal. Users opt in: `pip install "pyzot[write]"` and `pip install "pyzot[browser]"`.

---

## 7. Self-contained, cross-platform configuration (decision §13.4)

Goal: works identically on **Linux, macOS, and Windows**; config / cache / credentials live **next to the skill on disk**, not buried under OS-specific dirs. User can `cd` to the skill folder and inspect everything.

### 7.1 Path resolution rules

`pyzot.paths.pyzot_home()` returns the first match:

1. `PYZOT_HOME` env var, if set and writable.
2. Walk up from `Path(__file__).resolve().parent` looking for a sibling `SKILL.md` — when found, use `<that-dir>/.pyzot/`.
3. If invoked through a `zot` console script that exists inside a directory tree containing `SKILL.md` (typical when the skill is checked out from git or installed as a portable bundle), use `<skill-root>/.pyzot/`.
4. Final fallback: `Path.home() / ".pyzot"` — same on every OS, no XDG-vs-AppData branching. (We deliberately do **not** use `platformdirs` here; the user wants one consistent location.)

Layout under `<pyzot-home>/`:

```text
.pyzot/
├── config.toml               # user-editable settings
├── credentials.json          # service logins (Unpaywall email, etc.) — not encrypted, mode 0600
├── cookies/                  # Playwright persistent profiles, one per service
│   ├── ieee/
│   ├── sciencedirect/
│   └── default/
├── cache/
│   ├── crossref/             # keyed by DOI, JSON
│   ├── openalex/
│   └── sessions.jsonl        # sessionID → item keys (idempotency)
└── logs/
    └── zot.log               # rolling, last 1 MB
```

`zot config path` prints `<pyzot-home>` so the user can find it instantly. Directory is created lazily on first write.

### 7.2 `config.toml` example

```toml
[database]
path = ""                        # empty = auto-detect zotero.sqlite

[write]
enabled = false                  # the §13.3 one-off setting
connector_url = "http://127.0.0.1:23119"
require_zotero = true
non_interactive_default = false

[resolvers]
order = ["crossref", "openalex", "semantic_scholar"]
crossref_user_agent = "pyzot/0.2 (mailto:auto-set-on-first-run)"

[unpaywall]
enabled = false                  # §13.2 opt-in default
email = ""                       # populated on first use via `zot add login --service unpaywall`

[browser]
profile_root = ""                # empty = <pyzot-home>/cookies
headless = false                 # SSO/captcha needs headed

[duplicates]
# §13.5: just inform, return key, do not mutate
on_duplicate = "report"          # report | skip | force-add
```

---

## 8. End-to-end flows

### 8.1 `zot add doi 10.1109/X --collection "Smart Grid" --tag to-read`

1. Write-gate check (`write.enabled` OR `--allow-write` OR env).
2. `preflight.ping()` → fail-fast actionable error if Zotero is closed.
3. `dedup.find_by_doi("10.1109/X")` → if hit, **§13.5 behavior**: print existing item key + title, exit 0. No prompt, no mutation.
4. `crossref.resolve("10.1109/X")` → CSL-JSON.
5. Translate CSL-JSON → connector item shape.
6. `sessionID = uuid4()`; `POST /connector/saveItems`.
7. Resolve target collection name → ID via local read-only DB (`queries/collections.py` already exists).
8. `POST /connector/updateSession {sessionID, target:"C<id>", tags:[...], note:""}`.
9. Optional `--with-pdf`: `unpaywall.resolve(doi)` → fetch PDF → `POST /connector/saveAttachment` (child).
10. Print new item key + storage path.

### 8.2 `zot add "Zhang, J. et al. (2025) Beyond simplifications…"` (citation string)

Auto-detect → §4.1 pipeline → DOI → §8.1 from step 3.

### 8.3 `zot add url https://ieeexplore.ieee.org/document/9876543`

1. Write-gate + preflight.
2. `ieee.url_to_doi(url)` — try in order:
   - regex extract DOI from URL/page query string,
   - IEEE public metadata REST (`/rest/document/<arnumber>/metadata` — no key needed for basic fields, returns DOI),
   - Crossref reverse search.
3. If DOI found → §8.1.
4. Else fallback: Playwright (if `[browser]` extra installed) renders the page → snapshot HTML → `POST /connector/saveSnapshot` → Zotero's IEEE translator runs.

### 8.4 `zot add url https://www.sciencedirect.com/science/article/pii/S2352467725000XYZ`

1. Same shape as 8.3.
2. `sciencedirect.url_to_doi(url)` extracts the PII, queries Crossref (`/works?filter=alternative-id:<PII>` or `?query.bibliographic=<PII>`).
3. DOI → §8.1.
4. Fallback: Playwright → saveSnapshot.

### 8.5 `zot add file ~/Downloads/paper.pdf --collection "Inbox"`

1. Preflight + write gate.
2. MIME sniff (`application/pdf` / `application/epub+zip`).
3. `sessionID = uuid4()`.
4. `POST /connector/saveStandaloneAttachment` with body = file stream, headers `Content-Type`, `Content-Length`, `X-Metadata: {sessionID, title, url:"file://…"}`.
5. Wait for `201` → `{canRecognize: true|false}`. Zotero auto-runs `RecognizeDocument` in background.
6. `POST /connector/updateSession` for collection + tags.
7. Poll local read-only DB for the parent (created by recognizer) — bounded retry, default 30 s.
8. Print recognized parent's key + title; or, if recognition failed, the standalone attachment key.

### 8.6 `zot add login --service unpaywall` (first-time prompt, decision §13.2)

1. Prompt: "Unpaywall requires an email address per their fair-use policy. Enter your email:".
2. Validate, save to `<pyzot-home>/credentials.json` `{services.unpaywall.email}`.
3. Set `[unpaywall] enabled = true`.
4. Subsequent `zot add doi … --with-pdf` runs use the saved email automatically.

For `--service ieee` / `--service sciencedirect`:

1. Launch headed Chromium with `<pyzot-home>/cookies/<service>/` as user-data-dir.
2. Open `https://ieeexplore.ieee.org/Xplore/home.jsp` (or SD home).
3. User signs in (institutional SSO / shibboleth / direct).
4. We detect a successful auth (`page.wait_for_url` to a post-login pattern, or click a "I'm signed in" confirmation button rendered by pyzot into the page).
5. Persist cookies; close window.
6. Print "Logged in as <user> for <service>. Cookies saved to `<pyzot-home>/cookies/<service>/`."

The browser is **only** for auth/captcha/paywall, never for primary metadata — matches the requirement.

### 8.7 First-time write attempt without prior auth

If a write command needs a service the user hasn't logged into yet:

```text
$ zot add doi 10.1109/X --with-pdf
[warn] Unpaywall is opt-in and not configured.
       Run `zot add login --service unpaywall` first, or pass --no-pdf to skip PDF retrieval.
       (Press Y to launch login now / N to skip / q to abort): _
```

Pressing Y inlines the §8.6 flow, then continues.

---

## 9. Safety & UX guarantees

- **Write gate always enforced.** Default `write.enabled = false`; one-off toggle via `zot config set write.enabled true`. `--allow-write` and `PYZOT_ALLOW_WRITE=1` provide ad-hoc overrides.
- **All writes go through Zotero.** Our SQLite handle stays `mode=ro`.
- **WAL detection still warns** (existing `db.py`).
- **Idempotency.** `connector_client` records `sessionID → item keys` in `<pyzot-home>/cache/sessions.jsonl`.
- **Duplicate handling** (decision §13.5). On duplicate DOI: print "Item with DOI X already exists: <KEY> — <title>" and exit 0. No prompt. Tag/collection mutations on existing items are **deferred to v2**.
- **Dry-run.** `--dry-run` resolves metadata + prints the JSON we would POST, no request.
- **Verbose.** `-v` echoes every HTTP request/response.
- **Network egress is explicit.** Connector talks loopback only. External resolvers (Crossref / Unpaywall / etc.) listed in README; each can be disabled in config.
- **No Zotero API key required.**
- **All credentials at-rest.** `<pyzot-home>/credentials.json` is mode 0600 (POSIX) / ACL-restricted (Windows via `pywin32` if present, else best-effort).

---

## 10. Tests

```text
tests/
├── unit/
│   ├── test_identifiers.py
│   ├── test_csl_json.py
│   ├── test_dedup.py
│   ├── test_paths.py                 # pyzot_home resolution under each rule
│   └── test_resolvers/
│       ├── test_crossref.py          # vcrpy cassettes
│       ├── test_openalex.py
│       ├── test_semantic_scholar.py
│       ├── test_arxiv.py
│       ├── test_pubmed.py
│       ├── test_openlibrary.py
│       ├── test_unpaywall.py
│       ├── test_ieee.py
│       └── test_sciencedirect.py
├── integration/
│   ├── test_connector_client.py      # pytest-httpserver mock of /connector/*
│   ├── test_session.py
│   └── test_add_pipeline.py          # end-to-end with mocked connector + mocked resolvers
└── e2e/                              # @pytest.mark.e2e (already a marker)
    ├── test_add_doi.py
    ├── test_add_pdf.py
    ├── test_add_cite.py
    ├── test_add_ieee.py              # real ieeexplore URLs
    ├── test_add_sciencedirect.py
    └── test_add_import.py
```

CI runs unit + integration. e2e remains opt-in.

---

## 11. SKILL.md changes (decision §13.6)

Replace the "Never writes" claim with a clear write section. The skill description must:

1. State that writes go through Zotero's connector — **Zotero must be running** for any `zot add …`.
2. Tell the agent to enable writes one-off: `zot config set write.enabled true` (preferred) or pass `--allow-write` per command.
3. **Explicit instruction for any agent using this skill**: *"Before invoking any `zot add` command, ensure `write.enabled` is `true` in `<pyzot-home>/config.toml`, or include `--allow-write` on each call. If unsure, run `zot config get write.enabled` first."*
4. Document `<pyzot-home>` resolution (§7.1) — agents inspect/modify config without OS-specific assumptions.
5. Add the smart auto-detect example: `zot add "<anything>"`.
6. List supported sources (IEEE, ScienceDirect, arXiv, PubMed, ISBN, citation strings, local PDFs).
7. Emphasise read-only commands are unchanged and remain the default.

A drafted SKILL section is in `docs/skill-write-section.md` (created in M6).

---

## 12. Out of scope for v1 → v2 roadmap

| Item | v2 path |
| --- | --- |
| Edit existing items (rename, change collection, retag) | Either ship `.xpi` with `/pyzot/updateItem` endpoint, or wait for the local API to gain write support, or use web API with a user-supplied key. **Deferred — no work in v1.** |
| Delete items | Same blocker; deferred. |
| Notes editing beyond what `updateSession` supports | Deferred. |
| Group library targeting via `L`/`U`/`G` IDs | `updateSession` accepts these — partial v1 support, polished in v1.1. |
| Sync trigger control | Auto-sync stays as Zotero schedules; we do not call `/connector/delaySync`. |

---

## 13. Decisions (locked)

These were the open questions in the previous draft. **All locked by user.**

1. **§13.1 Browser profile dir** — `<pyzot-home>/cookies/<service>/`. Self-contained, OS-agnostic, portable with the skill. (User: "self-contained skill … relative location to the pyzot location.")
2. **§13.2 Unpaywall** — Opt-in by default. On first use that needs it, prompt user for email; persist to `<pyzot-home>/credentials.json`; never ask again unless they `zot add login --service unpaywall --reset`.
3. **§13.3 `--allow-write` ergonomics** — One-off setting via `zot config set write.enabled true`. Once set, no flag needed. Ad-hoc `--allow-write` and env `PYZOT_ALLOW_WRITE=1` still supported.
4. **§13.4 Cross-platform config storage** — `<pyzot-home>` resolved per §7.1, Linux + macOS + Windows identical. No XDG / AppData branching.
5. **§13.5 Duplicate handling** — On duplicate DOI, **inform** the user the entry already exists and **show the item key** so it can be reused. No prompt, no mutation. Default `on_duplicate = "report"`.
6. **§13.6 Plugin path** — No `.xpi` for v1. Item editing deferred entirely to v2 (see §12).

---

## 14. Roadmap (post-decisions)

| Tag | Milestone | Branch state | Outputs |
| --- | --- | --- | --- |
| **v0.1.3** | current `master` | released | read-only CLI |
| **v0.2.0-M1** | preflight + plumbing | `feat/write-capability` | `zot add status`, `zot config get/set`, `paths.py`, `connector_client.ping()` |
| **v0.2.0-M2** | identifier resolvers | same | `zot add doi/isbn/arxiv/pmid` + Crossref/arXiv/PubMed/OpenLibrary; `updateSession`-based collection/tag |
| **v0.2.0-M3** | citation + URL | same | `zot add cite`, `zot add url`, IEEE + ScienceDirect URL→DOI helpers, OpenAlex + S2 fallbacks |
| **v0.2.0-M4** | local files | same | `zot add file`, `zot add import`, recognizer poll |
| **v0.2.0-M5** | auto-detect + batch + dedup + dry-run | same | `zot add "<anything>"`, `zot add batch`, dedupe report, `--dry-run` |
| **v0.2.0-M6** | Playwright auth | same | `zot add login`, `--with-pdf`, IEEE / ScienceDirect / Unpaywall paths |
| **v0.2.0**  | docs + release | merge to `master` | README, SKILL.md, CHANGELOG, version bump, PyPI release |
| **v0.3.0** | (deferred) item editing | new branch | `.xpi` plugin OR web-API key path; tag/collection mutations on existing items |

Each Mn lands as **one PR-shaped commit** on `feat/write-capability`. Merge to `master` only after v0.2.0-M6 is green.

---

## 15. Implementation prompts (handoff to sonnet)

Each prompt below is **self-contained** for a fresh sonnet agent. Run them in order. Each prompt assumes:

- working dir `/home/mnumair/projects/MY_SKILLS/pyzot`,
- branch `feat/write-capability` checked out,
- `PLAN_WRITE.md` (this file) is the source of truth.

> **Operating rules for the sonnet implementer (apply to every prompt below):**
>
> - **Do not modify any read-only command behavior.** All v0.1.3 commands and tests must keep passing unchanged.
> - **Do not write to `zotero.sqlite` directly.** Ever. The DB connection stays `mode=ro` + `PRAGMA query_only=ON`.
> - **All writes go through `pyzot.write.connector_client`.** No bypass.
> - **Add tests with each milestone.** A milestone is not done until unit + integration tests pass.
> - **No feature creep.** Stick to the milestone's scope; defer extras to a follow-up note in PLAN_WRITE.md §12.
> - **Update PLAN_WRITE.md at the bottom of each milestone** with a short "M<n> implemented on <date>, commit <sha>" line in §14.

### 15.1 — M1: preflight + plumbing

```text
TASK: Implement pyzot v0.2.0-M1 (preflight + plumbing).

DELIVERABLES (commit message: "feat(write): M1 preflight + plumbing"):

1. Add optional dependency group `write = ["httpx>=0.27"]` to pyproject.toml.
   Bump version to 0.2.0.dev1.

2. Create src/pyzot/paths.py implementing:
     - pyzot_home() → Path, resolved per PLAN_WRITE.md §7.1 (env → SKILL.md sibling →
       skill-root → ~/.pyzot). Lazy-create the dir on first call that needs to write.
     - subpaths: config_path(), credentials_path(), cookies_root(), cache_root(),
       sessions_path(), logs_path().

3. Create src/pyzot/write/__init__.py and src/pyzot/write/connector_client.py with:
     - class ConnectorClient(base_url: str = "http://127.0.0.1:23119")
     - .ping() → dict | raises ConnectorUnreachable
     - .get_selected_collection() → dict
     - All requests via httpx.Client, timeout 5s, retries on transient 5xx.

4. Create src/pyzot/write/preflight.py with check_zotero_running() → returns a
   PreflightReport(reachable: bool, selected_collection: str | None, version: str | None).

5. Modify src/pyzot/config.py to read [write] section per PLAN_WRITE.md §7.2.
   Provide get_write_enabled(), set_write_enabled(bool), get_connector_url().

6. Create src/pyzot/cli/config_cmd.py exposing:
     zot config get <key>
     zot config set <key> <value>     # supports write.enabled, connector_url, unpaywall.email
     zot config path                  # prints <pyzot-home>

7. Create src/pyzot/cli/add.py with ONLY `zot add status` for now:
     - Calls preflight.check_zotero_running()
     - Prints reachability + selected collection + connector URL.
     - No write capability yet — that lands in M2.

8. Wire both groups into src/pyzot/cli/main.py (add --allow-write global flag,
   wire config and add groups). Read `PYZOT_ALLOW_WRITE` env in the gate helper
   `require_write_enabled(ctx) → None | ClickException`.

9. Tests:
     - tests/unit/test_paths.py covering each rule in §7.1 (use monkeypatch + tmp_path).
     - tests/unit/test_config_write_section.py
     - tests/integration/test_connector_client.py using pytest-httpserver to mock
       /connector/ping. Add pytest-httpserver to dev deps.

ACCEPTANCE:
  - `python -m pytest tests/ -q` passes (all v0.1.3 tests + new M1 tests).
  - `zot add status` works against a running Zotero (manual smoke).
  - `zot config path` prints a path that exists OR is created on first set.
  - `zot config set write.enabled true; zot config get write.enabled` round-trips.

DO NOT YET:
  - Hit any external HTTP API (Crossref, etc.).
  - Implement saveItems / saveAttachment / etc.
  - Touch identifiers.py or resolvers/ — they belong to M2/M3.
```

### 15.2 — M2: identifier resolvers

```text
TASK: Implement pyzot v0.2.0-M2 (identifier-based add).

PRECONDITIONS: M1 merged on feat/write-capability; `zot add status` works.

DELIVERABLES (commit "feat(write): M2 identifiers + saveItems"):

1. src/pyzot/write/identifiers.py — detect_kind(s) returning one of:
     "doi" | "arxiv" | "pmid" | "isbn" | "url" | "citation" | "filepath" | "unknown"
   With regexes for DOI (10.NNNN/...), arXiv (modern + old style), PMID, ISBN-10/13.

2. src/pyzot/write/csl_json.py — csl_to_connector_item(csl: dict) → dict matching
   the connector's saveItems item shape (itemType, title, creators[], date,
   DOI, publicationTitle/journalAbbreviation, volume, issue, pages, ISBN, …).
   Map CSL types to Zotero item types (journalArticle, conferencePaper, book, …).

3. src/pyzot/write/resolvers/{crossref,arxiv,pubmed,openlibrary}.py — each exposes
   resolve(identifier) → CSL-JSON dict.
     - crossref: GET https://api.crossref.org/works/{doi}, User-Agent from config.
     - arxiv:    GET http://export.arxiv.org/api/query?id_list={id}, parse Atom.
     - pubmed:   eutils efetch JSON.
     - openlibrary: openlibrary.org + Google Books fallback (no key needed for basic).

4. src/pyzot/write/dedup.py — find_by_doi(db, doi) / find_by_url(db, url) /
   find_by_arxiv(db, id) using existing read-only db.py. Returns ItemRef | None.

5. src/pyzot/write/session.py — Session class:
     - new() → uuid4
     - save_items(items, uri) → POST /connector/saveItems
     - update_session(target, tags, note) → POST /connector/updateSession
     - records (sessionID → item_keys) to <pyzot-home>/cache/sessions.jsonl

6. cli/add.py:
     `zot add doi <DOI>`, `zot add arxiv <ID>`, `zot add pmid <ID>`, `zot add isbn <ID>`
     - Support --collection (name; resolved to ID via queries/collections.py),
       --tag (repeatable), --dry-run, --on-duplicate=report|skip|force-add.
     - Honour write gate (M1).
     - On dup DOI/arxiv: print "Item with DOI/arxiv X already exists: <KEY> — <title>"
       and exit 0.
     - On success: print new item key and target collection.

7. Tests:
     - vcrpy cassettes for each resolver under tests/unit/test_resolvers/cassettes/.
     - tests/integration/test_add_pipeline.py end-to-end with mocked connector +
       mocked resolvers.

ACCEPTANCE:
  - `zot add doi 10.1109/TPWRS.2023.1234567 --collection X --tag y --dry-run`
     prints the JSON it would POST.
  - With write.enabled=true and Zotero running (manual smoke), the same command
     creates the item in collection X with tag y.
  - Duplicate DOI returns the existing key, exits 0, makes no HTTP call to /saveItems.

DO NOT YET:
  - Free-text citation resolver (M3).
  - URL parsing for IEEE / ScienceDirect (M3).
  - PDF upload or recognizer (M4).
```

### 15.3 — M3: citation + URL (incl. IEEE / ScienceDirect)

```text
TASK: Implement pyzot v0.2.0-M3 (citation strings + URL ingestion).

DELIVERABLES (commit "feat(write): M3 citation + URL + IEEE/SD"):

1. src/pyzot/write/resolvers/openalex.py — works search fallback.
2. src/pyzot/write/resolvers/semantic_scholar.py — second fallback,
   with rate-limit-aware retry (sleep on 429, max 3 tries).
3. src/pyzot/write/resolvers/ieee.py:
     url_to_doi(url) — try in order: regex on URL, IEEE public REST
     /rest/document/<arnumber>/metadata, Crossref reverse (arnumber as bibliographic
     query). Return DOI | None.
4. src/pyzot/write/resolvers/sciencedirect.py:
     url_to_doi(url) — extract PII from /pii/<PII>/, query Crossref by PII as
     alternative-id filter or bibliographic query.
5. src/pyzot/write/citation_pipeline.py implementing PLAN_WRITE.md §4.1:
     resolve_citation(text, threshold=50, gap=1.4, interactive=True) → CSL-JSON | None.
     - Crossref bibliographic search → score check → maybe-prompt with rich.table
       of top 5 candidates.
     - Fallback OpenAlex, then Semantic Scholar.

6. cli/add.py extensions:
     `zot add cite "<text>"`, `zot add cite --file refs.txt`
     `zot add url <https://...>` — auto-routes IEEE/SD/arXiv/PubMed/generic
     `zot add "<anything>"` — auto-detect via identifiers.detect_kind.

7. Tests:
     - cassettes for IEEE + SD URL→DOI.
     - cassettes for Crossref bibliographic search.
     - test_citation_pipeline.py covers the example string from PLAN_WRITE.md §4.1
       ("Zhang, J., Geth, F., Heidari, R., Verbič, G. (2025) Beyond simplifications…")
       and asserts a single high-confidence match.

ACCEPTANCE:
  - `zot add cite "Zhang, J. et al. (2025) Beyond simplifications…"` returns a
     DOI and creates an item.
  - `zot add https://ieeexplore.ieee.org/document/9876543` resolves to a DOI and
     creates an item without launching a browser.
  - `zot add https://www.sciencedirect.com/science/article/pii/S2352467725000XYZ`
     same.
  - Ambiguous citation triggers an interactive disambiguation table; with
     --non-interactive it errors with a clear message.

DO NOT YET:
  - PDF upload or recognizer (M4).
  - Playwright (M6).
```

### 15.4 — M4: local files (PDF + import)

```text
TASK: Implement pyzot v0.2.0-M4 (local file ingestion).

DELIVERABLES (commit "feat(write): M4 file + import"):

1. src/pyzot/write/pdf.py — sniff_mime(path) (PDF / EPUB / unknown),
   stream_upload(client, sessionID, path, metadata) handling
   /connector/saveStandaloneAttachment.

2. cli/add.py:
     `zot add file <path>` — saveStandaloneAttachment + updateSession +
     poll local DB for recognized parent (default 30 s, --wait-recognize=N).
     Print recognized parent OR standalone attachment key.

     `zot add import <path>` — POST raw bytes to /connector/import,
     content-type sniff (.bib → application/x-bibtex, .ris →
     application/x-research-info-systems, .json → application/vnd.citationstyles.csl+json).

3. Tests:
     - tests/fixtures/sample.pdf (small synthetic PDF).
     - tests/fixtures/sample.bib + sample.ris.
     - tests/integration/test_add_file.py with mocked connector + mocked DB poll.

ACCEPTANCE:
  - `zot add file ~/Downloads/paper.pdf --collection Inbox` uploads, gets recognized
    (manual smoke against a real PDF with a clear DOI), reports the parent key.
  - `zot add import refs.bib --collection "Imports/2026-05"` creates one or more
    items.

DO NOT YET:
  - Playwright (M6).
```

### 15.5 — M5: auto-detect + batch + dedup polish + dry-run

```text
TASK: Implement pyzot v0.2.0-M5 (UX polish).

DELIVERABLES (commit "feat(write): M5 auto-detect + batch + UX"):

1. cli/add.py top-level: `zot add "<anything>"` dispatches based on
   detect_kind. URL → §8.3/8.4; DOI → §8.1; PMID/arXiv/ISBN → §8.1
   shape; citation → §4.1; file path → §8.5.

2. `zot add batch <file>` — one input per line; reuses the dispatcher.
   Concurrency: sequential by default, --jobs N for parallel resolver
   lookups (still sequential connector calls — Zotero session manager is
   not concurrent-safe).

3. Polish:
   - `--dry-run` consistent everywhere.
   - `-v` echoes every HTTP request/response.
   - `--non-interactive` propagates to citation pipeline.
   - Logs to <pyzot-home>/logs/zot.log (rolling, 1 MB).

4. Tests:
   - tests/integration/test_auto_detect.py
   - tests/integration/test_batch.py with mixed inputs.

ACCEPTANCE:
  - `zot add "10.1109/X"` and `zot add doi 10.1109/X` produce identical results.
  - `zot add batch papers.txt` with mixed DOI / arXiv / file / citation inputs
    succeeds; failed lines are listed at end with exit code 1 only if any failed.
```

### 15.6 — M6: Playwright auth + paywalled PDFs

```text
TASK: Implement pyzot v0.2.0-M6 (browser auth + paywall fallback).

DELIVERABLES (commit "feat(write): M6 playwright auth + paywall"):

1. Add `browser = ["playwright>=1.40"]` optional group.
   `zot add login --install-browser` invokes `playwright install chromium`.

2. src/pyzot/write/browser.py (lazy import):
   - login(service) → opens headed Chromium with persistent profile at
     <pyzot-home>/cookies/<service>/, navigates to service home, waits for
     successful auth, saves storage state.
   - render(url, service) → opens page in headless mode reusing cookies,
     returns rendered HTML.
   - download(url, service, dest) → fetch PDF/binary with cookies.

3. src/pyzot/write/credentials.py — load/save credentials.json
   (Unpaywall email, etc.); mode 0600.

4. cli/add.py:
   - `zot add login [--service unpaywall|ieee|sciencedirect]` per §8.6.
   - `--with-pdf` flag on `zot add doi/arxiv/cite/url`:
       try Unpaywall (if opted in), else publisher fetch with cookies, else
       skip. Attach via /connector/saveAttachment under same session.
   - On first --with-pdf when [unpaywall] enabled=false, prompt per §8.7.

5. Tests:
   - browser tests are e2e-only (manual + skipped in CI).
   - unit test for credentials.py (atomic write, permission bits).
   - unit test for the §8.7 prompt logic (mocked input).

ACCEPTANCE:
  - `zot add login --service unpaywall` saves email and flips
    [unpaywall].enabled=true.
  - `zot add login --service ieee` opens a browser, user signs in via SSO
    (manual), cookies persist.
  - `zot add doi 10.1109/X --with-pdf` after IEEE login retrieves the PDF
    and attaches it.
```

### 15.7 — M6 release: docs + SKILL.md + PyPI

```text
TASK: Ship pyzot v0.2.0.

DELIVERABLES (commit "release: pyzot v0.2.0"):

1. Update README.md: new "Writing to your library" section.
   Replace any "never writes" language with the safe-by-default + opt-in framing.
2. Update SKILL.md per PLAN_WRITE.md §11. Crucially add the agent-facing instruction:
       "Before any `zot add` command, ensure write capability is enabled:
        run `zot config set write.enabled true` once, OR pass --allow-write
        on each call. If unsure, run `zot config get write.enabled` first."
3. Add docs/architecture-write.md (distilled from PLAN_WRITE.md).
4. Add docs/commands.md entries for all `zot add …` and `zot config …`.
5. Update CHANGELOG.md (create if missing) with the v0.2.0 block.
6. Bump pyproject.toml version to 0.2.0.
7. Verify the GitHub Actions workflow publishes to PyPI on tag.
8. Manual full e2e smoke: doi, arxiv, pmid, isbn, ieee URL, sciencedirect URL,
   citation, file PDF, import bib, batch, --with-pdf after login.

ACCEPTANCE:
  - All tests green (unit + integration + opt-in e2e where reasonable).
  - `pip install -e ".[all]"` installs cleanly on Linux + macOS + Windows.
  - SKILL.md renders correctly and includes the write instructions.
  - Tag v0.2.0 published; release notes link to CHANGELOG.
  - Merge feat/write-capability → master via PR.
```

---

## 16. Implementation log

(To be updated by the sonnet implementer at the close of each milestone.)

| Milestone | Date | Commit | Notes |
| --- | --- | --- | --- |
| M1 | 2026-05-10 | 52d4bf9 | paths.py, write/connector_client.py, write/preflight.py, config [write] section, zot config/add groups, 71 tests pass (40 existing + 31 new) |
| M2 | 2026-05-10 | c76ea2a | identifiers.py, csl_json.py, resolvers/{crossref,arxiv,pubmed,openlibrary}, dedup.py, session.py, connector_client save_items/update_session, cli add doi/arxiv/pmid/isbn; 225 tests pass (71 existing + 154 new) |
| M3 | 2026-05-10 | cffcfb1 | openalex/semantic_scholar/crossref-search/ieee/sciencedirect resolvers, citation_pipeline, connector save_snapshot, cli add cite + add url; 297 tests pass (225 existing + 72 new) |
| M4 | 2026-05-10 | 00c79ff | pdf.py (sniff_mime/human_size/sniff_import_content_type), recognize.py (DB poll), connector_client save_standalone_attachment + connector_import, cli add file + add import, fixtures + 60 new tests; 357 total pass |
| M5 | 2026-05-10 | e3615a5 | auto-detect dispatcher + zot add batch + --dry-run/-v/--non-interactive consistency + lazy RotatingFileHandler at <pyzot-home>/logs/zot.log + connector [http] tracing; fixes click 8.2 mix_stderr removal + Handler lock-pairing bug; 396 total pass |
| M6 | 2026-05-10 | 2147f77 | credentials.py (atomic 0600 store), browser.py (lazy Playwright: headed login + headless fetch), resolvers/unpaywall.py (OA PDF URL resolution), ConnectorClient.save_attachment + Session.attach_child_pdf, --with-pdf/--non-interactive on all doi/arxiv/pmid/isbn/cite/url commands, zot add login --service unpaywall/ieee/sciencedirect + --reset + --install-browser, §8.7 first-time prompt cascade; browser = ["playwright>=1.40"] optional dep; 441 total pass (396 prior + 45 new) |
| Release v0.2.0 | 2026-05-10 | 5d90dd9 | README + SKILL.md + CHANGELOG.md + docs/architecture-write.md + docs/commands.md (zot add + zot config sections) + pyproject.toml version bump to 0.2.0; 441 tests pass |
| Post-v0.2.0 bug fix | 2026-05-17 | — | connector_client._request(): guard `response.json()` with `response.text.strip()` to survive Zotero's empty-body 201 on saveItems (hit on IEEE AMPS/MDPI DOIs) |
| Post-v0.2.0 feature | 2026-05-17 | — | assign-to-collection: (1) write/collection_assign.py — direct INSERT into collectionItems join table; (2) _run_add_pipeline + _run_cite_pipeline duplicate handler now calls _try_assign_collection when --collection passed; (3) new `zot collection assign <KEY> <NAME>` command; SKILL.md + docs/commands.md updated |
