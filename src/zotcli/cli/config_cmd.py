"""CLI group: zot config — read/write zotcli configuration and per-library auth."""

from __future__ import annotations

import sys

import click

from zotcli.cli.main import Context, pass_ctx
from zotcli.cli.render import make_console
from zotcli.config import get_library_auth, set_library_auth


@click.group("config")
def config_cmd():
    """Manage zotcli settings."""


@config_cmd.command("path")
def config_path_cmd():
    """Print the zotcli home directory path."""
    from zotcli.paths import zotcli_home
    click.echo(str(zotcli_home()))


@config_cmd.command("get")
@click.argument("key")
def config_get(key: str):
    """Print the value of KEY (section.key form, e.g. write.enabled).

    Exits with code 1 if the key is not set.
    """
    from zotcli.config import get_config_value
    val = get_config_value(key)
    if val is None:
        click.echo(f"Key '{key}' is not set.", err=True)
        sys.exit(1)
    click.echo(val)


@config_cmd.command("set")
@click.argument("key")
@click.argument("value")
def config_set(key: str, value: str):
    """Set KEY to VALUE and persist to <zotcli-home>/config.toml.

    Supported keys include: write.enabled, write.connector_url,
    unpaywall.email, and any other dotted section.key value.
    """
    from zotcli.config import set_config_value
    set_config_value(key, value)
    click.echo(f"Set {key} = {value}")


@config_cmd.command("library-auth")
@click.option("--library", "library_id", type=int, default=None, help="Library ID (default: current)")
@click.option("--institution", default=None, help="Institution/library provider name")
@click.option("--username", default=None, help="Library login username")
@click.option("--password", default=None, help="Library login password/token")
@click.option("--show", is_flag=True, help="Show current authentication details")
@pass_ctx
def library_auth(
    ctx: Context,
    library_id: int | None,
    institution: str | None,
    username: str | None,
    password: str | None,
    show: bool,
):
    """Store or display per-library authentication details for full-text retrieval."""
    console = make_console(ctx.color)
    lib_id = library_id if library_id is not None else ctx.library_id

    if show:
        auth = get_library_auth(lib_id)
        if not any(auth.values()):
            console.print(f"[dim]No auth details configured for library {lib_id}.[/dim]")
            return
        masked_password = "******" if auth["password"] else ""
        console.print(f"Library: {lib_id}")
        console.print(f"Institution: {auth['institution']}")
        console.print(f"Username: {auth['username']}")
        console.print(f"Password: {masked_password}")
        return

    institution_value = institution or click.prompt("Institution", default="", show_default=False)
    username_value = username or click.prompt("Username", default="", show_default=False)
    password_value = password or click.prompt(
        "Password / token",
        default="",
        show_default=False,
        hide_input=True,
    )

    set_library_auth(
        lib_id,
        institution=institution_value.strip(),
        username=username_value.strip(),
        password=password_value,
    )
    console.print(f"[green]Saved auth details for library {lib_id}.[/green]")
