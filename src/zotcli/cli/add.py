"""CLI group: zot add — add items to your Zotero library.

M1 implemented `zot add status`.
M2 adds: `zot add doi`, `zot add arxiv`, `zot add pmid`, `zot add isbn`.
M3 adds: `zot add cite`, `zot add url`.
M4 adds: `zot add file`, `zot add import`.
M5 adds: `zot add "<anything>"` (auto-detect), `zot add batch <file>`.

Architecture (M5 auto-detect):
    The ``add`` group is a custom subclass of ``click.Group`` with
    ``invoke_without_command=True``.  When ``parse_args`` sees a token that
    does not match any registered subcommand name it stores it as a bare
    positional and sets ``_bare_input``.  The group callback is invoked with
    that token; it calls ``_dispatch(ctx, token, ...)`` which runs
    ``detect_kind(token)`` and forwards to the appropriate ``_run_*`` helper.

    Explicit subcommands (``zot add doi 10.x/y``) continue to work unchanged
    because Click's built-in subcommand resolution runs first.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

import click


# ---------------------------------------------------------------------------
# Custom Group: implements ``zot add "<anything>"`` via a fallback mechanism.
#
# Design:
#   ``_AddGroup`` overrides ``resolve_command`` so that when the first arg
#   does not match any registered subcommand name, it returns a synthetic
#   ``_dispatch_cmd`` instead of raising ``NoSuchCommand``.  This lets us
#   keep the group a plain ``click.Group`` (no ``invoke_without_command``,
#   no ``allow_extra_args``) so that all existing subcommands continue to
#   work without any side effects on their contexts.
#
#   The ``_dispatch_cmd`` is a normal ``click.Command`` that accepts the
#   full options (--collection, --tag, --dry-run, …) plus a positional
#   INPUT argument, and then calls ``_dispatch()``.
# ---------------------------------------------------------------------------

def _make_dispatch_command() -> click.Command:
    """Build a synthetic Click command used when no subcommand name matches."""

    @click.command("_dispatch", hidden=True,
                   short_help="Auto-detect and add by identifier.")
    @click.argument("input_value", metavar="INPUT")
    @click.option("--collection", "-c", default=None, metavar="NAME")
    @click.option("--tag", "-t", multiple=True, metavar="TEXT")
    @click.option("--dry-run", is_flag=True, default=False)
    @click.option("--on-duplicate",
                  type=click.Choice(["report", "skip", "force-add"]),
                  default="report", show_default=True)
    @click.option("-v", "--verbose", is_flag=True, default=False)
    @click.option("--non-interactive", "non_interactive", is_flag=True, default=False)
    @click.option("--with-pdf/--no-pdf", "with_pdf", default=None)
    @click.pass_context
    def _dispatch_cmd(
        ctx: click.Context,
        input_value: str,
        collection: str | None,
        tag: tuple,
        dry_run: bool,
        on_duplicate: str,
        verbose: bool,
        non_interactive: bool,
        with_pdf: bool,
    ) -> None:
        """Auto-detect input type and dispatch to the right add handler."""
        from zotcli.logging_setup import configure_logging
        configure_logging(verbose=verbose)
        _dispatch(
            ctx,
            input_value,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
            non_interactive=non_interactive,
            with_pdf=with_pdf,
        )

    return _dispatch_cmd


# Singleton dispatch command — created once
_DISPATCH_CMD = _make_dispatch_command()


class _AddGroup(click.Group):
    """click.Group subclass that falls back to auto-dispatch for bare inputs.

    When the first non-option token does not match any registered subcommand,
    ``resolve_command`` returns ``_DISPATCH_CMD`` instead of raising an error.
    The unrecognised token becomes the ``INPUT`` argument of ``_DISPATCH_CMD``.
    All registered subcommands work exactly as before.
    """

    def resolve_command(
        self, ctx: click.Context, args: list[str]
    ) -> tuple[str | None, click.Command | None, list[str]]:
        try:
            return super().resolve_command(ctx, args)
        except click.UsageError:
            # No matching subcommand — treat the first token as a bare input.
            # args[0] is the unknown token; pass the whole list to _DISPATCH_CMD.
            if args:
                return args[0], _DISPATCH_CMD, args
            return None, None, args


# ---------------------------------------------------------------------------
# Top-level add group
# ---------------------------------------------------------------------------

@click.group("add", cls=_AddGroup)
@click.pass_context
def add(ctx: click.Context) -> None:
    """Add items to your Zotero library via the connector.

    When called with a single positional argument (no subcommand),
    automatically detects what kind of input it is (DOI, arXiv ID, PMID,
    ISBN, URL, citation string, or local file path) and dispatches to the
    right handler.

    Examples:

    \b
        zot add "10.1109/TPWRS.2023.1234567"        # auto-detect DOI
        zot add "2401.12345"                        # auto-detect arXiv
        zot add "Zhang, J. et al. (2025) Beyond..."  # auto-detect citation
        zot add "/home/me/paper.pdf"                # auto-detect file
        zot add doi 10.1109/X                       # explicit subcommand
        zot add batch papers.txt                    # batch mode

    Subcommands are still available for explicit use in scripts.
    """
    # Group callback — nothing to do here; subcommands handle their own logic.


def _dispatch(
    ctx: click.Context,
    input_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    non_interactive: bool,
    with_pdf: bool = False,
) -> None:
    """Detect the kind of *input_value* and dispatch to the appropriate handler.

    Routing table:
        "doi"       → _run_doi
        "arxiv"     → _run_arxiv
        "pmid"      → _run_pmid
        "isbn"      → _run_isbn
        "url"       → _run_url (which itself sub-routes by URL pattern)
        "citation"  → _run_cite_pipeline
        "filepath"  → _run_file if PDF/EPUB, else _run_import
        "unknown"   → ClickException with clear message
    """
    from zotcli.write.identifiers import detect_kind

    kind = detect_kind(input_value)

    if verbose:
        click.echo(f"Detected kind: {kind!r} for input: {input_value[:80]!r}", err=True)

    if kind == "doi":
        _run_doi(ctx, input_value,
                 collection=collection, tag=tag,
                 dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                 with_pdf=with_pdf, non_interactive=non_interactive)
    elif kind == "arxiv":
        _run_arxiv(ctx, input_value,
                   collection=collection, tag=tag,
                   dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                   with_pdf=with_pdf, non_interactive=non_interactive)
    elif kind == "pmid":
        _run_pmid(ctx, input_value,
                  collection=collection, tag=tag,
                  dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                  with_pdf=with_pdf, non_interactive=non_interactive)
    elif kind == "isbn":
        _run_isbn(ctx, input_value,
                  collection=collection, tag=tag,
                  dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                  with_pdf=with_pdf, non_interactive=non_interactive)
    elif kind == "url":
        _run_url(ctx, input_value,
                 collection=collection, tag=tag,
                 dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                 with_pdf=with_pdf, non_interactive=non_interactive)
    elif kind == "citation":
        _run_cite_pipeline(
            ctx, input_value,
            threshold=50, gap=1.4,
            non_interactive=non_interactive,
            collection=collection, tag=tag,
            dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
            with_pdf=with_pdf,
        )
    elif kind == "filepath":
        _run_filepath(ctx, input_value,
                      collection=collection, tag=tag,
                      dry_run=dry_run, verbose=verbose)
    else:
        raise click.ClickException(
            f"Cannot determine input type for: {input_value!r}\n"
            "Supported kinds: DOI (10.NNNN/...), arXiv ID (YYMM.NNNNN), "
            "PMID (numeric), ISBN, URL (https://...), "
            "citation string (free text with spaces), "
            "local file path (/path/to/file.pdf).\n"
            "Use an explicit subcommand for unambiguous dispatch: "
            "`zot add doi`, `zot add arxiv`, `zot add cite`, etc."
        )


# ---------------------------------------------------------------------------
# Common options shared by doi/arxiv/pmid/isbn commands
# ---------------------------------------------------------------------------

_COMMON_ADD_OPTIONS = [
    click.option(
        "--collection", "-c",
        default=None,
        metavar="NAME",
        help="Collection name to add the item to.",
    ),
    click.option(
        "--tag", "-t",
        multiple=True,
        metavar="TEXT",
        help="Tag to apply (repeatable).",
    ),
    click.option(
        "--dry-run",
        is_flag=True,
        default=False,
        help="Print the JSON that would be POSTed without making any request to the connector.",
    ),
    click.option(
        "--on-duplicate",
        type=click.Choice(["report", "skip", "force-add"]),
        default="report",
        show_default=True,
        help="Behaviour when a duplicate is found.",
    ),
    click.option(
        "-v", "--verbose",
        is_flag=True,
        default=False,
        help="Print verbose HTTP request/response info.",
    ),
    click.option(
        "--with-pdf/--no-pdf",
        "with_pdf",
        default=None,
        help=(
            "Attach a PDF to the saved item via the 4-resolver find-file pipeline "
            "(doi / item URL / Zotero OA endpoint / custom resolvers). Defaults to "
            "the value of config key `autoattach.enabled` (default: on). "
            "Use --no-pdf to opt out for a single command."
        ),
    ),
    click.option(
        "--non-interactive",
        "non_interactive",
        is_flag=True,
        default=False,
        help="Never prompt (e.g. for Unpaywall setup); skip PDF retrieval silently.",
    ),
]


def _apply_common_options(func):
    """Decorator that applies all common add options to a command."""
    for option in reversed(_COMMON_ADD_OPTIONS):
        func = option(func)
    return func


# ---------------------------------------------------------------------------
# Core helper: _run_add_pipeline (used by doi/arxiv/pmid/isbn commands + dispatcher)
# ---------------------------------------------------------------------------

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
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Shared implementation for doi/arxiv/pmid/isbn add commands.

    Steps:
    1. Write gate
    2. Preflight (Zotero running?)
    3. Dedup check
    4. Resolve identifier → CSL-JSON
    5. Translate CSL-JSON → connector item
    6. Dry-run OR save + update session
    7. Optional: attach PDF via --with-pdf
    8. Print result
    """
    from zotcli.config import get_connector_url
    from zotcli.write.csl_json import csl_to_connector_item
    from zotcli.write.identifiers import (
        normalize_arxiv,
        normalize_doi,
        normalize_isbn,
        normalize_pmid,
    )
    from zotcli.write.preflight import check_zotero_running
    from zotcli.write.resolvers import IdentifierNotFound, resolve

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
    connector_url = _resolve_connector_url(ctx)
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
                f"Item with {kind.upper()} {identifier} already exists: "
                f"{dup.key} — {dup.title}"
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
            "uri": f"https://zotcli.local/add/{kind}/{identifier}",
            "sessionID": "<dry-run>",
        }
        if tags_list:
            payload["_tags"] = tags_list
        if collection:
            payload["_collection"] = collection
        click.echo(json.dumps(payload, indent=2))
        return

    # --- 7. Save + update session ---
    from zotcli.write.connector_client import ConnectorClient
    from zotcli.write.session import Session

    client = ConnectorClient(base_url=connector_url, verbose=verbose)
    session = Session(client=client)

    uri = f"https://zotcli.local/add/{kind}/{identifier}"
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

    # --- 8. Attach PDF (default on; --no-pdf to opt out) ---
    if with_pdf is None:
        with_pdf = _autoattach_enabled()
    if with_pdf and not dry_run:
        doi_for_pdf: str | None = None
        if kind == "doi":
            doi_for_pdf = identifier
        else:
            doi_for_pdf = csl.get("DOI") or csl.get("doi") or None

        url_for_pdf: str | None = csl.get("URL") or csl.get("url") or None

        parent_key = keys[0] if keys else None
        _run_pdf_attachment(
            ctx,
            doi=doi_for_pdf,
            session=session,
            parent_key=parent_key,
            verbose=verbose,
            non_interactive=non_interactive,
            item_url=url_for_pdf,
        )


# ---------------------------------------------------------------------------
# Per-kind runner helpers (used by both subcommands and the dispatcher)
# ---------------------------------------------------------------------------

def _run_doi(
    ctx: click.Context,
    doi_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Run the DOI add pipeline."""
    _run_add_pipeline(
        ctx, "doi", doi_value,
        collection=collection, tag=tag,
        dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
        with_pdf=with_pdf, non_interactive=non_interactive,
    )


def _run_arxiv(
    ctx: click.Context,
    arxiv_id: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Run the arXiv add pipeline."""
    _run_add_pipeline(
        ctx, "arxiv", arxiv_id,
        collection=collection, tag=tag,
        dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
        with_pdf=with_pdf, non_interactive=non_interactive,
    )


def _run_pmid(
    ctx: click.Context,
    pmid_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Run the PMID add pipeline."""
    _run_add_pipeline(
        ctx, "pmid", pmid_value,
        collection=collection, tag=tag,
        dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
        with_pdf=with_pdf, non_interactive=non_interactive,
    )


def _run_isbn(
    ctx: click.Context,
    isbn_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Run the ISBN add pipeline."""
    _run_add_pipeline(
        ctx, "isbn", isbn_value,
        collection=collection, tag=tag,
        dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
        with_pdf=with_pdf, non_interactive=non_interactive,
    )


def _run_url(
    ctx: click.Context,
    url: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool = False,
    non_interactive: bool = False,
) -> None:
    """Route a URL to the appropriate sub-handler (arXiv/PubMed/DOI/IEEE/SD/snapshot)."""
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
        _run_add_pipeline(
            ctx, "arxiv", arxiv_id,
            collection=collection, tag=tag,
            dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
            with_pdf=with_pdf, non_interactive=non_interactive,
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
        _run_add_pipeline(
            ctx, "pmid", pmid,
            collection=collection, tag=tag,
            dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
            with_pdf=with_pdf, non_interactive=non_interactive,
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
        _run_add_pipeline(
            ctx, "doi", doi,
            collection=collection, tag=tag,
            dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
            with_pdf=with_pdf, non_interactive=non_interactive,
        )
        return

    # IEEE Xplore
    if "ieeexplore.ieee.org" in url.lower():
        from zotcli.write.resolvers.ieee import url_to_doi as ieee_url_to_doi
        if verbose:
            click.echo("Detected IEEE Xplore URL, extracting DOI...", err=True)
        doi = ieee_url_to_doi(url)
        if doi:
            if verbose:
                click.echo(f"IEEE resolved DOI: {doi!r}", err=True)
            _run_add_pipeline(
                ctx, "doi", doi,
                collection=collection, tag=tag,
                dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                with_pdf=with_pdf, non_interactive=non_interactive,
            )
            return
        else:
            _run_url_snapshot(
                ctx, url,
                collection=collection, tag=tag,
                dry_run=dry_run, verbose=verbose,
            )
            return

    # ScienceDirect / Elsevier
    if "sciencedirect.com" in url.lower():
        from zotcli.write.resolvers.sciencedirect import url_to_doi as sd_url_to_doi
        if verbose:
            click.echo("Detected ScienceDirect URL, extracting DOI...", err=True)
        doi = sd_url_to_doi(url)
        if doi:
            if verbose:
                click.echo(f"ScienceDirect resolved DOI: {doi!r}", err=True)
            _run_add_pipeline(
                ctx, "doi", doi,
                collection=collection, tag=tag,
                dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
                with_pdf=with_pdf, non_interactive=non_interactive,
            )
            return
        else:
            _run_url_snapshot(
                ctx, url,
                collection=collection, tag=tag,
                dry_run=dry_run, verbose=verbose,
            )
            return

    # Generic URL — try DOI in URL first, then saveSnapshot
    _doi_in_url = _re.compile(r"(10\.\d{4,9}/[^\s?&#\"'<>]+)", _re.IGNORECASE)
    m_doi2 = _doi_in_url.search(url)
    if m_doi2:
        doi = m_doi2.group(1).rstrip(".")
        if verbose:
            click.echo(f"Found DOI in generic URL: {doi!r}", err=True)
        _run_add_pipeline(
            ctx, "doi", doi,
            collection=collection, tag=tag,
            dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
            with_pdf=with_pdf, non_interactive=non_interactive,
        )
        return

    # Fallback: saveSnapshot
    if verbose:
        click.echo("No identifier found; falling back to saveSnapshot", err=True)
    _run_url_snapshot(
        ctx, url,
        collection=collection, tag=tag,
        dry_run=dry_run, verbose=verbose,
    )


def _run_filepath(
    ctx: click.Context,
    path_value: str,
    *,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Route a local file path to `file` (PDF/EPUB) or `import` (bibliography)."""
    from pathlib import Path as _Path

    from zotcli.write.pdf import sniff_mime

    fpath = _Path(path_value).expanduser().resolve()

    if not fpath.exists():
        raise click.ClickException(f"File not found: {fpath}")

    mime = sniff_mime(fpath)
    if mime in ("application/pdf", "application/epub+zip"):
        _run_file(
            ctx, str(fpath),
            collection=collection, tag=tag,
            dry_run=dry_run, wait_recognize=30, verbose=verbose,
        )
    else:
        _run_import(
            ctx, str(fpath),
            collection=collection, tag=tag,
            dry_run=dry_run, verbose=verbose,
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

    from zotcli.write.pdf import human_size, sniff_mime

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
            "Only PDF and EPUB files are supported by `zot add file`. "
            "To import bibliography data (.bib, .ris, .json) use `zot add import`."
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
    connector_url = _resolve_connector_url(ctx)
    from zotcli.write.preflight import check_zotero_running
    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    import uuid as _uuid
    from zotcli.write.connector_client import ConnectorClient
    session_id = _uuid.uuid4().hex
    client = ConnectorClient(base_url=connector_url, verbose=verbose)

    if verbose:
        click.echo(
            f"Uploading {fpath.name} ({human_size(file_size)}, {mime}) ...", err=True
        )

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
        from zotcli.write.session import Session as _Session
        tmp_session = _Session(client=client)
        tmp_session.id = session_id
        if collection:
            db = _open_db()
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

        from zotcli.config import get_db_path
        from zotcli.db import discover_db

        try:
            db_path = get_db_path() or discover_db()
        except Exception:
            db_path = None

        parent_ref = None
        if db_path is not None and attachment_key:
            from zotcli.write.recognize import wait_for_recognized_parent
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

    from zotcli.write.pdf import sniff_import_content_type

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
    connector_url = _resolve_connector_url(ctx)
    from zotcli.write.preflight import check_zotero_running
    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    import uuid as _uuid
    from zotcli.write.connector_client import ConnectorClient
    session_id = _uuid.uuid4().hex
    client = ConnectorClient(base_url=connector_url, verbose=verbose)

    if verbose:
        click.echo(
            f"Importing {fpath.name} ({len(body)} bytes, {content_type}) ...", err=True
        )

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
        from zotcli.write.session import Session as _Session
        tmp_session = _Session(client=client)
        tmp_session.id = session_id
        if collection:
            db = _open_db()
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


def _try_assign_collection(item_id: int, collection_name: str, *, verbose: bool = False) -> None:
    """Assign item_id to collection_name if not already a member. Prints result."""
    try:
        from zotcli.config import get_db_path
        from zotcli.db import ZoteroDatabase, discover_db
        from zotcli.queries.collections import get_collection_by_name
        from zotcli.write.collection_assign import assign_item_to_collection, is_item_in_collection

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
            click.echo(
                f"[assign] collectionID={col.collection_id} itemID={item_id}", err=True
            )
    except Exception as exc:
        click.echo(f"Warning: could not assign to collection: {exc}", err=True)


def _find_duplicate(kind: str, identifier: str):
    """Return an ItemRef if the identifier already exists in the DB, else None."""
    try:
        from zotcli import db as _db_module
        from zotcli.write import dedup

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


def _autoattach_enabled() -> bool:
    """Return the resolved default for --with-pdf.

    Reads ``autoattach.enabled`` from zotcli-home config.toml. Default: True.
    """
    try:
        from zotcli.config import get_config_value
        raw = get_config_value("autoattach.enabled")
        if raw is None:
            return True
        return raw.lower() not in ("false", "0", "no", "off")
    except Exception:
        return True


def _open_db():
    """Open the Zotero database in read-only mode, returning None on failure."""
    try:
        from zotcli.config import get_db_path
        from zotcli.db import ZoteroDatabase, discover_db

        db_path = get_db_path()
        if db_path is None:
            db_path = discover_db()
        return ZoteroDatabase(db_path, warn_if_open=False)
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Individual add subcommands  (thin wrappers over the _run_* helpers)
# ---------------------------------------------------------------------------

@add.command("status")
@click.pass_context
def add_status(ctx: click.Context):
    """Check whether Zotero is running and report the current target.

    Prints reachability, selected collection, connector URL, and a hint
    about enabling write capability if not already enabled.
    """
    from zotcli.config import get_connector_url, get_write_enabled
    from zotcli.write.preflight import check_zotero_running

    # Resolve connector URL from: CLI flag > config > default
    connector_url = _resolve_connector_url(ctx)

    click.echo(f"Connector URL : {connector_url}")

    report = check_zotero_running(connector_url=connector_url)

    if report.reachable:
        click.echo("Zotero status : reachable ✓")
        if report.version:
            click.echo(f"Version       : {report.version}")
        if report.selected_collection:
            click.echo(f"Selected coll : {report.selected_collection}")
        else:
            click.echo("Selected coll : (none)")
    else:
        click.echo("Zotero status : not reachable ✗")
        if report.error:
            click.echo(f"Error         : {report.error}", err=True)

    # Write-enabled hint
    write_ok = get_write_enabled()
    allow_write_flag = getattr(ctx.obj, "allow_write", False) if ctx.obj else False
    allow_write_env = os.environ.get("ZOTCLI_ALLOW_WRITE", "0") not in ("0", "", "false", "False")

    if write_ok or allow_write_flag or allow_write_env:
        click.echo("Write enabled : yes")
    else:
        click.echo("Write enabled : no")
        click.echo(
            "Hint: run `zot config set write.enabled true` to enable write capability, "
            "or pass --allow-write per command."
        )


@add.command("doi")
@click.argument("doi_value")
@_apply_common_options
@click.pass_context
def add_doi(
    ctx: click.Context,
    doi_value: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
    non_interactive: bool,
) -> None:
    """Add an item by DOI.

    DOI_VALUE may be a bare DOI (10.NNNN/...), a doi: prefixed string,
    or a full https://doi.org/... URL.

    Example:

        zot add doi 10.1038/s41586-020-2649-2 --collection Inbox --tag to-read

        zot add doi 10.1109/X --with-pdf   # also attach an open-access PDF
    """
    _run_doi(ctx, doi_value,
             collection=collection, tag=tag,
             dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
             with_pdf=with_pdf, non_interactive=non_interactive)


@add.command("arxiv")
@click.argument("arxiv_id")
@_apply_common_options
@click.pass_context
def add_arxiv(
    ctx: click.Context,
    arxiv_id: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
    non_interactive: bool,
) -> None:
    """Add an item by arXiv ID.

    ARXIV_ID may be a modern (YYMM.NNNNN) or legacy (archive/NNNNNNN) ID,
    with or without an "arxiv:" prefix or version suffix.

    Example:

        zot add arxiv 2401.12345 --collection Preprints
    """
    _run_arxiv(ctx, arxiv_id,
               collection=collection, tag=tag,
               dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
               with_pdf=with_pdf, non_interactive=non_interactive)


@add.command("pmid")
@click.argument("pmid_value")
@_apply_common_options
@click.pass_context
def add_pmid(
    ctx: click.Context,
    pmid_value: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
    non_interactive: bool,
) -> None:
    """Add an item by PubMed ID (PMID).

    PMID_VALUE is a numeric PubMed identifier.

    Example:

        zot add pmid 31452104 --collection Biology
    """
    _run_pmid(ctx, pmid_value,
              collection=collection, tag=tag,
              dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
              with_pdf=with_pdf, non_interactive=non_interactive)


@add.command("isbn")
@click.argument("isbn_value")
@_apply_common_options
@click.pass_context
def add_isbn(
    ctx: click.Context,
    isbn_value: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
    non_interactive: bool,
) -> None:
    """Add an item by ISBN (10 or 13 digit).

    ISBN_VALUE may include hyphens or spaces.

    Example:

        zot add isbn 978-0-262-03384-8 --collection Books
    """
    _run_isbn(ctx, isbn_value,
              collection=collection, tag=tag,
              dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
              with_pdf=with_pdf, non_interactive=non_interactive)


# ---------------------------------------------------------------------------
# M3: zot add cite
# ---------------------------------------------------------------------------

@add.command("cite")
@click.argument("citation_text", required=False, default=None)
@click.option("--file", "-f", "refs_file", type=click.Path(exists=True), default=None,
              help="Path to a file with one citation per line.")
@click.option("--threshold", type=int, default=50, show_default=True,
              help="Minimum Crossref score to auto-accept the top result.")
@click.option("--gap", type=float, default=1.4, show_default=True,
              help="Minimum score ratio (top/second) for unambiguous auto-accept.")
@_apply_common_options
@click.pass_context
def add_cite(
    ctx: click.Context,
    citation_text: str | None,
    refs_file: str | None,
    threshold: int,
    gap: float,
    non_interactive: bool,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
) -> None:
    """Add an item from a free-text citation string.

    CITATION_TEXT is a bibliographic reference string, e.g.:

        zot add cite "Zhang, J. et al. (2025) Beyond simplifications..."

    Use --file to provide multiple citations (one per line, blank lines and
    '#' comments are skipped). Each resolved citation is added as a separate item.

    Example:

        zot add cite "Smith, J. (2020) My Paper. Nature, 585, 357-362."

        zot add cite --file refs.txt --collection "Inbox" --tag to-read
    """
    # --- Write gate ---
    require_write_enabled(ctx)

    # Collect lines to process
    lines: list[str] = []

    if refs_file:
        with open(refs_file, encoding="utf-8") as fh:
            for raw_line in fh:
                stripped = raw_line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                lines.append(stripped)
    elif citation_text:
        lines = [citation_text.strip()]
    else:
        raise click.UsageError(
            "Provide a CITATION_TEXT argument or --file with a file of citations."
        )

    any_failed = False
    for line in lines:
        try:
            _run_cite_pipeline(
                ctx,
                citation_text=line,
                threshold=threshold,
                gap=gap,
                non_interactive=non_interactive,
                collection=collection,
                tag=tag,
                dry_run=dry_run,
                on_duplicate=on_duplicate,
                verbose=verbose,
                with_pdf=with_pdf,
            )
        except click.ClickException as exc:
            if len(lines) > 1:
                # In batch mode, report and continue
                click.echo(f"Could not resolve: {line[:80]!r} — {exc.format_message()}", err=True)
                any_failed = True
            else:
                raise

    if any_failed:
        raise SystemExit(1)


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
    with_pdf: bool = False,
) -> None:
    """Resolve one citation string and add it to Zotero."""
    from zotcli.write.citation_pipeline import resolve_citation

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
        raise click.ClickException(
            f"Could not resolve citation: {citation_text[:120]!r}"
        )

    doi = csl.get("DOI") or csl.get("doi", "")

    if verbose:
        click.echo(f"Resolved DOI: {doi!r}", err=True)

    # Dedup check
    if doi and on_duplicate != "force-add":
        dup = _find_duplicate("doi", doi)
        if dup is not None:
            click.echo(
                f"Item with DOI {doi} already exists: {dup.key} — {dup.title}"
            )
            if collection:
                _try_assign_collection(dup.item_id, collection, verbose=verbose)
            return

    # Translate to connector item
    from zotcli.write.csl_json import csl_to_connector_item
    connector_item = csl_to_connector_item(csl)

    tags_list = list(tag)
    uri = f"https://zotcli.local/add/cite/{doi}" if doi else "https://zotcli.local/add/cite"

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
    connector_url = _resolve_connector_url(ctx)
    from zotcli.write.preflight import check_zotero_running
    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    from zotcli.write.connector_client import ConnectorClient
    from zotcli.write.session import Session

    client = ConnectorClient(base_url=connector_url, verbose=verbose)
    session = Session(client=client)
    result = session.save_items([connector_item], uri=uri)

    if verbose:
        click.echo(f"saveItems response: {result}", err=True)

    if collection:
        db = _open_db()
        if db is not None:
            try:
                session.set_target(collection, db=db)
            except ValueError as exc:
                click.echo(f"Warning: {exc}", err=True)
        else:
            click.echo("Warning: cannot resolve collection name — database not available.", err=True)

    if tags_list:
        session.add_tags(tags_list)

    keys = session._saved_keys
    if keys:
        click.echo(" ".join(keys))
    else:
        click.echo(json.dumps(result, indent=2))

    # Attach PDF (default on; --no-pdf to opt out)
    if with_pdf is None:
        with_pdf = _autoattach_enabled()
    if with_pdf and not dry_run:
        parent_key = keys[0] if keys else None
        url_for_pdf: str | None = csl.get("URL") or csl.get("url") or None
        _run_pdf_attachment(
            ctx,
            doi=doi or None,
            session=session,
            parent_key=parent_key,
            verbose=verbose,
            non_interactive=non_interactive,
            item_url=url_for_pdf,
        )


# ---------------------------------------------------------------------------
# M3: zot add url
# ---------------------------------------------------------------------------

@add.command("url")
@click.argument("url_value")
@_apply_common_options
@click.pass_context
def add_url(
    ctx: click.Context,
    url_value: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    with_pdf: bool,
    non_interactive: bool,
) -> None:
    """Add an item from a URL.

    Auto-routes based on URL pattern:

    \b
    - arXiv URL → arXiv ID → resolver chain
    - PubMed URL → PMID → resolver chain
    - IEEE Xplore URL → DOI extraction → add by DOI
    - ScienceDirect URL → DOI extraction → add by DOI
    - doi.org URL → add by DOI
    - Generic URL → saveSnapshot (Zotero translators run on fetched HTML)

    Example:

        zot add url https://ieeexplore.ieee.org/document/9876543

        zot add url https://www.sciencedirect.com/science/article/pii/S2352467725000XYZ

        zot add url https://arxiv.org/abs/2401.12345
    """
    _run_url(ctx, url_value,
             collection=collection, tag=tag,
             dry_run=dry_run, on_duplicate=on_duplicate, verbose=verbose,
             with_pdf=with_pdf, non_interactive=non_interactive)


# ---------------------------------------------------------------------------
# M4: zot add file
# ---------------------------------------------------------------------------

@add.command("file")
@click.argument("path", type=click.Path(exists=True, path_type=str))
@click.option("--collection", "-c", default=None, metavar="NAME",
              help="Collection name to add the attachment to.")
@click.option("--tag", "-t", multiple=True, metavar="TEXT",
              help="Tag to apply (repeatable).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print upload metadata without sending the file.")
@click.option("--wait-recognize", "wait_recognize", type=int, default=30, show_default=True,
              help="Seconds to poll for a recognised parent (0 to skip).")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Print verbose HTTP request/response info.")
@click.pass_context
def add_file(
    ctx: click.Context,
    path: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    wait_recognize: int,
    verbose: bool,
) -> None:
    """Upload a local PDF or EPUB file as a standalone attachment.

    Zotero will automatically attempt to recognise the parent reference from
    the file (using RecognizeDocument). Use --wait-recognize to control how
    long to poll for the result (default 30 seconds; 0 to skip polling).

    Example:

        zot add file ~/Downloads/paper.pdf --collection Inbox --tag ml

        zot add file ~/Downloads/paper.pdf --dry-run
    """
    _run_file(ctx, path,
              collection=collection, tag=tag,
              dry_run=dry_run, wait_recognize=wait_recognize, verbose=verbose)


# ---------------------------------------------------------------------------
# M4: zot add import
# ---------------------------------------------------------------------------

@add.command("import")
@click.argument("path", type=click.Path(exists=True, path_type=str))
@click.option("--collection", "-c", default=None, metavar="NAME",
              help="Collection name to add imported items to.")
@click.option("--tag", "-t", multiple=True, metavar="TEXT",
              help="Tag to apply (repeatable).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Print first 200 bytes and sniffed content-type without importing.")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Print verbose HTTP request/response info.")
@click.pass_context
def add_import(
    ctx: click.Context,
    path: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    verbose: bool,
) -> None:
    """Import bibliography data from a RIS, BibTeX, or CSL-JSON file.

    Sends the raw file bytes to Zotero's /connector/import endpoint, which
    auto-detects the format via built-in import translators.

    Supported formats:

    \b
    - .ris    → application/x-research-info-systems
    - .bib    → application/x-bibtex
    - .bibtex → application/x-bibtex
    - .json   → application/vnd.citationstyles.csl+json

    Example:

        zot add import refs.bib --collection "Imports/2026-05"

        zot add import refs.ris --tag imported --dry-run
    """
    _run_import(ctx, path,
                collection=collection, tag=tag,
                dry_run=dry_run, verbose=verbose)


# ---------------------------------------------------------------------------
# M5: zot add batch <path>
# ---------------------------------------------------------------------------

@add.command("batch")
@click.argument("path", metavar="FILE")
@click.option("--collection", "-c", default=None, metavar="NAME",
              help="Collection name applied to all items.")
@click.option("--tag", "-t", multiple=True, metavar="TEXT",
              help="Tag to apply to all items (repeatable).")
@click.option("--dry-run", is_flag=True, default=False,
              help="Resolve and print what would be submitted without making connector calls.")
@click.option("--on-duplicate",
              type=click.Choice(["report", "skip", "force-add"]),
              default="report", show_default=True,
              help="Behaviour when a duplicate is found.")
@click.option("-v", "--verbose", is_flag=True, default=False,
              help="Print verbose HTTP request/response info.")
@click.option("--non-interactive", "non_interactive", is_flag=True, default=False,
              help="Never prompt; fail/skip ambiguous citations.")
@click.option("--jobs", "jobs", type=int, default=1, show_default=True,
              help="(Stub — reserved for parallel resolver lookups in v0.3.0; currently no-op.)")
@click.pass_context
def add_batch(
    ctx: click.Context,
    path: str,
    collection: str | None,
    tag: tuple,
    dry_run: bool,
    on_duplicate: str,
    verbose: bool,
    non_interactive: bool,
    jobs: int,
) -> None:
    """Process a file of inputs, one per line.

    FILE may be ``-`` to read from stdin.  Each line is passed through the
    same auto-detect dispatcher as ``zot add "<anything>"``.

    Lines that start with ``#`` or are blank are silently skipped.

    After processing all lines a summary table is printed and, if any lines
    failed, the command exits with code 1.

    Note: ``--jobs N`` (N > 1) is reserved for parallel resolver lookups in
    a future release.  Currently it is accepted but has no effect.

    Example:

    \b
        zot add batch papers.txt --collection "Smart Grid"
        cat dois.txt | zot add batch - --tag imported
    """
    from zotcli.logging_setup import configure_logging
    configure_logging(verbose=verbose)

    # Read input lines
    if path == "-":
        lines_raw = sys.stdin.readlines()
    else:
        from pathlib import Path as _Path
        input_path = _Path(path)
        if not input_path.exists():
            raise click.ClickException(f"File not found: {path}")
        lines_raw = input_path.read_text(encoding="utf-8").splitlines()

    # Parse: strip, skip blank and comment lines
    inputs: list[str] = []
    for raw in lines_raw:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        inputs.append(stripped)

    if not inputs:
        click.echo("No inputs to process.", err=True)
        return

    if jobs > 1:
        click.echo(
            f"Note: --jobs {jobs} is a stub in this release; running sequentially.", err=True
        )

    # Process each line sequentially
    results: list[dict] = []  # {input, kind, status, message}

    from zotcli.write.identifiers import detect_kind

    for inp in inputs:
        kind = detect_kind(inp)
        try:
            _dispatch(
                ctx, inp,
                collection=collection, tag=tag,
                dry_run=dry_run, on_duplicate=on_duplicate,
                verbose=verbose, non_interactive=non_interactive,
            )
            results.append({"input": inp, "kind": kind, "status": "ok", "message": ""})
        except (click.ClickException, SystemExit, Exception) as exc:
            msg = getattr(exc, "format_message", None)
            if callable(msg):
                msg = msg()
            else:
                msg = str(exc)
            results.append({"input": inp, "kind": kind, "status": "fail", "message": msg})

    # Print summary table
    _print_batch_summary(results)

    # Exit code: 1 if any failures
    n_failed = sum(1 for r in results if r["status"] == "fail")
    if n_failed:
        sys.exit(1)


def _print_batch_summary(results: list[dict]) -> None:
    """Print a per-line status table and a summary line."""
    try:
        from rich.table import Table
        from rich.console import Console

        table = Table(title="Batch results", show_header=True, header_style="bold")
        table.add_column("Input", max_width=60, no_wrap=True)
        table.add_column("Kind", width=10)
        table.add_column("Status", width=7)
        table.add_column("Message", max_width=50, no_wrap=True)

        for r in results:
            status_style = "green" if r["status"] == "ok" else "red"
            table.add_row(
                r["input"][:60],
                r["kind"],
                f"[{status_style}]{r['status']}[/{status_style}]",
                r["message"][:50],
            )

        console = Console()
        console.print(table)
    except ImportError:
        # Fallback: plain text
        for r in results:
            mark = "OK" if r["status"] == "ok" else "FAIL"
            click.echo(f"[{mark}] {r['kind']}: {r['input'][:60]}" + (
                f" — {r['message'][:50]}" if r["message"] else ""
            ))

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = 0  # currently no "skip" status (duplicates are counted as ok)
    click.echo(f"{n_ok} added, {n_skip} skipped, {n_fail} failed.")


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
    # Fetch HTML (no JS rendering — that's M6/Playwright)
    html: str | None = None
    try:
        import httpx as _httpx
        if verbose:
            click.echo(f"Fetching {url} ...", err=True)
        with _httpx.Client(timeout=15.0, follow_redirects=True) as client:
            resp = client.get(
                url,
                headers={"User-Agent": "Mozilla/5.0 (zotcli/0.2; compatible)"},
            )
        if resp.status_code == 200:
            content_type = resp.headers.get("content-type", "")
            if "html" in content_type or not content_type:
                html = resp.text
    except Exception as exc:
        if verbose:
            click.echo(f"Warning: could not fetch URL: {exc}", err=True)

    if dry_run:
        payload = {
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
    connector_url = _resolve_connector_url(ctx)
    from zotcli.write.preflight import check_zotero_running
    report = check_zotero_running(connector_url=connector_url)
    if not report.reachable:
        raise click.ClickException(
            f"Zotero is not running (connector not reachable at {connector_url}). "
            "Open Zotero and retry."
        )

    from zotcli.write.connector_client import ConnectorClient
    from zotcli.write.session import Session

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
            db = _open_db()
            if db is not None:
                try:
                    from zotcli.write.session import Session as _Session
                    tmp_session = _Session(client=client)
                    tmp_session.id = session_id
                    tmp_session.set_target(collection, db=db)
                except ValueError as exc:
                    click.echo(f"Warning: {exc}", err=True)
            else:
                click.echo("Warning: cannot resolve collection name — database not available.", err=True)
        if tags_list:
            client.update_session(session_id, tags=tags_list)

    click.echo(json.dumps(result, indent=2))


# ---------------------------------------------------------------------------
# Helper functions (used by status and write commands)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# M6: PDF attachment pipeline
# ---------------------------------------------------------------------------

# Elsevier/ScienceDirect DOI prefixes (incomplete but covers the main ones)
_ELSEVIER_PREFIXES = ("10.1016/", "10.1006/", "10.1053/", "10.1067/", "10.1078/")


def _is_ieee_doi(doi: str) -> bool:
    """Return True if the DOI is from IEEE (10.1109/...)."""
    return doi.startswith("10.1109/")


def _is_elsevier_doi(doi: str) -> bool:
    """Return True if the DOI is from Elsevier/ScienceDirect."""
    return any(doi.startswith(p) for p in _ELSEVIER_PREFIXES)


def _publisher_cookies_exist(service: str) -> bool:
    """Return True if a browser profile exists for the given service."""
    from zotcli.paths import cookies_root
    profile_dir = cookies_root() / service
    # Playwright creates a Default/ directory inside the user-data-dir when first used
    return profile_dir.exists() and any(profile_dir.iterdir())


def _prompt_unpaywall_setup(ctx: click.Context, non_interactive: bool) -> bool:
    """Prompt the user to configure Unpaywall (§8.7 cascade).

    If *non_interactive* is True, silently returns False.

    Returns True if the user successfully completed Unpaywall setup,
    False if they chose to skip, and raises ClickException if they abort.
    """
    if non_interactive:
        click.echo(
            "[info] --with-pdf: Unpaywall not configured; skipping PDF retrieval "
            "(--non-interactive mode).",
            err=True,
        )
        return False

    click.echo(
        "\n[warn] Unpaywall is opt-in and not configured.\n"
        "       Run `zot add login --service unpaywall` first, or pass --no-pdf to skip PDF retrieval.\n"
        "       (Press Y to configure Unpaywall now / N to skip PDF / q to abort): ",
        nl=False,
    )
    try:
        choice = input().strip().lower()
    except EOFError:
        choice = "n"

    if choice == "q":
        raise click.ClickException("Aborted by user.")
    if choice == "y":
        # Inline Unpaywall login flow
        _inline_unpaywall_login()
        return True
    # 'n' or anything else → skip
    click.echo("[info] Skipping PDF retrieval.", err=True)
    return False


def _inline_unpaywall_login() -> None:
    """Interactively collect and persist Unpaywall email (inline §8.6 flow)."""
    import re as _re
    from zotcli.write import credentials as _creds
    from zotcli.config import set_config_value

    click.echo("Unpaywall requires an email address per their fair-use policy.")
    email = click.prompt("Enter your email")

    if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        raise click.ClickException(f"Invalid email address: {email!r}")

    _creds.set("unpaywall", "email", email)
    set_config_value("unpaywall.enabled", "true")
    click.echo(f"Unpaywall configured with email: {email}")
    click.echo("Run `zot add doi <DOI> --with-pdf` to attach an OA PDF.")


def _run_pdf_attachment(
    ctx: click.Context,
    *,
    doi: str | None,
    session,
    parent_key: str | None,
    verbose: bool,
    non_interactive: bool,
    item_url: str | None = None,
) -> None:
    """Run the Zotero-style find-file pipeline and attach the result to *parent_key*.

    Uses :mod:`zotcli.write.find_file` (the 4-resolver pipeline that mirrors
    Zotero's ``getFileResolvers`` + ``downloadFirstAvailableFile``):

      doi  → ``https://doi.org/{doi}`` (page scrape)
      url  → item URL (page scrape)
      oa   → ``POST https://services.zotero.org/oa/search``
      custom → user-defined resolvers (``findPDFs.resolvers`` config)

    On success the PDF is attached as a child of the just-saved item via the
    same connector session (``session.attach_child_pdf``) — no separate
    SQLite write is needed because the parent was created in this session.

    If neither a DOI nor an item URL is available the function returns
    silently (nothing to look up).
    """
    if parent_key is None:
        if verbose:
            click.echo("[pdf] No parent key returned; skipping PDF attach.", err=True)
        return

    if not doi and not item_url:
        if verbose:
            click.echo("[pdf] No DOI or URL; nothing to look up.", err=True)
        return

    from zotcli.write.find_file import find_file

    if verbose:
        click.echo(f"[pdf] find_file: doi={doi!r} url={item_url!r}", err=True)

    result = find_file(
        doi=doi,
        item_url=item_url,
        allow_browser=True,
        allow_headed=not non_interactive,
    )

    if result is None:
        click.echo("No PDF found (tried doi, url, OA, custom resolvers).")
        return

    title_doi = doi or item_url or "fulltext"
    try:
        session.attach_child_pdf(
            parent_key=parent_key,
            pdf_path=result.path,
            source_url=result.source_url,
            title=f"{title_doi} ({result.access_method})"[:200],
        )
        from zotcli.write.pdf import human_size
        size_str = human_size(result.path.stat().st_size)
        click.echo(f"Attached PDF ({size_str}) via {result.access_method}.")
    finally:
        try:
            result.path.unlink()
        except OSError:
            pass


# ---------------------------------------------------------------------------
# M6: zot add login
# ---------------------------------------------------------------------------

@add.command("login")
@click.option("--service", "-s",
              type=click.Choice(["unpaywall", "ieee", "sciencedirect"]),
              default=None,
              help="Service to authenticate with.")
@click.option("--reset", is_flag=True, default=False,
              help="Clear stored credentials/cookies for the service.")
@click.option("--install-browser", "install_browser_flag", is_flag=True, default=False,
              help="Install Chromium via `playwright install chromium`.")
@click.pass_context
def add_login(ctx: click.Context, service: str | None, reset: bool, install_browser_flag: bool) -> None:
    """Manage authentication for PDF retrieval services.

    Use --service to set up access for Unpaywall (email registration),
    IEEE Xplore (institutional SSO), or ScienceDirect (Elsevier SSO).

    Examples:

    \b
        zot add login --service unpaywall         # save Unpaywall email
        zot add login --service ieee              # open browser for IEEE SSO
        zot add login --service sciencedirect     # open browser for SD SSO
        zot add login --service ieee --reset      # clear IEEE cookies
        zot add login --install-browser           # install Chromium
    """
    import re as _re
    from zotcli.write import credentials as _creds
    from zotcli.config import set_config_value

    # --install-browser: runs regardless of --service
    if install_browser_flag:
        from zotcli.write.browser import install_browser, is_browser_extra_installed
        if not is_browser_extra_installed():
            raise click.ClickException(
                'The playwright package is not installed. '
                'Install it first: pip install "zotcli[browser]"'
            )
        try:
            install_browser()
            click.echo("Chromium installed successfully.")
        except RuntimeError as exc:
            raise click.ClickException(str(exc)) from exc
        return

    if service is None:
        # Print current status for all services
        from zotcli.paths import cookies_root
        creds = _creds.load()
        services_data = creds.get("services", {})

        click.echo("Authentication status:")
        # Unpaywall
        up = services_data.get("unpaywall", {})
        up_email = up.get("email", "")
        click.echo(f"  unpaywall     : {'configured (email: ' + up_email + ')' if up_email else 'not configured'}")
        # IEEE
        ieee_data = services_data.get("ieee", {})
        ieee_ts = ieee_data.get("logged_in_at", "")
        ieee_cookies = _publisher_cookies_exist("ieee")
        click.echo(f"  ieee          : {'logged in at ' + ieee_ts if ieee_ts else ('cookies present' if ieee_cookies else 'not logged in')}")
        # ScienceDirect
        sd_data = services_data.get("sciencedirect", {})
        sd_ts = sd_data.get("logged_in_at", "")
        sd_cookies = _publisher_cookies_exist("sciencedirect")
        click.echo(f"  sciencedirect : {'logged in at ' + sd_ts if sd_ts else ('cookies present' if sd_cookies else 'not logged in')}")
        click.echo("\nUse `zot add login --service <name>` to configure a service.")
        return

    # --reset: clear stored credentials/cookies
    if reset:
        if service == "unpaywall":
            _creds.clear("unpaywall")
            set_config_value("unpaywall.enabled", "false")
            click.echo(f"Cleared Unpaywall credentials.")
        else:
            from zotcli.paths import cookies_root
            import shutil
            profile_dir = cookies_root() / service
            if profile_dir.exists():
                shutil.rmtree(profile_dir)
                click.echo(f"Cleared {service} browser profile ({profile_dir}).")
            else:
                click.echo(f"No browser profile found for {service}.")
            _creds.clear(service)
        return

    # --- Service-specific login ---
    if service == "unpaywall":
        click.echo("Unpaywall requires an email address per their fair-use policy.")
        email = click.prompt("Enter your email")
        if not _re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise click.ClickException(f"Invalid email address: {email!r}")
        _creds.set("unpaywall", "email", email)
        set_config_value("unpaywall.enabled", "true")
        click.echo(f"Unpaywall configured. Email: {email}")
        click.echo("Unpaywall is now enabled. Use --with-pdf on `zot add doi` to fetch OA PDFs.")

    elif service in ("ieee", "sciencedirect"):
        from zotcli.write.browser import BrowserSession, is_browser_extra_installed
        if not is_browser_extra_installed():
            raise click.ClickException(
                f"Browser support is required for {service} login. "
                'Install it with: pip install "zotcli[browser]"'
            )
        try:
            bs = BrowserSession(service)
            result = bs.login()
            logged_in_at = result.get("logged_in_at", "")
            _creds.set(service, "logged_in_at", logged_in_at)
            click.echo(
                f"Logged in to {service} successfully. "
                f"Cookies saved to {bs.profile_dir}."
            )
        except Exception as exc:
            raise click.ClickException(
                f"Login to {service} failed: {exc}"
            ) from exc

    else:
        raise click.ClickException(f"Unknown service: {service!r}")


def require_write_enabled(ctx: click.Context) -> None:
    """Raise ClickException if write is not enabled by any gate.

    Gates checked (in priority order):
    1. --allow-write flag in ctx.obj
    2. ZOTCLI_ALLOW_WRITE env var (truthy: 1, true, yes)
    3. write.enabled = true in config

    This helper is called by all write commands; not used by `status`.
    """
    from zotcli.config import get_write_enabled

    obj = ctx.obj
    if getattr(obj, "allow_write", False):
        return
    if os.environ.get("ZOTCLI_ALLOW_WRITE", "0") not in ("0", "", "false", "False"):
        return
    if get_write_enabled():
        return

    raise click.ClickException(
        "Write capability is disabled. Enable it with:\n"
        "  zot config set write.enabled true\n"
        "or pass --allow-write on each command, "
        "or set the ZOTCLI_ALLOW_WRITE=1 environment variable."
    )


def _resolve_connector_url(ctx: click.Context) -> str:
    """Return the effective connector URL from CLI flag, env, or config."""
    from zotcli.config import get_connector_url

    obj = ctx.obj
    # CLI flag takes precedence
    url = getattr(obj, "connector_url", None)
    if url:
        return url
    # Env var
    env_url = os.environ.get("ZOTCLI_CONNECTOR_URL")
    if env_url:
        return env_url
    # Config
    return get_connector_url()
