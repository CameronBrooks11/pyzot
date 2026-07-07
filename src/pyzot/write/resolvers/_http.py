"""Shared HTTP helpers for metadata resolvers."""

from __future__ import annotations

from typing import Any

_DEFAULT_USER_AGENT = "pyzot/0.2 (mailto:auto-set-on-first-run)"


def require_httpx(service: str = "resolver") -> Any:
    """Import httpx or raise the standard write-extra error."""
    try:
        import httpx  # type: ignore[import]
    except ImportError as exc:
        raise ImportError(
            f"The 'write' extra is required for {service} access. "
            "Install it with: pip install \"pyzot[write]\""
        ) from exc
    return httpx


def user_agent(config_key: str = "resolvers.crossref_user_agent") -> str:
    """Return a configured resolver User-Agent or the project default."""
    try:
        from pyzot.config import get_config_value
        value = get_config_value(config_key)
        if value:
            return value
    except Exception:
        pass
    return _DEFAULT_USER_AGENT


def headers(*, config_key: str = "resolvers.crossref_user_agent") -> dict[str, str]:
    """Return standard resolver request headers."""
    return {"User-Agent": user_agent(config_key)}
