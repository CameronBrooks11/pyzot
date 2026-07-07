"""Shared context helpers for `zot add`."""

from __future__ import annotations

import os

import click


def require_write_enabled(ctx: click.Context) -> None:
    """Raise ClickException if write is not enabled by any gate.

    Gates checked (in priority order):
    1. --allow-write flag in ctx.obj
    2. PYZOT_ALLOW_WRITE env var (truthy: 1, true, yes)
    3. write.enabled = true in config

    This helper is called by all write commands; not used by `status`.
    """
    from pyzot.config import get_write_enabled

    obj = ctx.obj
    if getattr(obj, "allow_write", False):
        return
    if os.environ.get("PYZOT_ALLOW_WRITE", "0") not in ("0", "", "false", "False"):
        return
    if get_write_enabled():
        return

    raise click.ClickException(
        "Write capability is disabled. Enable it with:\n"
        "  zot config set write.enabled true\n"
        "or pass --allow-write on each command, "
        "or set the PYZOT_ALLOW_WRITE=1 environment variable."
    )


def resolve_connector_url(ctx: click.Context) -> str:
    """Return the effective connector URL from CLI flag, env, or config."""
    from pyzot.config import get_connector_url

    obj = ctx.obj
    # CLI flag takes precedence
    url = getattr(obj, "connector_url", None)
    if url:
        return url
    # Env var
    env_url = os.environ.get("PYZOT_CONNECTOR_URL")
    if env_url:
        return env_url
    # Config
    return get_connector_url()
