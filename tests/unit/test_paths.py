"""Unit tests for zotcli.paths — zotcli_home() resolution rules (§7.1)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Rule 1: ZOTCLI_HOME env var
# ---------------------------------------------------------------------------

def test_env_override(monkeypatch, tmp_path):
    """ZOTCLI_HOME env var is used when set."""
    custom_home = tmp_path / "my_zotcli_home"
    monkeypatch.setenv("ZOTCLI_HOME", str(custom_home))

    # Re-import to get a fresh call (function reads env each time)
    import importlib
    import zotcli.paths as paths_mod
    importlib.reload(paths_mod)
    from zotcli.paths import zotcli_home

    result = zotcli_home()
    assert result == custom_home


def test_env_override_returns_exact_path(monkeypatch, tmp_path):
    """ZOTCLI_HOME returns the path as-is (does not append .zotcli)."""
    custom = tmp_path / "custom"
    monkeypatch.setenv("ZOTCLI_HOME", str(custom))

    from zotcli.paths import zotcli_home
    result = zotcli_home()
    assert result == custom


# ---------------------------------------------------------------------------
# Rule 2: SKILL.md sibling search
# ---------------------------------------------------------------------------

def test_skill_md_sibling_detection(monkeypatch, tmp_path):
    """When SKILL.md is found in a parent of __file__, use <skill-root>/.zotcli."""
    # Set up a fake skill root with SKILL.md
    skill_root = tmp_path / "my_skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("skill")

    # Place a fake paths.py location inside the skill root
    fake_src = skill_root / "src" / "zotcli"
    fake_src.mkdir(parents=True)
    fake_paths_file = fake_src / "paths.py"
    fake_paths_file.write_text("")

    # Clear env
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    # Monkey-patch Path(__file__) by patching _find_skill_root to return skill_root
    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: skill_root)

    from zotcli.paths import zotcli_home
    result = zotcli_home()
    assert result == skill_root / ".zotcli"


def test_skill_md_not_found_falls_through(monkeypatch, tmp_path):
    """When SKILL.md is not found, fall through to Path.home() / .zotcli."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import zotcli_home
    result = zotcli_home()
    assert result == tmp_path / ".zotcli"


# ---------------------------------------------------------------------------
# Rule 3 (fallback): Path.home() / ".zotcli"
# ---------------------------------------------------------------------------

def test_fallback_to_home(monkeypatch, tmp_path):
    """When no env var and no SKILL.md found, fallback to ~/.zotcli."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    # Patch Path.home() to return tmp_path so we don't write to real home
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import zotcli_home
    result = zotcli_home()
    assert result == tmp_path / ".zotcli"


def test_fallback_does_not_create_dir(monkeypatch, tmp_path):
    """zotcli_home() itself does not create the directory."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import zotcli_home
    result = zotcli_home()
    # Directory should NOT exist yet — zotcli_home() is pure
    assert not result.exists()


# ---------------------------------------------------------------------------
# Sub-path helpers — creation side-effects
# ---------------------------------------------------------------------------

def test_config_path_creates_parent(monkeypatch, tmp_path):
    """config_path() creates the parent directory."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import config_path
    p = config_path()
    assert p.parent.exists()
    assert p.name == "config.toml"


def test_credentials_path(monkeypatch, tmp_path):
    """credentials_path() returns a path named credentials.json."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import credentials_path
    p = credentials_path()
    assert p.name == "credentials.json"
    assert p.parent.exists()


def test_cookies_root(monkeypatch, tmp_path):
    """cookies_root() creates and returns the cookies directory."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import cookies_root
    p = cookies_root()
    assert p.exists()
    assert p.name == "cookies"


def test_cache_root(monkeypatch, tmp_path):
    """cache_root() creates and returns the cache directory."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import cache_root
    p = cache_root()
    assert p.exists()
    assert p.name == "cache"


def test_sessions_path(monkeypatch, tmp_path):
    """sessions_path() returns path ending in sessions.jsonl."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import sessions_path
    p = sessions_path()
    assert p.name == "sessions.jsonl"
    assert p.parent.exists()


def test_logs_path(monkeypatch, tmp_path):
    """logs_path() returns path ending in zot.log."""
    monkeypatch.delenv("ZOTCLI_HOME", raising=False)

    import zotcli.paths as paths_mod
    monkeypatch.setattr(paths_mod, "_find_skill_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from zotcli.paths import logs_path
    p = logs_path()
    assert p.name == "zot.log"
    assert p.parent.exists()
