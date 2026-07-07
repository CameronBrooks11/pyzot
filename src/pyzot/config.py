"""Configuration — auto-detection and persistence via TOML."""

from __future__ import annotations

import json
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib
    except ImportError:
        tomllib = None


def _config_dir() -> Path:
    from platformdirs import user_config_dir

    return Path(user_config_dir("pyzot", appauthor=False))


def _config_path() -> Path:
    return _config_dir() / "config.toml"


_DEFAULTS: dict = {
    "database": {
        "path": None,
        "library_id": 1,
    },
    "output": {
        "default_format": "table",
        "color": True,
        "page_size": 50,
    },
    "library_auth": {},
}

# Defaults for the [write] section (stored in pyzot-home/config.toml)
_WRITE_DEFAULTS: dict = {
    "write": {
        "enabled": False,
        "connector_url": "http://127.0.0.1:23119",
        "require_zotero": True,
        "non_interactive_default": False,
    },
}


def load_config() -> dict:
    """Load config from disk, merging with defaults."""
    cfg = {k: dict(v) for k, v in _DEFAULTS.items()}
    p = _config_path()
    if p.exists() and tomllib is not None:
        with open(p, "rb") as f:
            on_disk = tomllib.load(f)
        for section, values in on_disk.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
    return cfg


def save_config(cfg: dict) -> None:
    """Persist config to disk (TOML format)."""
    p = _config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        import tomli_w

        with open(p, "wb") as f:
            tomli_w.dump(_strip_none(cfg), f)
        return
    except ImportError:
        pass

    lines: list[str] = []
    for section, values in cfg.items():
        if not isinstance(values, dict):
            continue
        lines.append(f"[{section}]")
        for key, value in values.items():
            if isinstance(value, dict):
                lines.append(f"[{section}.{key}]")
                for nested_key, nested_value in value.items():
                    if isinstance(nested_value, dict):
                        raise ValueError(
                            "Fallback TOML writer supports only one level of nested tables; "
                            "install tomli_w for deeper nesting."
                        )
                    if nested_value is None:
                        continue
                    lines.append(f"{nested_key} = {_toml_literal(nested_value)}")
            else:
                if value is None:
                    continue
                lines.append(f"{key} = {_toml_literal(value)}")
        lines.append("")
    p.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _strip_none(obj):
    if isinstance(obj, dict):
        return {k: _strip_none(v) for k, v in obj.items() if v is not None}
    return obj


def _toml_literal(value: object) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(value)
    return json.dumps(str(value))


def get_db_path(override: str | None = None) -> Path | None:
    """Return the database path from override > config > None."""
    if override:
        return Path(override)
    cfg = load_config()
    raw = cfg.get("database", {}).get("path")
    if raw:
        return Path(raw)
    return None


def get_library_id(override: int | None = None) -> int:
    if override is not None:
        return override
    cfg = load_config()
    return cfg.get("database", {}).get("library_id", 1)


def get_library_auth(library_id: int) -> dict[str, str]:
    cfg = load_config()
    auth = cfg.get("library_auth", {}).get(str(library_id), {})
    if not isinstance(auth, dict):
        return {}
    return {
        "institution": str(auth.get("institution", "") or ""),
        "username": str(auth.get("username", "") or ""),
        "password": str(auth.get("password", "") or ""),
    }


def set_library_auth(
    library_id: int,
    *,
    institution: str,
    username: str,
    password: str,
) -> None:
    cfg = load_config()
    auth_section = cfg.setdefault("library_auth", {})
    if not isinstance(auth_section, dict):
        auth_section = {}
        cfg["library_auth"] = auth_section
    auth_section[str(library_id)] = {
        "institution": institution,
        "username": username,
        "password": password,
    }
    save_config(cfg)


# ---------------------------------------------------------------------------
# Write-section helpers — config stored in <pyzot-home>/config.toml
# ---------------------------------------------------------------------------


def _write_config_path() -> Path:
    """Return the path to the pyzot-home config.toml (for write settings)."""
    from pyzot.paths import config_path

    return config_path()


def _load_write_config() -> dict:
    """Load the pyzot-home config.toml, merging with write defaults."""
    import copy

    cfg = copy.deepcopy(_WRITE_DEFAULTS)
    p = _write_config_path()
    if p.exists() and tomllib is not None:
        with open(p, "rb") as f:
            on_disk = tomllib.load(f)
        for section, values in on_disk.items():
            if section in cfg and isinstance(values, dict):
                cfg[section].update(values)
            else:
                cfg[section] = values
    return cfg


def _save_write_config_atomic(cfg: dict) -> None:
    """Write cfg to pyzot-home config.toml atomically (write-then-rename)."""
    p = _write_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    content = _dump_toml(cfg)
    # Write to a sibling temp file, then rename for atomicity
    tmp_path = p.with_suffix(".toml.tmp")
    try:
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(p)
    except Exception:
        # Clean up temp file on error
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _dump_toml(cfg: dict) -> str:
    """Minimal hand-rolled TOML serialiser for our small, flat config.

    Only handles: bool, int, float, str values within one level of sections.
    Uses tomli-w if available; falls back to hand-rolled for the simple case.
    """
    try:
        import io

        import tomli_w

        buf = io.BytesIO()
        tomli_w.dump(cfg, buf)
        return buf.getvalue().decode("utf-8")
    except ImportError:
        pass

    # Hand-rolled fallback
    lines: list[str] = []
    for section, values in cfg.items():
        if not isinstance(values, dict):
            # Top-level scalar — unlikely but handle it
            lines.append(f"{section} = {_toml_value(values)}")
            continue
        lines.append(f"\n[{section}]")
        for key, val in values.items():
            lines.append(f"{key} = {_toml_value(val)}")
    return "\n".join(lines).lstrip("\n") + "\n"


def _toml_value(val: object) -> str:
    """Render a Python value as a TOML literal."""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, (int, float)):
        return str(val)
    if isinstance(val, str):
        escaped = val.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{escaped}"'
    if val is None:
        return '""'
    return f'"{val}"'


# --- Public helpers ---


def get_write_enabled() -> bool:
    """Return True if write capability is enabled (default False)."""
    cfg = _load_write_config()
    return bool(cfg.get("write", {}).get("enabled", False))


def set_write_enabled(value: bool) -> None:
    """Persist write.enabled to <pyzot-home>/config.toml atomically."""
    cfg = _load_write_config()
    cfg.setdefault("write", {})["enabled"] = value
    _save_write_config_atomic(cfg)


def get_connector_url() -> str:
    """Return the connector URL (default http://127.0.0.1:23119)."""
    cfg = _load_write_config()
    return cfg.get("write", {}).get("connector_url", "http://127.0.0.1:23119")


def set_config_value(key: str, value: str) -> None:
    """Set an arbitrary config value using dotted section.key notation.

    Supports keys like: ``write.enabled`` and ``write.connector_url``.
    """
    cfg = _load_write_config()
    if "." in key:
        section, _, field = key.partition(".")
    else:
        # Top-level key — store under a generic section
        section, field = "misc", key

    cfg.setdefault(section, {})

    # Type coercion: booleans
    coerced: object
    if value.lower() in ("true", "yes", "1"):
        coerced = True
    elif value.lower() in ("false", "no", "0"):
        coerced = False
    else:
        coerced = value

    cfg[section][field] = coerced
    _save_write_config_atomic(cfg)


def get_config_value(key: str) -> str | None:
    """Get an arbitrary config value using dotted section.key notation.

    Returns the string representation of the value, or None if unset.
    """
    cfg = _load_write_config()
    if "." in key:
        section, _, field = key.partition(".")
    else:
        section, field = "misc", key

    val = cfg.get(section, {}).get(field)
    if val is None:
        return None
    return str(val).lower() if isinstance(val, bool) else str(val)
