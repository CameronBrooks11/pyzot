"""URL routing and snapshot support for `zot add`."""

from __future__ import annotations

import json

import click

from . import pipeline
from .context import require_write_enabled, resolve_connector_url


def _run_url(
    ctx: click.Context,
    url: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    non_interactive: bool = False,
) -> None:
    """Route a URL to the appropriate sub-handler (arXiv/PubMed/DOI/snapshot)."""
    import re as _re

    require_write_enabled(ctx)

    url = url.strip()

    # arXiv URL
    _arxiv_url = _re.compile(
        r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)(?:\.pdf)?$",
        _re.IGNORECASE,
    )
    m_arxiv = _arxiv_url.match(url)
    if m_arxiv:
        arxiv_id = m_arxiv.group(1)
        if verbose:
            click.echo(f"Detected arXiv URL, ID={arxiv_id!r}", err=True)
        pipeline._run_add_pipeline(
            ctx,
            "arxiv",
            arxiv_id,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
        return

    # PubMed URL
    _pm_url = _re.compile(
        r"https?://(?:www\.)?(?:ncbi\.nlm\.nih\.gov/pubmed|pubmed\.ncbi\.nlm\.nih\.gov)/(\d{1,9})/?",
        _re.IGNORECASE,
    )
    m_pm = _pm_url.match(url)
    if m_pm:
        pmid = m_pm.group(1)
        if verbose:
            click.echo(f"Detected PubMed URL, PMID={pmid!r}", err=True)
        pipeline._run_add_pipeline(
            ctx,
            "pmid",
            pmid,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
        return

    # doi.org URL
    _doi_url = _re.compile(
        r"https?://(?:dx\.)?doi\.org/(10\.\d{4,9}/.+)$",
        _re.IGNORECASE,
    )
    m_doi = _doi_url.match(url)
    if m_doi:
        doi = m_doi.group(1).rstrip("/")
        if verbose:
            click.echo(f"Detected doi.org URL, DOI={doi!r}", err=True)
        pipeline._run_add_pipeline(
            ctx,
            "doi",
            doi,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
        return

    # Generic URL — try DOI in URL first, then saveSnapshot
    _doi_in_url = _re.compile(r"(10\.\d{4,9}/[^\s?&#\"'<>]+)", _re.IGNORECASE)
    m_doi2 = _doi_in_url.search(url)
    if m_doi2:
        doi = m_doi2.group(1).rstrip(".")
        if verbose:
            click.echo(f"Found DOI in generic URL: {doi!r}", err=True)
        pipeline._run_add_pipeline(
            ctx,
            "doi",
            doi,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
        return

    # Fallback: saveSnapshot
    if verbose:
        click.echo("No identifier found; falling back to saveSnapshot", err=True)
    _run_url_snapshot(
        ctx,
        url,
        collection=collection,
        tag=tag,
        dry_run=dry_run,
        verbose=verbose,
    )


def _run_url_snapshot(
    ctx: click.Context,
    url: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Fetch a page and POST it to /connector/saveSnapshot."""
    # Fetch HTML without JS rendering.
    html: str | None = None
    try:
        import httpx as _httpx

        if verbose:
            click.echo(f"Fetching {url} ...", err=True)
        with _httpx.Client(timeout=15.0, follow_redirects=True) as http_client:
            resp = http_client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (pyzot/0.2; compatible)"},
            )
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type or not content_type:
                html = resp.text
    except Exception as exc:
        if verbose:
            click.echo(f"Warning: could not fetch URL: {exc}", err=True)

    if dry_run:
        payload: dict[str, object] = {
            "url": url,
            "html": html[:500] + "…" if html and len(html) > 500 else html,
            "sessionID": "<dry-run>",
            "_type": "saveSnapshot",
        }
        if collection:
            payload["_collection"] = collection
        if tag:
            payload["_tags"] = list(tag)
        click.echo(json.dumps(payload, indent=2))
        return

    # Live save
    connector_url = resolve_connector_url(ctx)
    from pyzot.write.preflight import check_zotero_running

    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    from pyzot.write.connector_client import ConnectorClient

    client = ConnectorClient(base_url=connector_url, verbose=verbose)
    import uuid as _uuid

    session_id = _uuid.uuid4().hex

    result = client.save_snapshot(url=url, html=html, session_id=session_id)

    if verbose:
        click.echo(f"saveSnapshot response: {result}", err=True)

    # Apply collection + tags via updateSession
    tags_list = list(tag)
    if collection or tags_list:
        if collection:
            db = pipeline._open_db()
            if db is not None:
                try:
                    from pyzot.write.session import Session as _Session

                    tmp_session = _Session(client=client)
                    tmp_session.id = session_id
                    tmp_session.set_target(collection, db=db)
                except ValueError as exc:
                    click.echo(f"Warning: {exc}", err=True)
            else:
                click.echo(
                    "Warning: cannot resolve collection name — database not available.", err=True
                )
        if tags_list:
            client.update_session(session_id, tags=tags_list)

    click.echo(json.dumps(result, indent=2))
