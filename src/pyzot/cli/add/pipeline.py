"""Identifier add pipeline and database helpers."""

from __future__ import annotations

import json

import click

from .context import require_write_enabled, resolve_connector_url


def _run_add_pipeline(
    ctx: click.Context,
    kind: str,
    identifier: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
) -> None:
    """Shared implementation for doi/arxiv/pmid/isbn add commands.

    Steps:
    1. Write gate
    2. Preflight (Zotero running?)
    3. Dedup check
    4. Resolve identifier → CSL-JSON
    5. Translate CSL-JSON → connector item
    6. Dry-run OR save + update session
    7. Print result
    """
    from pyzot.write.csl_json import csl_to_connector_item
    from pyzot.write.identifiers import (
        normalize_arxiv,
        normalize_doi,
        normalize_isbn,
        normalize_pmid,
    )
    from pyzot.write.preflight import check_zotero_running
    from pyzot.write.resolvers import IdentifierNotFound, resolve

    # --- 1. Write gate ---
    require_write_enabled(ctx)

    # --- Normalise identifier ---
    if kind == "doi":
        identifier = normalize_doi(identifier)
    elif kind == "arxiv":
        identifier = normalize_arxiv(identifier)
    elif kind == "pmid":
        identifier = normalize_pmid(identifier)
    elif kind == "isbn":
        identifier = normalize_isbn(identifier)

    # --- 2. Preflight ---
    connector_url = resolve_connector_url(ctx)
    if not dry_run:
        report = check_zotero_running(connector_url=connector_url)
        if not report.reachable:
            raise click.ClickException(
                f"Zotero is not running (connector not reachable at {connector_url}). "
                "Open Zotero and retry."
            )

    # --- 3. Dedup check ---
    if on_duplicate != "force-add":
        dup = _find_duplicate(kind, identifier)
        if dup is not None:
            click.echo(
                f"Item with {kind.upper()} {identifier} already exists: {dup.key} — {dup.title}"
            )
            if collection:
                _try_assign_collection(dup.item_id, collection, verbose=verbose)
            return

    # --- 4. Resolve identifier → CSL-JSON ---
    if verbose:
        click.echo(f"Resolving {kind}:{identifier} ...", err=True)

    try:
        csl = resolve(kind, identifier)
    except IdentifierNotFound as exc:
        raise click.ClickException(str(exc)) from exc
    except Exception as exc:
        raise click.ClickException(f"Resolver error for {kind}:{identifier}: {exc}") from exc

    if verbose:
        click.echo(f"Resolved: {csl.get('title', '(no title)')}", err=True)

    # --- 5. Translate CSL-JSON → connector item ---
    connector_item = csl_to_connector_item(csl)

    # Apply tags from command line to the connector item shape
    tags_list = list(tag)

    # --- 6. Dry-run ---
    if dry_run:
        payload = {
            "items": [connector_item],
            "uri": f"https://pyzot.local/add/{kind}/{identifier}",
            "sessionID": "<dry-run>",
        }
        if tags_list:
            payload["_tags"] = tags_list
        if collection:
            payload["_collection"] = collection
        click.echo(json.dumps(payload, indent=2))
        return

    # --- 7. Save + update session ---
    from pyzot.write.connector_client import ConnectorClient
    from pyzot.write.session import Session

    client = ConnectorClient(base_url=connector_url, verbose=verbose)
    session = Session(client=client)

    uri = f"https://pyzot.local/add/{kind}/{identifier}"
    result = session.save_items([connector_item], uri=uri)

    if verbose:
        click.echo(f"saveItems response: {result}", err=True)

    # Apply collection
    if collection:
        db = _open_db()
        if db is not None:
            try:
                session.set_target(collection, db=db)
                if verbose:
                    click.echo(f"Set target collection: {collection}", err=True)
            except ValueError as exc:
                click.echo(f"Warning: {exc}", err=True)
        else:
            click.echo(
                "Warning: cannot resolve collection name — database not available.", err=True
            )

    # Apply tags
    if tags_list:
        session.add_tags(tags_list)
        if verbose:
            click.echo(f"Applied tags: {tags_list}", err=True)

    # Print result
    keys = session._saved_keys
    if keys:
        click.echo(" ".join(keys))
    else:
        # Fall back to printing whatever the response contains
        click.echo(json.dumps(result, indent=2))


def _try_assign_collection(item_id: int, collection_name: str, *, verbose: bool = False) -> None:
    """Assign item_id to collection_name if not already a member. Prints result."""
    try:
        from pyzot.config import get_db_path
        from pyzot.db import ZoteroDatabase, discover_db
        from pyzot.queries.collections import get_collection_by_name
        from pyzot.write.collection_assign import assign_item_to_collection, is_item_in_collection

        db_path = get_db_path()
        if db_path is None:
            db_path = discover_db()

        with ZoteroDatabase(db_path, warn_if_open=False) as db:
            matches = get_collection_by_name(db, collection_name, fuzzy=False)
            if not matches:
                matches = get_collection_by_name(db, collection_name, fuzzy=True)
            if not matches:
                click.echo(
                    f"Warning: collection {collection_name!r} not found; could not assign.",
                    err=True,
                )
                return
            col = matches[0]
            already_in = is_item_in_collection(db, item_id, col.collection_id)

        if already_in:
            click.echo(f"Item already in collection {col.name!r}.")
            return

        inserted = assign_item_to_collection(db_path, item_id, col.collection_id)
        if inserted:
            click.echo(f"Assigned to collection {col.name!r}.")
        else:
            click.echo(f"Item already in collection {col.name!r}.")

        if verbose:
            click.echo(f"[assign] collectionID={col.collection_id} itemID={item_id}", err=True)
    except Exception as exc:
        click.echo(f"Warning: could not assign to collection: {exc}", err=True)


def _find_duplicate(kind: str, identifier: str):
    """Return an ItemRef if the identifier already exists in the DB, else None."""
    try:
        from pyzot.write import dedup

        database = _open_db()
        if database is None:
            return None

        finder = {
            "doi": dedup.find_by_doi,
            "arxiv": dedup.find_by_arxiv,
            "pmid": dedup.find_by_pmid,
            "isbn": dedup.find_by_isbn,
        }.get(kind)

        if finder is None:
            return None

        return finder(database, identifier)
    except Exception:
        return None


def _open_db():
    """Open the Zotero database in read-only mode, returning None on failure."""
    try:
        from pyzot.config import get_db_path
        from pyzot.db import ZoteroDatabase, discover_db

        db_path = get_db_path()
        if db_path is None:
            db_path = discover_db()
        return ZoteroDatabase(db_path, warn_if_open=False)
    except Exception:
        return None
