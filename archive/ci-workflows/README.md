# Archived CI workflows

These are stored here **outside** `.github/workflows/`, so GitHub does
**not** run them — they are kept for reference only.

- `docs.yml` — upstream mkdocs deploy to GitHub Pages (fired on push to main).
- `publish.yml` — upstream PyPI trusted-publishing release (fired on `v*.*.*` tags).

To reactivate any of these for this repository, move the file back into
`.github/workflows/` and configure the required secrets / Pages / trusted
publishing for the `CameronBrooks11/pyzot` project.
