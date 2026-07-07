"""Unit tests for the [write] section in config.py.

Tests:
- Round-trip set_write_enabled / get_write_enabled
- Default values (False, connector URL)
- Atomic write (temp file replaced)
- get_config_value / set_config_value for arbitrary keys
- get_connector_url
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def isolated_config(monkeypatch, tmp_path):
    """Redirect all paths to tmp_path so tests don't touch real config."""
    # Patch pyzot_home to return tmp_path / ".pyzot"
    fake_home = tmp_path / ".pyzot"

    import pyzot.paths as paths_mod

    monkeypatch.setattr(paths_mod, "pyzot_home", lambda: fake_home)

    # Also patch in config.py's reference to paths
    import pyzot.config as cfg_mod

    monkeypatch.setattr(
        cfg_mod,
        "_write_config_path",
        lambda: fake_home / "config.toml",
    )
    yield fake_home


# ---------------------------------------------------------------------------
# get_write_enabled defaults
# ---------------------------------------------------------------------------


def test_write_enabled_default_false():
    """Default value of write.enabled is False."""
    from pyzot.config import get_write_enabled

    assert get_write_enabled() is False


def test_connector_url_default():
    """Default connector URL is the standard Zotero loopback."""
    from pyzot.config import get_connector_url

    assert get_connector_url() == "http://127.0.0.1:23119"


# ---------------------------------------------------------------------------
# Round-trip set / get
# ---------------------------------------------------------------------------


def test_set_and_get_write_enabled_true():
    """set_write_enabled(True) persists and get_write_enabled() returns True."""
    from pyzot.config import get_write_enabled, set_write_enabled

    set_write_enabled(True)
    assert get_write_enabled() is True


def test_set_and_get_write_enabled_false():
    """set_write_enabled(False) can disable after enabling."""
    from pyzot.config import get_write_enabled, set_write_enabled

    set_write_enabled(True)
    set_write_enabled(False)
    assert get_write_enabled() is False


def test_round_trip_persists_to_file(isolated_config):
    """After set_write_enabled(True), the config file exists and contains 'true'."""
    from pyzot.config import set_write_enabled

    set_write_enabled(True)
    config_file = isolated_config / "config.toml"
    assert config_file.exists()
    content = config_file.read_text()
    assert "true" in content


# ---------------------------------------------------------------------------
# Atomic write — temp file should not be left behind
# ---------------------------------------------------------------------------


def test_atomic_write_no_temp_file_left(isolated_config):
    """After set_write_enabled, no .tmp file is left in the home dir."""
    from pyzot.config import set_write_enabled

    set_write_enabled(True)
    tmp_files = list(isolated_config.glob("*.tmp"))
    assert tmp_files == [], f"Temp files left behind: {tmp_files}"


# ---------------------------------------------------------------------------
# set_config_value / get_config_value
# ---------------------------------------------------------------------------


def test_set_get_config_value_string():
    """Arbitrary string values round-trip correctly."""
    from pyzot.config import get_config_value, set_config_value

    set_config_value("write.connector_url", "http://localhost:9999")
    assert get_config_value("write.connector_url") == "http://localhost:9999"


def test_set_get_config_value_bool_true():
    """String 'true' is coerced to bool and read back as 'true'."""
    from pyzot.config import get_config_value, set_config_value

    set_config_value("write.enabled", "true")
    assert get_config_value("write.enabled") == "true"


def test_set_get_config_value_bool_false():
    """String 'false' is coerced to bool and read back as 'false'."""
    from pyzot.config import get_config_value, set_config_value

    set_config_value("write.enabled", "false")
    assert get_config_value("write.enabled") == "false"


def test_get_config_value_unset_returns_none():
    """get_config_value returns None for a key that has not been set."""
    from pyzot.config import get_config_value

    assert get_config_value("nonexistent.key") is None


# ---------------------------------------------------------------------------
# Multiple write calls accumulate state
# ---------------------------------------------------------------------------


def test_multiple_keys_persist_independently():
    """Setting two different keys does not overwrite each other."""
    from pyzot.config import get_config_value, set_config_value

    set_config_value("write.connector_url", "http://localhost:1234")
    set_config_value("write.enabled", "true")
    assert get_config_value("write.connector_url") == "http://localhost:1234"
    assert get_config_value("write.enabled") == "true"
