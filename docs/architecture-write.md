# Write-path architecture

This document describes the design of `zotcli`'s opt-in write capability (v0.2.0). For the full design history, rationale, and locked decisions see [`PLAN_WRITE.md`](../PLAN_WRITE.md).

---

## Why not write to SQLite directly?

Zotero is not "just SQLite". A new item touches a dozen interrelated tables (`items`, `itemData`, `creators`, `itemAttachments`, `syncCache`, `objectVersions`, …) and Zotero maintains an EXCLUSIVE WAL lock while running. The community and Zotero's own documentation are unambiguous: **never write to `zotero.sqlite` from a third-party tool**.

Therefore all writes go through Zotero's own connector HTTP server.

---

## Primary write path — Zotero connector HTTP server

Zotero ships a local HTTP server at `127.0.0.1:23119`. Endpoints used by zotcli:

| Endpoint | Purpose |
|---|---|
| `GET  /connector/ping` | Liveness check (preflight) |
| `GET  /connector/getSelectedCollection` | Reports current target library/collection |
| `POST /connector/saveItems` | Save a parent item from CSL-ish JSON payload |
| `POST /connector/saveSnapshot` | Save a webpage snapshot (generic URL fallback) |
| `POST /connector/saveStandaloneAttachment` | Stream a binary file; Zotero auto-runs `RecognizeDocument` |
| `POST /connector/saveAttachment` | Attach a child file to a previously saved parent session |
| `POST /connector/import` | Stream RIS / BibTeX / CSL-JSON bytes; Zotero auto-detects format |
| `POST /connector/updateSession` | Re-target saved items to a specific collection; add tags |

Auth: none (loopback only).

---

## System diagram

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
│  zotcli.write.connector_client                                    │
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

---

## Source coverage matrix

| Source | Metadata path | PDF retrieval |
|---|---|---|
| DOI (any publisher) | Crossref `/works/<doi>` → CSL-JSON | Unpaywall for OA; publisher cookies for paywall |
| arXiv | arXiv Atom feed → CSL-JSON | Direct PDF (always OA) |
| PubMed | NCBI eutils efetch → CSL-JSON | Unpaywall for full text |
| ISBN | OpenLibrary + Google Books → CSL-JSON | N/A |
| IEEE Xplore URL | Extract DOI from URL → Crossref; fallback Playwright snapshot | Unpaywall OA; institutional SSO cookies |
| ScienceDirect URL | Extract PII → Crossref; fallback Playwright snapshot | Unpaywall OA; Elsevier SSO cookies |
| Free-text citation | Crossref bibliographic search → DOI → above; fallback OpenAlex → Semantic Scholar | Unpaywall on resolved DOI |
| Generic URL | `saveSnapshot` (Zotero translators run on fetched HTML) | N/A |
| Local PDF / EPUB | `saveStandaloneAttachment` → Zotero `RecognizeDocument` | File is the attachment |
| RIS / BibTeX / CSL-JSON | `import` endpoint (Zotero auto-detects format) | N/A |

**Key insight:** IEEE Xplore and ScienceDirect DOIs are always registered with Crossref, so metadata is retrievable without a browser. A browser is only needed to retrieve paywalled PDFs.

---

## Citation-string resolver pipeline

Free-text citation strings (e.g. `"Zhang, J. et al. (2025) Beyond simplifications…"`) are resolved in order:

1. Crossref `GET /works?query.bibliographic=<text>&rows=5&select=DOI,title,author,issued,score`
2. Score check: accept top result if `score >= 50` AND `score / next_score >= 1.4`.
3. If ambiguous: render top 5 candidates in a `rich.table` and prompt the user (or error with `--non-interactive`).
4. If Crossref returns nothing: fall back to OpenAlex `/works?search=…`.
5. If OpenAlex empty: Semantic Scholar `/graph/v1/paper/search` (rate-limit-aware, max 3 retries on 429).
6. Once a DOI is resolved, the standard DOI flow takes over.

---

## Module layout

```text
src/zotcli/
├── paths.py                    ← zotcli_home() resolution (§7.1)
├── config.py                   ← reads [write], [unpaywall], [browser] sections
├── cli/
│   ├── add.py                  ← `zot add` group + auto-detect dispatcher
│   ├── config_cmd.py           ← `zot config get/set/path`
│   └── main.py                 ← root cli + --allow-write global flag
└── write/
    ├── connector_client.py     ← httpx client for all /connector/* calls
    ├── preflight.py            ← ping + selected-collection probe
    ├── session.py              ← sessionID lifecycle + updateSession
    ├── csl_json.py             ← CSL-JSON ↔ Zotero connector item shape
    ├── identifiers.py          ← detect_kind(input) dispatcher
    ├── citation_pipeline.py    ← free-text citation → DOI
    ├── dedup.py                ← read-only duplicate check against local DB
    ├── pdf.py                  ← MIME sniff + streaming upload helper
    ├── browser.py              ← Playwright headed window (lazy import)
    ├── credentials.py          ← atomic file-based credential store (mode 0600)
    └── resolvers/
        ├── crossref.py
        ├── arxiv.py
        ├── pubmed.py
        ├── openlibrary.py
        ├── openalex.py
        ├── semantic_scholar.py
        ├── unpaywall.py
        ├── ieee.py
        └── sciencedirect.py
```

---

## Self-contained data directory

`zotcli_home()` resolves in order:

1. `ZOTCLI_HOME` env var (if set and writable).
2. Walk up from `Path(__file__).parent` looking for a sibling `SKILL.md`; use `<that-dir>/.zotcli/`.
3. Final fallback: `Path.home() / ".zotcli"` — identical on Linux, macOS, Windows; no `platformdirs` / XDG / AppData branching.

```text
<zotcli-home>/
  config.toml               # [write], [unpaywall], [browser], [database], [resolvers]
  credentials.json          # Unpaywall email, service markers — mode 0600
  cookies/                  # Playwright persistent profiles
  │   ├── ieee/
  │   ├── sciencedirect/
  │   └── default/
  cache/
  │   ├── crossref/         # keyed by DOI
  │   ├── openalex/
  │   └── sessions.jsonl    # sessionID → item keys (idempotency)
  └── logs/
      └── zot.log           # rotating, 1 MB × 3 backups
```

`zot config path` prints `<zotcli-home>`. The directory is created lazily on first write.

---

## Write gate

All write commands check the write gate before any network call:

```
write.enabled = false        (default — read-only install)
```

Enable once: `zot config set write.enabled true` (persists to `config.toml`).
Ad-hoc override: `--allow-write` flag or `ZOTCLI_ALLOW_WRITE=1` environment variable.

---

## Safety guarantees

- `zotero.sqlite` is opened `mode=ro` + `PRAGMA query_only=ON` — impossible to corrupt via direct SQL.
- All mutations go through Zotero's own connector; Zotero performs every database transaction and maintains sync state.
- Idempotency: `sessionID → item keys` recorded in `cache/sessions.jsonl`.
- Duplicate DOI: report existing key + title and exit 0; no mutation (default `on_duplicate = "report"`).
- Credentials at rest in `credentials.json` with mode 0600 (POSIX) / best-effort ACL (Windows).
- Playwright browser is only launched for auth and paywalled-PDF retrieval — never for primary metadata.

---

## Optional dependencies

| Extra | Package | Required for |
|---|---|---|
| `write` | `httpx>=0.27` | All `zot add …` commands |
| `browser` | `playwright>=1.40` | `zot add login`, `--with-pdf` on paywalled content |

Install: `pip install "zotcli[write]"`, `pip install "zotcli[browser]"`, or `pip install "zotcli[all]"`.

---

## v0.3 roadmap

Items deferred from v0.2.0:

- **Edit / delete existing items** — requires either a Zotero `.xpi` plugin with a custom endpoint, or waiting for the local API to gain write support, or using the web API with a user-supplied key.
- **Parallel connector calls in `zot add batch`** — `--jobs N` is accepted but is currently a no-op; sequential connector calls are safe; parallel resolver lookups deferred.
- **Group library targeting** — `updateSession` supports `L`/`U`/`G` ID prefixes; polishing deferred.

See `PLAN_WRITE.md §12` for the full roadmap.
