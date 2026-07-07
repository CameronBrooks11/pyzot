"""CLI — `zot attachments` subcommands."""

from __future__ import annotations

import subprocess
import sys

import click
from rich.table import Table

from pyzot.cli.main import Context, pass_ctx
from pyzot.cli.render import make_console
from pyzot.models import Attachment
from pyzot.queries.attachments import enrich_attachment_paths
from pyzot.queries.items import get_item


@click.group()
def attachments():
    """Browse and open Zotero attachments."""


@attachments.command("list")
@click.option("--missing", is_flag=True, help="Only show missing files")
@click.option("--type", "content_type", default=None, help="Filter by content type (e.g. pdf)")
@pass_ctx
def list_attachments(ctx: Context, missing: bool, content_type: str | None):
    """List all attachments."""
    console = make_console(ctx.color)
    data_dir = ctx.db.path.parent

    rows = ctx.db.fetchall(
        """
        SELECT i.itemID, i.key, ia.parentItemID, ia.linkMode,
               ia.contentType, ia.path
        FROM itemAttachments ia
        JOIN items i ON ia.itemID = i.itemID
        WHERE ia.parentItemID IS NOT NULL
        ORDER BY ia.contentType
        """
    )

    atts = [
        Attachment(
            item_id=r["itemID"],
            key=r["key"],
            parent_item_id=r["parentItemID"],
            link_mode=r["linkMode"] if r["linkMode"] is not None else 0,
            content_type=r["contentType"] or "",
            path=r["path"],
        )
        for r in rows
    ]
    enrich_attachment_paths(atts, data_dir)

    if content_type:
        atts = [a for a in atts if content_type.lower() in a.content_type.lower()]
    if missing:
        atts = [a for a in atts if not a.file_exists]

    if not atts:
        console.print("[dim]No attachments found.[/dim]")
        return

    t = Table(title=f"{len(atts)} attachments")
    t.add_column("Key", style="cyan", width=10)
    t.add_column("Type", width=20)
    t.add_column("Mode", width=14)
    t.add_column("Exists", width=7)
    t.add_column("Path")

    for att in atts[:500]:
        exists = "[green]✓[/green]" if att.file_exists else "[red]✗[/red]"
        path_str = str(att.absolute_path) if att.absolute_path else att.path or ""
        t.add_row(att.key, att.content_type, att.link_mode_name, exists, path_str[:80])
    console.print(t)
    if len(atts) > 500:
        console.print(f"[dim]... and {len(atts) - 500} more[/dim]")


@attachments.command("path")
@click.argument("id_or_key")
@pass_ctx
def attachment_path(ctx: Context, id_or_key: str):
    """Print the resolved absolute path(s) for an item's attachments."""
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(ctx.db, item_id_val)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    for att in item.attachments:
        if att.absolute_path:
            click.echo(str(att.absolute_path))


@attachments.command("open")
@click.argument("id_or_key")
@pass_ctx
def open_attachment(ctx: Context, id_or_key: str):
    """Open the first attachment with the system default application."""
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(ctx.db, item_id_val)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")

    existing = [a for a in item.attachments if a.file_exists and a.absolute_path]
    if not existing:
        raise click.ClickException("No local files found for this item.")

    path = existing[0].absolute_path
    click.echo(f"Opening: {path}")

    if sys.platform == "win32":
        import os

        os.startfile(str(path))
    elif sys.platform == "darwin":
        subprocess.run(["open", str(path)])
    else:
        opener = "wslview" if _which("wslview") else "xdg-open"
        subprocess.run([opener, str(path)])


def _which(cmd: str) -> bool:
    import shutil

    return shutil.which(cmd) is not None


# ---------------------------------------------------------------------------
# Write commands — attach files / fetch PDFs for existing items
# ---------------------------------------------------------------------------


def _resolve_parent(db, id_or_key: str):
    """Return (item, item_key) or raise ClickException."""
    item_id_val = int(id_or_key) if id_or_key.isdigit() else id_or_key
    item = get_item(db, item_id_val)
    if item is None:
        raise click.ClickException(f"Item not found: {id_or_key!r}")
    return item


def _require_write(ctx: Context) -> None:
    """Refuse to run write commands unless write capability is enabled."""
    from pyzot.config import get_write_enabled

    allow_flag = getattr(ctx, "allow_write", False)
    if not (get_write_enabled() or allow_flag):
        raise click.ClickException(
            "Write capability is disabled. Enable with `zot config set write.enabled true`, "
            "or pass --allow-write."
        )


def _data_dir(ctx: Context):
    """Return the Zotero data directory (parent of zotero.sqlite)."""
    return ctx.db.path.parent


@attachments.command("add")
@click.argument("parent_key")
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--title", default=None, help="Display title (default: filename stem).")
@click.option("--source-url", default=None, help="Source URL for provenance.")
@pass_ctx
def add_attachment(
    ctx: Context,
    parent_key: str,
    file_path: str,
    title: str | None,
    source_url: str | None,
) -> None:
    """Attach an existing local file to an existing Zotero item.

    Inserts the attachment directly into ``zotero.sqlite`` and copies the
    file into ``<zotero-data-dir>/storage/<new-key>/``.

    Example:

        zot attachments add ABCD1234 ~/Downloads/paper.pdf
    """
    from pyzot.write.attach_existing import attach_to_existing

    _require_write(ctx)

    # Resolve parent (also validates it exists)
    item = _resolve_parent(ctx.db, parent_key)
    if not item.key:
        raise click.ClickException(f"Item {parent_key!r} has no key.")

    result = attach_to_existing(
        db_path=ctx.db.path,
        data_dir=_data_dir(ctx),
        parent_key=item.key,
        source_file=file_path,
        title=title,
        source_url=source_url,
        library_id=ctx.library_id,
    )

    console = make_console(ctx.color)
    if result.inserted:
        console.print(
            f"[green]✓[/green] Attached [cyan]{result.attachment_key}[/cyan] "
            f"to [cyan]{result.parent_key}[/cyan]\n"
            f"  Path: {result.stored_path}"
        )
    else:
        console.print(
            f"[yellow]·[/yellow] Already attached as [cyan]{result.attachment_key}[/cyan] "
            f"(no change)"
        )


@attachments.command("fetch")
@click.argument("parent_key")
@click.option(
    "--methods",
    default="doi,url,custom",
    show_default=True,
    help="Comma-separated subset of resolvers to enable.",
)
@pass_ctx
def fetch_attachment(
    ctx: Context,
    parent_key: str,
    methods: str,
) -> None:
    """Find and attach a PDF for an existing item using HTTP resolvers.

    Tries DOI, item URL, and any custom resolvers in turn. The first successful
    PDF is attached as a child of the item.

    Example:

        zot attachments fetch 5UFZMSLU
    """
    from pyzot.write.attach_existing import attach_to_existing
    from pyzot.write.find_file import find_file

    _require_write(ctx)
    console = make_console(ctx.color)

    item = _resolve_parent(ctx.db, parent_key)

    # Already has a PDF? Don't redownload.
    has_pdf = any(
        (a.content_type or "").lower() == "application/pdf" and a.file_exists
        for a in (item.attachments or [])
    )
    if has_pdf:
        console.print(f"[yellow]·[/yellow] {item.key} already has a PDF attachment; skipping.")
        return

    method_list = tuple(m.strip() for m in methods.split(",") if m.strip())
    item_url = (item.fields.get("url") or item.fields.get("URL") or "").strip() or None

    result = find_file(
        doi=item.doi,
        item_url=item_url,
        methods=method_list,
    )

    if result is None:
        console.print(f"[red]✗[/red] No PDF found for {item.key} ({item.title[:60]}).")
        raise SystemExit(1)

    try:
        att = attach_to_existing(
            db_path=ctx.db.path,
            data_dir=_data_dir(ctx),
            parent_key=item.key,
            source_file=result.path,
            title=f"{item.title} ({result.access_method})"[:200],
            content_type=result.content_type,
            source_url=result.source_url,
            library_id=ctx.library_id,
        )
    finally:
        # Always remove the temp file
        try:
            result.path.unlink()
        except OSError:
            pass

    console.print(
        f"[green]✓[/green] {item.key}: attached [cyan]{att.attachment_key}[/cyan] "
        f"via {result.access_method}"
    )


def _fetch_for_items(
    ctx: Context,
    items_iter,
    *,
    methods: tuple[str, ...],
    skip_with_pdf: bool = True,
) -> tuple[int, int, int]:
    """Run fetch for each item in *items_iter*. Returns (attached, skipped, failed)."""
    from pyzot.write.attach_existing import attach_to_existing
    from pyzot.write.find_file import find_file

    console = make_console(ctx.color)
    attached = skipped = failed = 0

    for item in items_iter:
        if not item.key:
            continue
        if skip_with_pdf and any(
            (a.content_type or "").lower() == "application/pdf" and a.file_exists
            for a in (item.attachments or [])
        ):
            skipped += 1
            console.print(f"[dim]·[/dim] {item.key} has PDF; skip")
            continue

        item_url = (item.fields.get("url") or item.fields.get("URL") or "").strip() or None
        try:
            result = find_file(
                doi=item.doi,
                item_url=item_url,
                methods=methods,
            )
        except Exception as exc:
            console.print(f"[red]✗[/red] {item.key}: find_file error: {exc}")
            failed += 1
            continue

        if result is None:
            console.print(f"[red]✗[/red] {item.key}: no PDF found")
            failed += 1
            continue

        try:
            att = attach_to_existing(
                db_path=ctx.db.path,
                data_dir=_data_dir(ctx),
                parent_key=item.key,
                source_file=result.path,
                title=f"{item.title} ({result.access_method})"[:200],
                content_type=result.content_type,
                source_url=result.source_url,
                library_id=ctx.library_id,
            )
            attached += 1
            console.print(
                f"[green]✓[/green] {item.key}: {att.attachment_key} via {result.access_method}"
            )
        except Exception as exc:
            failed += 1
            console.print(f"[red]✗[/red] {item.key}: attach failed: {exc}")
        finally:
            try:
                result.path.unlink()
            except OSError:
                pass

    return attached, skipped, failed


@attachments.command("fetch-collection")
@click.argument("collection_name")
@click.option("--methods", default="doi,url,custom", show_default=True)
@click.option(
    "--include-with-pdf",
    is_flag=True,
    default=False,
    help="Also process items that already have a PDF (re-fetch).",
)
@pass_ctx
def fetch_collection(
    ctx: Context,
    collection_name: str,
    methods: str,
    include_with_pdf: bool,
) -> None:
    """Find PDFs for every item in a collection that doesn't already have one.

    Example:

        zot attachments fetch-collection "[Paper] LV_UG_Cable_Models_DSSE"
    """
    from pyzot.queries.collections import get_collection_by_name, get_items_in_collection

    _require_write(ctx)
    console = make_console(ctx.color)

    matches = get_collection_by_name(ctx.db, collection_name, fuzzy=False)
    if not matches:
        matches = get_collection_by_name(ctx.db, collection_name, fuzzy=True)
    if not matches:
        raise click.ClickException(f"Collection not found: {collection_name!r}")
    col = matches[0]

    items = get_items_in_collection(ctx.db, col.collection_id)
    console.print(f"[bold]{col.name}[/bold] — {len(items)} items")

    method_list = tuple(m.strip() for m in methods.split(",") if m.strip())
    attached, skipped, failed = _fetch_for_items(
        ctx,
        items,
        methods=method_list,
        skip_with_pdf=not include_with_pdf,
    )
    console.print(f"\n[bold]Done.[/bold] attached={attached} skipped={skipped} failed={failed}")


@attachments.command("fetch-all")
@click.option("--methods", default="doi,url,custom", show_default=True)
@click.option("--limit", type=int, default=None, help="Cap total items processed.")
@pass_ctx
def fetch_all(
    ctx: Context,
    methods: str,
    limit: int | None,
) -> None:
    """Find PDFs for every library item that has a DOI/URL but no PDF.

    Long-running. Honour --limit while testing. Items already with a PDF
    attachment are skipped. Rate-limiting is enforced per-domain by the
    pipeline internally.

    Example:

        zot attachments fetch-all --limit 20
    """
    from pyzot.queries.items import get_items

    _require_write(ctx)
    console = make_console(ctx.color)

    items = get_items(ctx.db, library_id=ctx.library_id, limit=limit or 100000)
    candidates = [it for it in items if it.doi or (it.fields.get("url") or it.fields.get("URL"))]
    console.print(f"[bold]fetch-all[/bold] — {len(candidates)} candidate items")

    method_list = tuple(m.strip() for m in methods.split(",") if m.strip())
    attached, skipped, failed = _fetch_for_items(
        ctx,
        candidates,
        methods=method_list,
        skip_with_pdf=True,
    )
    console.print(f"\n[bold]Done.[/bold] attached={attached} skipped={skipped} failed={failed}")
