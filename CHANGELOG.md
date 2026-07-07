# Changelog

## Unreleased

### Changed

- Rebranded the imported ref src source as `pyzot` while keeping the
  `zot` console command.
- Reduced the write path to connector-based metadata adds, local file adds,
  bibliography imports, citation resolution, and HTTP-only attachment fetches.
- Collapsed the add implementation around auto-detect dispatch with thin
  compatibility wrappers for explicit add subcommands.
- Extracted shared HTTP import and User-Agent helpers for metadata resolvers.

### Removed

- Publisher-specific PDF scraping and login flows.
- Interactive profile management for write-path PDF retrieval.
- Automatic open-access PDF lookup during `zot add`.
- Dedicated publisher and open-access PDF resolver modules.
