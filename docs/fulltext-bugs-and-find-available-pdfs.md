# Full-Text Retrieval: Bugs, Limitations, and Zotero's "Find Available PDFs" — Reverse-Engineered

## 1. Bugs and Failures Encountered

### 1.1 `zot items fulltext` — Saved Cookies Not Used

**Command:** `zot items fulltext <key> --playwright-auth`

**What happened:** Even after running `zot add login --service ieee` and `zot add login --service sciencedirect` (which successfully saved cookies to `~/.zotcli/cookies/ieee` and `~/.zotcli/cookies/sciencedirect`), the fulltext command:

- For **IEEE items** (Source: `network`): uses a plain HTTP request with no cookie injection — always returns the IEEE Xplore paywall wrapper page.
- For **Elsevier/T&F items** (Source: `playwright_auth`): opens a **new interactive Chromium browser** and asks for manual login, ignoring the previously saved sessions entirely.

**Root cause:** `zot items fulltext` and `zot add login` use different credential/cookie systems. The cookies saved by `zot add login` (stored as Playwright persistent profiles in `~/.zotcli/cookies/<service>/`) are never loaded by the fulltext retrieval path.

**Impact:** The command is effectively useless for paywalled content unless the user manually authenticates every single time it's invoked.

---

### 1.2 `zot items fulltext --offline` — SQL Schema Bug

**Command:** `zot items fulltext <key> --offline`

**Error:**
```
sqlite3.OperationalError: no such column: fi.tokenCount
```

**Stack trace origin:** `zotcli/queries/search.py` line 196, inside `get_item_fulltext_with_strategy()`.

**What happened:** The `--offline` flag is supposed to skip network requests and read directly from Zotero's local full-text index (`fulltextItems` / `fulltextWords` tables). The SQL query references a column `fi.tokenCount` that does not exist in the actual Zotero SQLite schema. This crashes **every** invocation of `--offline` regardless of item.

**Impact:** The entire offline fallback path is broken. Items that have local PDFs indexed by Zotero cannot be read via zotcli.

---

### 1.3 `zot add doi --with-pdf` — Skips PDF Download for Existing Items

**Command:** `zot add doi <doi> --with-pdf`

**What happened:** When a DOI already exists in the library, zotcli detects the duplicate, prints:
```
Item with DOI <doi> already exists: <KEY> — <Title>
```
and exits 0 immediately. The `--with-pdf` flag is never evaluated.

**Impact:** There is no built-in way to attach a PDF to an existing Zotero item using zotcli. This is the critical missing operation.

---

### 1.4 `zot items fulltext` — Display-Only, Writes Nothing

**Architectural note:** `zot items fulltext` is a **read-only display command**. Even when it successfully retrieves web content, it prints it to stdout and stores nothing in Zotero. It does not:
- Create PDF attachments
- Update Zotero's full-text index
- Write to the SQLite database

This is a fundamental mismatch: the command name implies "getting full text into the system," but it only fetches and displays for the current terminal session.

---

### 1.5 Summary Table

| Issue | Command | Severity |
|---|---|---|
| Saved cookies not used | `fulltext --playwright-auth` | High — renders auth useless |
| `tokenCount` column missing | `fulltext --offline` | Critical — total crash |
| PDF download skipped for duplicates | `add doi --with-pdf` | High — no attachment path |
| Display-only (no write) | `fulltext` | Architectural gap |

---

## 2. How Zotero's "Find Available PDFs" Actually Works

Source: `zotero/chrome/content/zotero/xpcom/attachments.js`

### 2.1 Entry Point

Right-clicking items → **Find Available PDFs** calls:

```js
Zotero.Attachments.addAvailableFiles(items, options)
// (was addAvailablePDFs — deprecated alias still present)
```

### 2.2 Resolver Pipeline

For each item, `getFileResolvers(item, methods)` builds an ordered resolver list. Default `methods = ['doi', 'url', 'oa', 'custom']`.

```
methods = ['doi', 'url', 'oa', 'custom']
          │       │       │       └── user-defined JSON resolvers (findPDFs.resolvers pref)
          │       │       └── Zotero's Unpaywall mirror: POST https://services.zotero.org/oa/search
          │       └── item URL field → same page-scraping logic
          └── https://doi.org/{doi} → follow redirect → scrape landing page
```

**Resolver 1 — `doi`:**
```js
{ pageURL: 'https://doi.org/' + doi, accessMethod: 'doi' }
```

**Resolver 2 — `url`:**
```js
{ pageURL: item.getField('url'), accessMethod: 'url' }
```

**Resolver 3 — `oa` (most important for automation):**
```js
async function () {
    let urls = await Zotero.Utilities.Internal.getOpenAccessPDFURLs(doi);
    return urls.map(o => ({ url: o.url, pageURL: o.pageURL, version: o.version, accessMethod: 'oa' }));
}
```

Which calls (source: `xpcom/utilities_internal.js:1305`):
```js
POST https://services.zotero.org/oa/search
Content-Type: application/json
{"doi": "<doi>"}
```

Response is an array of objects:
```json
[
  { "url": "https://..../paper.pdf", "pageURL": "https://doi.org/...", "version": "publishedVersion" },
  { "pageURL": "https://repository.../handle/...", "version": "acceptedVersion" }
]
```

Note (from source comment): *"This uses a private API. Please use Unpaywall directly for non-Zotero projects."* The endpoint is Zotero's own mirror of Unpaywall — functionally equivalent but not officially public.

### 2.3 Download Logic — `downloadFirstAvailableFile`

For each resolver result, in order:
1. If `url` present → attempt direct download (3 retries, HTTPS enforced)
2. If only `pageURL` present → load the page → run Zotero's **web translator framework** (760+ site-specific translators) → extract embedded PDF link → download
3. If page resolves directly to a file (`Content-Type: application/pdf`) → save immediately
4. Skip URLs already tried; skip if redirect loop detected (max 10 redirects)
5. Per-domain rate limiting: 1 second between requests to same domain, max 5 consecutive failures before giving up on a domain

### 2.4 Attachment Creation

On success, `addFileFromURLs` creates a **child attachment** on the parent item:
```js
await this.createURLAttachmentFromTemporaryStorageDirectory({
    filename,       // e.g., "Author 2024 - Title.pdf"
    title,          // "Full Text" / "Accepted Version" / etc.
    url,            // source URL
    contentType: mimeType,
    parentItemID: item.id   // ← attached to existing item, NOT new item
});
```

This is the operation zotcli currently cannot replicate: attaching a downloaded file to an existing item rather than creating a new top-level item.

### 2.5 Eligibility Check

`canFindFileForItem(item)` returns false (item skipped) if:
- Item is not a regular item (note, attachment, etc.)
- Item has no DOI and no URL
- Item already has a full-text attachment

---

## 3. OA Availability in `[Paper] LV_UG_Cable_Models_DSSE`

Queried `POST https://services.zotero.org/oa/search` for all 34 items (May 2026):

### Direct PDF URL Available (downloadable without auth)

| Key | DOI | Publisher | PDF URL |
|---|---|---|---|
| MXYF8V3J / NI78AT9N | 10.3390/en19030720 | MDPI | `mdpi.com/.../pdf` |
| FAYD6CEP | 10.1038/s41746-025-01447-y | Nature | `nature.com/articles/....pdf` |
| RSQA3FG3 | 10.1016/j.enrev.2023.100039 | Open archive | `openarchive.usn.no/...` |
| PG37LE9L | 10.1007/s10207-023-00784-x | Springer OA | `link.springer.com/.../pdf` |
| LJ72I96M / HJL9D5GC / D4VHRKAR | 10.3390/electronics12122747 | MDPI | `mdpi.com/.../pdf` |
| 65CP78AC | 10.4204/eptcs.418.2 | EPTCS | `eptcs.web.cse.unsw.edu.au/paper.cgi?....pdf` |
| X2NWGFHZ | 10.3390/en14030774 | MDPI | `mdpi.com/.../pdf` |
| 5SV4BNEQ | 10.1016/j.ijepes.2024.110302 | KU Leuven repo | `lirias.kuleuven.be/retrieve/...` |
| Z44W7H8V | 10.1049/icp.2023.1175 | KU Leuven repo | `lirias.kuleuven.be/retrieve/...` |
| C4YFFB8R | 10.3390/en16237850 | MDPI | `mdpi.com/.../pdf` |
| AFCKZ2DK | 10.1049/dgt2.12020 | Wiley OA | `onlinelibrary.wiley.com/.../pdfdirect/...` |
| M75GKYTD | arXiv:2507.04555 | arXiv | `arxiv.org/pdf/2507.04555` |

### Page URL Only (need translator / institutional access)

| Key | DOI | Publisher | Notes |
|---|---|---|---|
| NNDUCC7L | 10.1016/j.compeleceng.2025.110418 | Elsevier | Possibly OA via institutional proxy |
| 5T4L8DTC | 10.1109/access.2024.3453053 | IEEE Access | IEEE Access is fully OA — direct PDF likely accessible |
| 9M4TBRDB | 10.1016/j.ijepes.2026.111871 | Elsevier | Possibly OA |
| V37HPCTK | 10.1016/j.segan.2024.101331 | Elsevier | Possibly OA |
| VXZLD73U | 10.12688/digitaltwin.17435.2 | F1000Research | OA platform |

### No OA Hit (requires institutional access or purchase)

| Key | DOI | Publisher |
|---|---|---|
| DG4GM75H | 10.1002/j.1538-7305.1926.tb00122.x | Bell Labs (1926) |
| YQKXWLJS | 10.1109/MPE.2023.3330120 | IEEE Magazine |
| 6ZH9FLB4 / CFILXCUV | 10.1109/powercon60995.2024.10870562 | IEEE Conference |
| 3E7PUXV9 / T2UG23KS | 10.1080/00207543.2025.2524516 | Taylor & Francis |
| KTK7UYMY | 10.1109/pesgm48719.2022.9916753 | IEEE Conference |
| 4TH5828T | 10.1080/00207543.2024.2357741 | Taylor & Francis |
| IFFQHWGU | 10.1016/j.jmsy.2022.06.015 | Elsevier |
| XAQNFYHL | 10.1109/tpwrd.2023.3296312 | IEEE |
| GVXSNHG3 | 10.1109/amps66841.2025.11219976 | IEEE Conference (2025) |
| ZV3J33DH | 10.1109/tpwrd.2025.3578065 | IEEE |
| QWRH84Y7 | 10.3403/30308933 | BSI Standard |
| 3LZUG5G9 | 10.1109/tsg.2022.3227602 | IEEE |

---

## 4. How to Replicate "Find Available PDFs" via `zot`

The core gap is step 3: Zotero creates a **child attachment on an existing item**. `zot add file` always creates a new top-level item. Until `zot` supports `zot attachments add <key> <file>`, the workaround is:

### Step 1 — Query OA endpoint

```python
import urllib.request, json

def get_oa_urls(doi):
    req = urllib.request.Request(
        "https://services.zotero.org/oa/search",
        data=json.dumps({"doi": doi}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())
```

### Step 2 — Download direct PDF URLs

For results with a `url` field (direct PDF), download with standard HTTP. For results with only `pageURL`, you need a web translator (Zotero's translator framework) or institutional browser session — this is what Zotero itself handles internally.

### Step 3 — Attach via Zotero connector API (workaround)

Zotero's connector HTTP server at `http://127.0.0.1:23119` exposes an internal API. The relevant endpoint for saving a file to an existing item is not currently exposed through `zot`, but the underlying mechanism is:

```http
POST http://127.0.0.1:23119/connector/saveSnapshot
```

A cleaner approach when the `zot attachments add` command exists:
```bash
zot attachments add <key> /tmp/downloaded.pdf
```

### Step 4 — Custom resolvers (Zotero pref)

For institutional resolvers (e.g., a university proxy that can resolve DOIs), Zotero supports a `findPDFs.resolvers` preference containing JSON:

```json
[{
  "name": "My Resolver",
  "method": "GET",
  "url": "https://proxy.myuniversity.edu/doi/{doi}",
  "mode": "html",
  "selector": "a.pdf-link",
  "attribute": "href"
}]
```

This is set via **Edit → Preferences → Advanced → Config Editor** → search `findPDFs.resolvers`.

### Practical Shell Script for OA Items

For the subset of items that have direct OA PDF URLs, this script can download and attempt to attach via `zot add file`:

```bash
#!/usr/bin/env bash
# Downloads OA PDFs and adds to Zotero (creates new items — NOT child attachments)
# Until `zot attachments add <key> <file>` exists, manual collection assignment needed

COLLECTION="[Paper] LV_UG_Cable_Models_DSSE"
TMPDIR=$(mktemp -d)

python3 << 'EOF'
import urllib.request, json, subprocess, os, sys

items = {
    "MXYF8V3J": "10.3390/en19030720",
    "FAYD6CEP": "10.1038/s41746-025-01447-y",
    # ... add remaining DOIs
}

for key, doi in items.items():
    req = urllib.request.Request(
        "https://services.zotero.org/oa/search",
        data=json.dumps({"doi": doi}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        results = json.loads(r.read())
    
    direct = next((x["url"] for x in results if x.get("url")), None)
    if direct:
        print(f"{key}: {direct}")
        # Download
        outfile = f"/tmp/zot_oa_{key}.pdf"
        urllib.request.urlretrieve(direct, outfile)
        # Attempt to attach (creates new recognized item via Zotero)
        subprocess.run(["zot", "add", "file", outfile, "--wait-recognize", "30"], check=False)
EOF
```

---

## 5. Required `zotcli` Feature: `zot attachments add`

To fully replicate "Find Available PDFs," zotcli needs:

```
zot attachments add <key> <file_path>
```

Which would:
1. Send the file to Zotero's connector as a child attachment of item `<key>`
2. Use `parentItemID` when creating the attachment (same as Zotero does internally via `createURLAttachmentFromTemporaryStorageDirectory`)

Connector API endpoint to target: `POST http://127.0.0.1:23119` — see Zotero's `xpcom/server/` for protocol details.

Until this exists, the only path for attaching PDFs to existing items is the Zotero desktop app's own "Find Available PDFs" menu action.
