"""Root Click group and shared context."""

from __future__ import annotations

import warnings

import click

from pyzot.config import get_db_path, get_library_id
from pyzot.db import ZoteroDatabase, discover_db

# Subcommands that do NOT need a Zotero database connection.
_DB_FREE_COMMANDS = {"config", "add"}


class Context:
    def __init__(
        self,
        db: ZoteroDatabase | None,
        library_id: int,
        fmt: str,
        color: bool,
        allow_write: bool = False,
        connector_url: str | None = None,
        require_zotero: bool = True,
    ):
        self.db = db
        self.library_id = library_id
        self.fmt = fmt
        self.color = color
        self.allow_write = allow_write
        self.connector_url = connector_url
        self.require_zotero = require_zotero


pass_ctx = click.make_pass_decorator(Context)


@click.group()
@click.option("--db", "db_path", default=None, help="Path to zotero.sqlite")
@click.option("--library", "library_id", default=None, type=int, help="Library ID (default: 1)")
@click.option(
    "--format",
    "fmt",
    default="table",
    type=click.Choice(["table", "json", "csv"]),
    help="Output format",
)
@click.option("--no-color", is_flag=True, default=False, help="Disable colour output")
@click.option(
    "--allow-write",
    is_flag=True,
    default=False,
    envvar="PYZOT_ALLOW_WRITE",
    help="Allow write operations (ad-hoc override; or set write.enabled=true in config).",
)
@click.option(
    "--connector-url",
    default=None,
    envvar="PYZOT_CONNECTOR_URL",
    help="Zotero connector URL (default: http://127.0.0.1:23119).",
)
@click.option(
    "--require-zotero/--no-require-zotero",
    default=True,
    help="Fail if Zotero is not reachable (default: require).",
)
@click.pass_context
def cli(
    ctx: click.Context,
    db_path: str | None,
    library_id: int | None,
    fmt: str,
    no_color: bool,
    allow_write: bool,
    connector_url: str | None,
    require_zotero: bool,
):
    """zot — CLI for your Zotero library."""
    # Commands that don't need the database skip DB discovery entirely.
    if ctx.invoked_subcommand in _DB_FREE_COMMANDS:
        ctx.obj = Context(
            db=None,
            library_id=library_id or 1,
            fmt=fmt,
            color=not no_color,
            allow_write=allow_write,
            connector_url=connector_url,
            require_zotero=require_zotero,
        )
        return

    resolved_path = get_db_path(db_path)
    if resolved_path is None:
        try:
            resolved_path = discover_db()
        except FileNotFoundError as e:
            raise click.ClickException(str(e)) from e

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        db = ZoteroDatabase(resolved_path, warn_if_open=True)

    for w in caught:
        click.echo(f"[warning] {w.message}", err=True)

    lib_id = get_library_id(library_id)
    ctx.obj = Context(
        db=db,
        library_id=lib_id,
        fmt=fmt,
        color=not no_color,
        allow_write=allow_write,
        connector_url=connector_url,
        require_zotero=require_zotero,
    )
    ctx.call_on_close(db.close)


# Import and register read-only subcommand groups
from pyzot.cli import attachments as _att_mod  # noqa: E402
from pyzot.cli import collections as _col_mod  # noqa: E402
from pyzot.cli import config_cmd as _config_mod  # noqa: E402
from pyzot.cli import export as _export_mod  # noqa: E402
from pyzot.cli import items as _items_mod  # noqa: E402
from pyzot.cli import search as _search_mod  # noqa: E402
from pyzot.cli import stats as _stats_mod  # noqa: E402

cli.add_command(_col_mod.collections)
cli.add_command(_items_mod.items)
cli.add_command(_att_mod.attachments)
cli.add_command(_search_mod.search)
cli.add_command(_stats_mod.stats)
cli.add_command(_export_mod.export)
cli.add_command(_config_mod.config_cmd)

# Import and register write-capability groups (M1+)
from pyzot.cli.add import add as _add_cmd  # noqa: E402

cli.add_command(_add_cmd)
