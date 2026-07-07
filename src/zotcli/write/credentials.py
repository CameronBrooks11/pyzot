"""File-based credential store for zotcli service logins.

Credentials are stored in ``<zotcli-home>/credentials.json`` with POSIX
mode 0600 (read/write for owner only).  No encryption at rest — the file
is protected by filesystem permissions only.

JSON shape:

.. code-block:: json

    {
        "services": {
            "unpaywall": {"email": "user@example.com"},
            "ieee": {"logged_in_at": "2026-05-10T13:24:00Z"},
            "sciencedirect": {"logged_in_at": "2026-05-10T14:00:00Z"}
        }
    }

API
---
- ``load() -> dict``  — returns the full credentials dict (or ``{}`` if no file).
- ``save(data: dict) -> None``  — atomic write-then-rename, chmod 0600 on POSIX.
- ``get(service, key) -> str | None``  — read one value.
- ``set(service, key, value) -> None``  — mutate and persist.
- ``clear(service) -> None``  — remove all stored data for a service.
"""

from __future__ import annotations

import json
import logging
import os
import stat
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _credentials_path() -> Path:
    """Return the path to credentials.json (parent dir created lazily)."""
    from zotcli.paths import credentials_path
    return credentials_path()


def load() -> dict:
    """Load and return the full credentials dict.

    Returns ``{}`` if the file does not exist or cannot be parsed.
    """
    p = _credentials_path()
    if not p.exists():
        return {}
    try:
        text = p.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            logger.warning("credentials.json has unexpected shape; ignoring.")
            return {}
        return data
    except Exception as exc:
        logger.warning("Failed to load credentials.json: %s", exc)
        return {}


def save(data: dict) -> None:
    """Persist *data* to credentials.json atomically (write-then-rename).

    After writing, sets POSIX file mode to 0600.  On Windows, ``os.chmod``
    with 0600 is a best-effort no-op (no pywin32 dependency).

    Parameters
    ----------
    data:
        The full credentials dict to persist.
    """
    p = _credentials_path()
    tmp = p.with_suffix(".json.tmp")
    try:
        content = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
        tmp.write_text(content, encoding="utf-8")
        # Set permissions before rename so the file is never world-readable
        try:
            os.chmod(tmp, stat.S_IRUSR | stat.S_IWUSR)  # 0o600
        except (AttributeError, NotImplementedError):
            # Windows: best-effort
            pass
        tmp.replace(p)
        logger.debug("credentials.json saved to %s", p)
    except Exception as exc:
        # Clean up temp file on error
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass
        raise RuntimeError(f"Failed to save credentials.json: {exc}") from exc


def get(service: str, key: str) -> str | None:
    """Return the value stored for *service* / *key*, or ``None`` if absent.

    Parameters
    ----------
    service:
        Service name (e.g. ``"unpaywall"``, ``"ieee"``, ``"sciencedirect"``).
    key:
        Field name within the service record (e.g. ``"email"``, ``"logged_in_at"``).

    Returns
    -------
    str | None
        The stored string value, or ``None`` if not found.
    """
    data = load()
    services = data.get("services", {})
    service_data = services.get(service, {})
    val = service_data.get(key)
    if val is None:
        return None
    return str(val)


def set(service: str, key: str, value: str) -> None:  # noqa: A001
    """Store *value* for *service* / *key* and persist atomically.

    Loads the current data, mutates the relevant field, then saves.

    Parameters
    ----------
    service:
        Service name.
    key:
        Field name.
    value:
        String value to store.
    """
    data = load()
    data.setdefault("services", {}).setdefault(service, {})[key] = value
    save(data)
    logger.debug("credentials: set %s.%s", service, key)


def clear(service: str) -> None:
    """Remove all stored credentials for *service*.

    If the service does not exist, this is a no-op.

    Parameters
    ----------
    service:
        Service name to clear.
    """
    data = load()
    services = data.get("services", {})
    if service in services:
        del services[service]
        data["services"] = services
        save(data)
        logger.debug("credentials: cleared service %s", service)
    else:
        logger.debug("credentials: clear called for unknown service %s (no-op)", service)
