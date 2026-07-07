"""Local file and bibliography import handling for `zot add`."""

from __future__ import annotations

import json

import click

from . import pipeline
from .context import require_write_enabled, resolve_connector_url


def _run_filepath(
    ctx: click.Context,
    path_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    wait_recognize: int,
    verbose: bool,
) -> None:
    """Route a local file path to `file` (PDF/EPUB) or `import` (bibliography)."""
    from pathlib import Path as _Path

    from pyzot.write.pdf import sniff_mime

    fpath = _Path(path_value).expanduser().resolve()

    if not fpath.exists():
        raise click.ClickException(f"File not found: {fpath}")

    mime = sniff_mime(fpath)
    if mime in ("application/pdf", "application/epub+zip"):
        _run_file(
            ctx,
            str(fpath),
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            wait_recognize=wait_recognize,
            verbose=verbose,
        )
    else:
        _run_import(
            ctx,
            str(fpath),
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            verbose=verbose,
        )


def _run_file(
    ctx: click.Context,
    path: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    wait_recognize: int,
    verbose: bool,
) -> None:
    """Upload a local PDF or EPUB file as a standalone attachment."""
    from pathlib import Path as _Path

    from pyzot.write.pdf import human_size, sniff_mime

    require_write_enabled(ctx)

    fpath = _Path(path).expanduser().resolve()

    if not fpath.is_file():
        raise click.ClickException(f"Not a regular file: {fpath}")

    mime = sniff_mime(fpath)
    if mime not in ("application/pdf", "application/epub+zip"):
        ext = fpath.suffix.lower()
        raise click.ClickException(
            f"Unsupported file type: {fpath.name!r} "
            f"(detected: {mime!r}, extension: {ext!r}). "
            "Bare file-path adds upload PDF/EPUB files and import bibliography "
            "data (.bib, .ris, .json) automatically."
        )

    file_size = fpath.stat().st_size
    title = fpath.stem
    source_url = f"file://{fpath}"

    if dry_run:
        import json as _json

        click.echo("Dry-run: would upload the following:")
        click.echo(f"  File       : {fpath}")
        click.echo(f"  Size       : {human_size(file_size)}")
        click.echo(f"  MIME       : {mime}")
        click.echo(f"  Title      : {title}")
        click.echo(f"  Source URL : {source_url}")
        if collection:
            click.echo(f"  Collection : {collection}")
        if tag:
            click.echo(f"  Tags       : {list(tag)}")
        click.echo(
            "  X-Metadata : "
            + _json.dumps({"sessionID": "<session-id>", "title": title, "url": source_url})
        )
        return

    # Preflight
    connector_url = resolve_connector_url(ctx)
    from pyzot.write.preflight import check_zotero_running

    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    import uuid as _uuid

    from pyzot.write.connector_client import ConnectorClient

    session_id = _uuid.uuid4().hex
    client = ConnectorClient(base_url=connector_url, verbose=verbose)

    if verbose:
        click.echo(f"Uploading {fpath.name} ({human_size(file_size)}, {mime}) ...", err=True)

    result = client.save_standalone_attachment(
        file_path=fpath,
        content_type=mime,
        session_id=session_id,
        title=title,
        source_url=source_url,
    )

    if verbose:
        click.echo(f"saveStandaloneAttachment response: {result}", err=True)

    can_recognize = result.get("canRecognize", False)

    # Apply collection + tags via updateSession
    tags_list = list(tag)
    if collection or tags_list:
        from pyzot.write.session import Session as _Session

        tmp_session = _Session(client=client)
        tmp_session.id = session_id
        if collection:
            db = pipeline._open_db()
            if db is not None:
                try:
                    tmp_session.set_target(collection, db=db)
                    if verbose:
                        click.echo(f"Set target collection: {collection}", err=True)
                except ValueError as exc:
                    click.echo(f"Warning: {exc}", err=True)
            else:
                click.echo(
                    "Warning: cannot resolve collection name — database not available.", err=True
                )
        if tags_list:
            tmp_session.add_tags(tags_list)
            if verbose:
                click.echo(f"Applied tags: {tags_list}", err=True)

    # Extract attachment key from result
    attachment_key: str | None = None
    if isinstance(result, dict):
        attachment_key = result.get("key") or result.get("attachmentKey")

    # Poll for recognised parent
    if can_recognize and wait_recognize > 0:
        if verbose:
            click.echo(
                f"canRecognize=true — polling DB for parent (up to {wait_recognize}s)...",
                err=True,
            )

        from pyzot.config import get_db_path
        from pyzot.db import discover_db

        try:
            db_path = get_db_path() or discover_db()
        except Exception:
            db_path = None

        parent_ref = None
        if db_path is not None and attachment_key:
            from pyzot.write.recognize import wait_for_recognized_parent

            parent_ref = wait_for_recognized_parent(
                db_path,
                attachment_key,
                timeout_s=float(wait_recognize),
                poll_interval_s=1.0,
            )

        if parent_ref is not None:
            click.echo(f"Recognised parent: {parent_ref.key} — {parent_ref.title}")
        else:
            click.echo(
                f"No parent recognised within {wait_recognize}s. "
                f"Standalone attachment key: {attachment_key or '(unknown)'}"
            )
    else:
        if attachment_key:
            click.echo(f"Standalone attachment key: {attachment_key}")
        else:
            click.echo(json.dumps(result, indent=2))


def _run_import(
    ctx: click.Context,
    path: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Import bibliography data from a RIS, BibTeX, or CSL-JSON file."""
    from pathlib import Path as _Path

    from pyzot.write.pdf import sniff_import_content_type

    require_write_enabled(ctx)

    fpath = _Path(path).expanduser().resolve()

    if not fpath.is_file():
        raise click.ClickException(f"Not a regular file: {fpath}")

    body = fpath.read_bytes()
    content_type = sniff_import_content_type(fpath, data=body[:512])

    if dry_run:
        preview = body[:200]
        try:
            preview_str = preview.decode("utf-8", errors="replace")
        except Exception:
            preview_str = repr(preview)
        click.echo(f"File         : {fpath}")
        click.echo(f"Content-Type : {content_type}")
        click.echo(f"Size         : {len(body)} bytes")
        click.echo(f"Preview (200B): {preview_str!r}")
        return

    # Preflight
    connector_url = resolve_connector_url(ctx)
    from pyzot.write.preflight import check_zotero_running

    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    import uuid as _uuid

    from pyzot.write.connector_client import ConnectorClient

    session_id = _uuid.uuid4().hex
    client = ConnectorClient(base_url=connector_url, verbose=verbose)

    if verbose:
        click.echo(f"Importing {fpath.name} ({len(body)} bytes, {content_type}) ...", err=True)

    result = client.connector_import(
        body=body,
        content_type=content_type,
        session_id=session_id,
    )

    if verbose:
        click.echo(f"connector_import response: {result}", err=True)

    # Apply collection + tags via updateSession
    tags_list = list(tag)
    if collection or tags_list:
        from pyzot.write.session import Session as _Session

        tmp_session = _Session(client=client)
        tmp_session.id = session_id
        if collection:
            db = pipeline._open_db()
            if db is not None:
                try:
                    tmp_session.set_target(collection, db=db)
                    if verbose:
                        click.echo(f"Set target collection: {collection}", err=True)
                except ValueError as exc:
                    click.echo(f"Warning: {exc}", err=True)
            else:
                click.echo(
                    "Warning: cannot resolve collection name — database not available.", err=True
                )
        if tags_list:
            tmp_session.add_tags(tags_list)
            if verbose:
                click.echo(f"Applied tags: {tags_list}", err=True)

    # Extract and print imported item keys
    keys: list[str] = []
    if isinstance(result, list):
        for item in result:
            if isinstance(item, dict):
                k = item.get("key")
                if k:
                    keys.append(k)
    elif isinstance(result, dict):
        items = result.get("items", [])
        if isinstance(items, list):
            for item in items:
                if isinstance(item, dict):
                    k = item.get("key")
                    if k:
                        keys.append(k)

    if keys:
        click.echo(f"Imported {len(keys)} item(s): {' '.join(keys)}")
    else:
        click.echo(json.dumps(result, indent=2))
