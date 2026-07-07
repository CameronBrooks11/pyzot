"""Citation resolution pipeline for `zot add`."""

from __future__ import annotations

import json

import click

from . import pipeline
from .context import resolve_connector_url


def _run_cite_pipeline(
    ctx: click.Context,
    citation_text: str,
    *,
    threshold: int,
    gap: float,
    non_interactive: bool,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
) -> None:
    """Resolve one citation string and add it to Zotero."""
    from pyzot.write.citation_pipeline import resolve_citation

    if verbose:
        click.echo(f"Resolving citation: {citation_text[:80]!r}", err=True)

    csl = resolve_citation(
        citation_text,
        threshold=threshold,
        gap=gap,
        interactive=not non_interactive,
        console=None,
    )

    if csl is None:
        if non_interactive:
            raise click.ClickException(
                f"Could not resolve citation (non-interactive mode): {citation_text[:120]!r}\n"
                "Tip: remove --non-interactive to use interactive disambiguation."
            )
        raise click.ClickException(f"Could not resolve citation: {citation_text[:120]!r}")

    doi = csl.get("DOI") or csl.get("doi", "")

    if verbose:
        click.echo(f"Resolved DOI: {doi!r}", err=True)

    # Dedup check
    if doi and on_duplicate != "force-add":
        dup = pipeline._find_duplicate("doi", doi)
        if dup is not None:
            click.echo(f"Item with DOI {doi} already exists: {dup.key} — {dup.title}")
            if collection:
                pipeline._try_assign_collection(dup.item_id, collection, verbose=verbose)
            return

    # Translate to connector item
    from pyzot.write.csl_json import csl_to_connector_item

    connector_item = csl_to_connector_item(csl)

    tags_list = list(tag)
    uri = f"https://pyzot.local/add/cite/{doi}" if doi else "https://pyzot.local/add/cite"

    if dry_run:
        payload = {
            "items": [connector_item],
            "uri": uri,
            "sessionID": "<dry-run>",
        }
        if tags_list:
            payload["_tags"] = tags_list
        if collection:
            payload["_collection"] = collection
        click.echo(json.dumps(payload, indent=2))
        return

    # Save + update session
    connector_url = resolve_connector_url(ctx)
    from pyzot.write.preflight import check_zotero_running

    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    from pyzot.write.connector_client import ConnectorClient
    from pyzot.write.session import Session

    client = ConnectorClient(base_url=connector_url, verbose=verbose)
    session = Session(client=client)
    result = session.save_items([connector_item], uri=uri)

    if verbose:
        click.echo(f"saveItems response: {result}", err=True)

    if collection:
        db = pipeline._open_db()
        if db is not None:
            try:
                session.set_target(collection, db=db)
            except ValueError as exc:
                click.echo(f"Warning: {exc}", err=True)
        else:
            click.echo(
                "Warning: cannot resolve collection name — database not available.", err=True
            )

    if tags_list:
        session.add_tags(tags_list)

    keys = session._saved_keys
    if keys:
        click.echo(" ".join(keys))
    else:
        click.echo(json.dumps(result, indent=2))
