"""Unit tests for pyzot.paths — pyzot_home() resolution rules."""

from __future__ import annotations

from pathlib import Path

# ---------------------------------------------------------------------------
# Rule 1: PYZOT_HOME env var
# ---------------------------------------------------------------------------


def test_env_override(monkeypatch, tmp_path):
    """PYZOT_HOME env var is used when set."""
    custom_home = tmp_path / "my_pyzot_home"
    monkeypatch.setenv("PYZOT_HOME", str(custom_home))

    # Re-import to get a fresh call (function reads env each time)
    import importlib

    import pyzot.paths as paths_mod

    importlib.reload(paths_mod)
    from pyzot.paths import pyzot_home

    result = pyzot_home()
    assert result == custom_home


def test_env_override_returns_exact_path(monkeypatch, tmp_path):
    """PYZOT_HOME returns the path as-is (does not append .pyzot)."""
    custom = tmp_path / "custom"
    monkeypatch.setenv("PYZOT_HOME", str(custom))

    from pyzot.paths import pyzot_home

    result = pyzot_home()
    assert result == custom


# ---------------------------------------------------------------------------
# Rule 2: repository sentinel search
# ---------------------------------------------------------------------------


def test_repo_root_detection(monkeypatch, tmp_path):
    """When pyproject.toml is found in a parent, use <repo-root>/.pyzot."""
    repo_root = tmp_path / "my_repo"
    repo_root.mkdir()
    (repo_root / "pyproject.toml").write_text("[project]\nname = 'pyzot'\n")

    # Place a fake paths.py location inside the repo root
    fake_src = repo_root / "src" / "pyzot"
    fake_src.mkdir(parents=True)
    fake_paths_file = fake_src / "paths.py"
    fake_paths_file.write_text("")

    # Clear env
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    # Monkey-patch Path(__file__) by patching _find_repo_root to return repo_root
    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: repo_root)

    from pyzot.paths import pyzot_home

    result = pyzot_home()
    assert result == repo_root / ".pyzot"


def test_repo_root_not_found_falls_through(monkeypatch, tmp_path):
    """When repo root is not found, fall through to Path.home() / .pyzot."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import pyzot_home

    result = pyzot_home()
    assert result == tmp_path / ".pyzot"


# ---------------------------------------------------------------------------
# Rule 3 (fallback): Path.home() / ".pyzot"
# ---------------------------------------------------------------------------


def test_fallback_to_home(monkeypatch, tmp_path):
    """When no env var and no repo root found, fallback to ~/.pyzot."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    # Patch Path.home() to return tmp_path so we don't write to real home
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import pyzot_home

    result = pyzot_home()
    assert result == tmp_path / ".pyzot"


def test_fallback_does_not_create_dir(monkeypatch, tmp_path):
    """pyzot_home() itself does not create the directory."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import pyzot_home

    result = pyzot_home()
    # Directory should NOT exist yet — pyzot_home() is pure
    assert not result.exists()


# ---------------------------------------------------------------------------
# Sub-path helpers — creation side-effects
# ---------------------------------------------------------------------------


def test_config_path_creates_parent(monkeypatch, tmp_path):
    """config_path() creates the parent directory."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import config_path

    p = config_path()
    assert p.parent.exists()
    assert p.name == "config.toml"


def test_cache_root(monkeypatch, tmp_path):
    """cache_root() creates and returns the cache directory."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import cache_root

    p = cache_root()
    assert p.exists()
    assert p.name == "cache"


def test_sessions_path(monkeypatch, tmp_path):
    """sessions_path() returns path ending in sessions.jsonl."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import sessions_path

    p = sessions_path()
    assert p.name == "sessions.jsonl"
    assert p.parent.exists()


def test_logs_path(monkeypatch, tmp_path):
    """logs_path() returns path ending in zot.log."""
    monkeypatch.delenv("PYZOT_HOME", raising=False)

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "_find_repo_root", lambda: None)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    from pyzot.paths import logs_path

    p = logs_path()
    assert p.name == "zot.log"
    assert p.parent.exists()
