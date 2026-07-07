"""Unit tests for src/zotcli/write/credentials.py.

Uses tmp_path + monkeypatch.setenv("ZOTCLI_HOME", ...) so the real
<zotcli-home> is never touched.
"""

from __future__ import annotations

import json
import os
import platform
import stat

import pytest


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Redirect ZOTCLI_HOME to a temp directory for every test."""
    monkeypatch.setenv("ZOTCLI_HOME", str(tmp_path))
    # Reload paths module cache (zotcli_home() reads the env var at call time, so OK)
    yield tmp_path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _creds():
    """Import credentials module fresh (to avoid any module-level caching)."""
    from zotcli.write import credentials
    return credentials


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------

class TestLoad:
    def test_returns_empty_dict_when_no_file(self, tmp_path):
        creds = _creds()
        result = creds.load()
        assert result == {}

    def test_returns_parsed_json(self, tmp_path):
        p = tmp_path / "credentials.json"
        p.write_text('{"services": {"unpaywall": {"email": "a@b.com"}}}', encoding="utf-8")
        creds = _creds()
        result = creds.load()
        assert result == {"services": {"unpaywall": {"email": "a@b.com"}}}

    def test_returns_empty_dict_on_invalid_json(self, tmp_path):
        p = tmp_path / "credentials.json"
        p.write_text("not json", encoding="utf-8")
        creds = _creds()
        result = creds.load()
        assert result == {}

    def test_returns_empty_dict_when_top_level_is_list(self, tmp_path):
        p = tmp_path / "credentials.json"
        p.write_text('[1, 2, 3]', encoding="utf-8")
        creds = _creds()
        result = creds.load()
        assert result == {}


# ---------------------------------------------------------------------------
# save()
# ---------------------------------------------------------------------------

class TestSave:
    def test_creates_file(self, tmp_path):
        creds = _creds()
        data = {"services": {"unpaywall": {"email": "x@y.com"}}}
        creds.save(data)
        p = tmp_path / "credentials.json"
        assert p.exists()
        loaded = json.loads(p.read_text())
        assert loaded == data

    def test_atomic_write_replaces_existing(self, tmp_path):
        creds = _creds()
        p = tmp_path / "credentials.json"
        p.write_text('{"old": true}', encoding="utf-8")
        creds.save({"new": True})
        loaded = json.loads(p.read_text())
        assert loaded == {"new": True}
        assert "old" not in loaded

    def test_no_tmp_file_left_on_success(self, tmp_path):
        creds = _creds()
        creds.save({"x": 1})
        leftovers = list(tmp_path.glob("*.tmp"))
        assert leftovers == []

    @pytest.mark.skipif(platform.system() == "Windows", reason="POSIX-only mode check")
    def test_file_mode_0600_on_posix(self, tmp_path):
        creds = _creds()
        creds.save({"test": True})
        p = tmp_path / "credentials.json"
        mode = stat.S_IMODE(p.stat().st_mode)
        assert mode == 0o600, f"Expected 0o600, got {oct(mode)}"


# ---------------------------------------------------------------------------
# get() / set()
# ---------------------------------------------------------------------------

class TestGetSet:
    def test_set_and_get_roundtrip(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "user@example.com")
        assert creds.get("unpaywall", "email") == "user@example.com"

    def test_get_returns_none_for_missing_service(self, tmp_path):
        creds = _creds()
        assert creds.get("nonexistent", "key") is None

    def test_get_returns_none_for_missing_key(self, tmp_path):
        creds = _creds()
        creds.set("ieee", "logged_in_at", "2026-05-10T00:00:00Z")
        assert creds.get("ieee", "nonexistent_key") is None

    def test_set_multiple_services(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "a@b.com")
        creds.set("ieee", "logged_in_at", "2026-05-10T00:00:00Z")
        creds.set("sciencedirect", "logged_in_at", "2026-05-11T00:00:00Z")

        assert creds.get("unpaywall", "email") == "a@b.com"
        assert creds.get("ieee", "logged_in_at") == "2026-05-10T00:00:00Z"
        assert creds.get("sciencedirect", "logged_in_at") == "2026-05-11T00:00:00Z"

    def test_set_overwrites_existing_value(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "old@example.com")
        creds.set("unpaywall", "email", "new@example.com")
        assert creds.get("unpaywall", "email") == "new@example.com"

    def test_set_persists_to_disk(self, tmp_path):
        creds = _creds()
        creds.set("ieee", "logged_in_at", "2026-01-01T00:00:00Z")
        p = tmp_path / "credentials.json"
        assert p.exists()
        data = json.loads(p.read_text())
        assert data["services"]["ieee"]["logged_in_at"] == "2026-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------

class TestClear:
    def test_clear_removes_service(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "x@y.com")
        creds.clear("unpaywall")
        assert creds.get("unpaywall", "email") is None

    def test_clear_does_not_affect_other_services(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "x@y.com")
        creds.set("ieee", "logged_in_at", "2026-05-10T00:00:00Z")
        creds.clear("unpaywall")
        assert creds.get("ieee", "logged_in_at") == "2026-05-10T00:00:00Z"

    def test_clear_nonexistent_service_is_noop(self, tmp_path):
        creds = _creds()
        # Should not raise
        creds.clear("nonexistent_service")

    def test_clear_persists_to_disk(self, tmp_path):
        creds = _creds()
        creds.set("unpaywall", "email", "x@y.com")
        creds.clear("unpaywall")
        p = tmp_path / "credentials.json"
        data = json.loads(p.read_text())
        assert "unpaywall" not in data.get("services", {})
