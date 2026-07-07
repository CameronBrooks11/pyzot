# AGENTS.md

Canonical working agreement for humans and AI agents contributing to this
repository. This is the source of truth for how to build, test, and change the
project. Tool-specific files (for example the root `CLAUDE.md`) point here.

## What this project is

`pyzot` (`zot` on the command line) is a CLI and small SDK for a local
[Zotero](https://www.zotero.org/) library.

- **Reads** query `zotero.sqlite` directly in read-only mode (`mode=ro`,
  `PRAGMA query_only=ON`).
- **Writes** are opt-in and go through Zotero's local connector HTTP server;
  `zotero.sqlite` is never mutated directly by the add pipeline.

It is a derivative of MohamedNumair's MIT-licensed `zotcli`; see `LICENSE` and
the provenance note in `README.md`.

## Environment and commands

This project uses [`uv`](https://docs.astral.sh/uv/) for dependency management
and [`just`](https://github.com/casey/just) as the task runner. Runtime
dependencies are minimal; optional features live in extras
(`bibtex`, `export`, `write`, `docs`) and dev tooling lives in the `dev`
dependency group (synced by default).

- `just setup` — install all extras + dev group via uv
- `just fmt` — format code (ruff)
- `just lint` — lint with autofix (ruff)
- `just typecheck` — static type check (mypy)
- `just check` — CI-equivalent gate: `ruff format --check` + `ruff check` + `mypy`
- `just test` — run the test suite (pytest, with all extras)
- `just docs` — build and serve the mkdocs site locally

Always run `just check` and `just test` before committing. Both must be green.

## Conventions

- Commit messages: Conventional Commits (`type(scope): description`), imperative
  mood, lowercase, no trailing period. Types: `feat`, `fix`, `docs`, `refactor`,
  `test`, `chore`, `ci`, `build`, `style`. One logical change per commit.
- Code style: edit only what a change needs; do not refactor or re-annotate
  untouched code. Keep the runtime dependency set small — prefer the stdlib or
  an existing dependency before adding a new one.
- Read path stays read-only: never open `zotero.sqlite` for writing. All item
  creation goes through the connector client under `src/pyzot/write/`.
- Docs filenames use kebab-case.

## Layout

```text
src/pyzot/
  cli/        Click commands
  queries/    read-only SQLite query layer
  export/     JSON/CSV/BibTeX/Markdown exporters
  write/      connector client, add pipeline, resolvers, attachment helpers
tests/        unit and integration tests
docs/         maintainer and command documentation (mkdocs)
```

## CI

Three GitHub Actions workflows live under `.github/workflows/`:

- `ci.yml` — on push to `main` and PRs: `just check` (format, lint, types) plus
  `just test` across a Python 3.10–3.13 matrix.
- `docs.yml` — on push to `main` touching docs/source: `mkdocs gh-deploy` to
  GitHub Pages.
- `release.yml` — on a `v*.*.*` tag: `uv build`, publish to PyPI via trusted
  publishing (OIDC), and create a GitHub release. Requires a PyPI trusted
  publisher configured for this repo/workflow.

All workflows run through uv + `just` so CI matches the local gate.
