# CLAUDE.md

See [AGENTS.md](AGENTS.md) for the canonical working agreement: build/test
commands, conventions, and repository layout. That file is the source of truth;
this pointer exists so Claude Code picks it up automatically.

Quick reference:

- Install: `just setup` (uv-managed)
- Before committing: `just check` and `just test` must both pass
- Commits: Conventional Commits, small and granular
- Reads are read-only against `zotero.sqlite`; writes go through the Zotero
  connector only
