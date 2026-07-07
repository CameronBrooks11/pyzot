# pyzot task runner.
# All recipes run through uv so local and CI behavior match exactly.

# Show available recipes.
default:
    @just --list

# Install dependencies (all extras + dev group) into the uv environment.
setup:
    uv sync --all-extras

# Format code in place.
fmt:
    uv run ruff format .

# Lint and apply safe autofixes.
lint:
    uv run ruff check --fix .

# Type-check the package with mypy.
typecheck:
    uv run mypy

# CI-equivalent gate: format check + lint + typecheck.
check:
    uv run ruff format --check .
    uv run ruff check .
    uv run mypy

# Run the test suite (needs the feature extras for full coverage).
test:
    uv run --all-extras pytest -q

# Build and serve the documentation locally.
docs:
    uv run --extra docs mkdocs serve
