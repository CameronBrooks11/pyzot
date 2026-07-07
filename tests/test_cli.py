"""CLI integration tests using CliRunner."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from click.testing import CliRunner

from pyzot.cli.main import cli


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    p = tmp_path / "zotero.sqlite"
    from tests.conftest import _seed_db

    conn = sqlite3.connect(str(p))
    _seed_db(conn)
    conn.commit()
    conn.close()
    return p


def run(db_path: Path, *args, env: dict[str, str] | None = None):
    runner = CliRunner()
    return runner.invoke(
        cli,
        ["--db", str(db_path), "--no-color", *args],
        catch_exceptions=False,
        env=env,
    )


def test_stats(db_path: Path):
    result = run(db_path, "stats")
    assert result.exit_code == 0
    assert "Items" in result.output


def test_collections_list(db_path: Path):
    result = run(db_path, "collections", "list")
    assert result.exit_code == 0
    assert "PhD" in result.output


def test_collections_list_flat(db_path: Path):
    result = run(db_path, "collections", "list", "--flat")
    assert result.exit_code == 0
    assert "NLP" in result.output


def test_items_list(db_path: Path):
    result = run(db_path, "items", "list")
    assert result.exit_code == 0
    assert "Deep Learning" in result.output


def test_items_show(db_path: Path):
    result = run(db_path, "items", "show", "1")
    assert result.exit_code == 0
    assert "Deep Learning for NLP" in result.output


def test_search(db_path: Path):
    result = run(db_path, "search", "Python")
    assert result.exit_code == 0
    assert "Python Programming" in result.output


def test_search_tag(db_path: Path):
    result = run(db_path, "search", "--tag", "nlp")
    assert result.exit_code == 0
    assert "Deep Learning" in result.output


def test_search_doi(db_path: Path):
    result = run(db_path, "search", "--doi", "10.1038/example")
    assert result.exit_code == 0
    assert "Deep Learning" in result.output


def test_stats_tags(db_path: Path):
    result = run(db_path, "stats", "tags")
    assert result.exit_code == 0
    assert "machine-learning" in result.output


def test_export_json(db_path: Path, tmp_path: Path):
    out = tmp_path / "out.json"
    result = run(db_path, "export", "json", "--all", "--output", str(out))
    assert result.exit_code == 0
    import json

    data = json.loads(out.read_text())
    assert len(data) == 3


def test_export_bib(db_path: Path, tmp_path: Path):
    out = tmp_path / "out.bib"
    result = run(db_path, "export", "bib", "--all", "--output", str(out))
    assert result.exit_code == 0
    content = out.read_text()
    assert "@article" in content


def test_export_markdown(db_path: Path, tmp_path: Path):
    out = tmp_path / "out.md"
    result = run(db_path, "export", "markdown", "--all", "--output", str(out))
    assert result.exit_code == 0
    content = out.read_text()
    assert "Deep Learning" in content


def test_items_fulltext(db_path: Path):
    result = run(db_path, "items", "fulltext", "1", "--offline")
    assert result.exit_code == 0
    # With no .zotero-ft-cache file in the fixture, the metadata fallback
    # runs and returns the title + abstract + notes.
    assert "Source: metadata" in result.output
    assert "Deep Learning for NLP" in result.output


def test_config_library_auth_set_and_show(db_path: Path, tmp_path: Path):
    env = {"XDG_CONFIG_HOME": str(tmp_path / "cfg"), "HOME": str(tmp_path / "home")}
    set_result = run(
        db_path,
        "config",
        "library-auth",
        "--library",
        "1",
        "--institution",
        "Test University",
        "--username",
        "test.user",
        "--password",
        "secret",
        env=env,
    )
    assert set_result.exit_code == 0
    assert "Saved auth details for library 1." in set_result.output

    show_result = run(db_path, "config", "library-auth", "--library", "1", "--show", env=env)
    assert show_result.exit_code == 0
    assert "Test University" in show_result.output
    assert "test.user" in show_result.output
    assert "******" in show_result.output
