"""CLI group: zot add — add items to your Zotero library.

M1 implemented `zot add status`.
M5 adds: `zot add "<anything>"` (auto-detect), `zot add batch <file>`.

Architecture (M5 auto-detect):
    The ``add`` group is a custom subclass of ``click.Group`` with
    ``invoke_without_command=True``.  When ``parse_args`` sees a token that
    does not match any registered subcommand name it stores it as a bare
    positional and sets ``_bare_input``.  The group callback is invoked with
    that token; it calls ``_dispatch(ctx, token, ...)`` which runs
    ``detect_kind(token)`` and forwards to the appropriate ``_run_*`` helper.

    The non-redundant subcommands are retained for status, batch mode, and
    advanced citation input.
"""

from __future__ import annotations

import os
import sys

import click

from . import citation, files, pipeline, url
from .context import require_write_enabled, resolve_connector_url
from .options import _apply_common_options

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

    @click.command("_dispatch", hidden=True, short_help="Auto-detect and add by identifier.")
    @click.argument("input_value", metavar="INPUT")
    @click.option("--collection", "-c", default=None, metavar="NAME")
    @click.option("--tag", "-t", multiple=True, metavar="TEXT")
    @click.option("--dry-run", is_flag=True, default=False)
    @click.option(
        "--on-duplicate",
        type=click.Choice(["report", "skip", "force-add"]),
        default="report",
        show_default=True,
    )
    @click.option("-v", "--verbose", is_flag=True, default=False)
    @click.option("--non-interactive", "non_interactive", is_flag=True, default=False)
    @click.option("--wait-recognize", "wait_recognize", type=int, default=30, show_default=True)
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
        wait_recognize: int,
    ) -> None:
        """Auto-detect input type and dispatch to the right add handler."""
        from pyzot.logging_setup import configure_logging

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
            wait_recognize=wait_recognize,
        )

    return _dispatch_cmd


# Singleton dispatch command — created once
_DISPATCH_CMD = _make_dispatch_command()

_LEGACY_ADD_COMMANDS = {
    "doi": "`zot add doi <DOI>` has been removed; use `zot add <DOI>`.",
    "arxiv": "`zot add arxiv <ID>` has been removed; use `zot add <ID>`.",
    "pmid": "`zot add pmid <PMID>` has been removed; use `zot add <PMID>`.",
    "isbn": "`zot add isbn <ISBN>` has been removed; use `zot add <ISBN>`.",
    "url": "`zot add url <URL>` has been removed; use `zot add <URL>`.",
    "file": "`zot add file <PATH>` has been removed; use `zot add <PATH>`.",
    "import": "`zot add import <PATH>` has been removed; use `zot add <PATH>`.",
}


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
            if args and args[0] in _LEGACY_ADD_COMMANDS:
                raise click.UsageError(_LEGACY_ADD_COMMANDS[args[0]], ctx=ctx) from None
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
        zot add batch papers.txt                    # batch mode

    Use `zot add batch` for scripted multi-item imports.
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
    wait_recognize: int = 30,
) -> None:
    """Detect the kind of *input_value* and dispatch to the appropriate handler.

    Routing table:
        "doi"       → _run_add_pipeline(kind="doi")
        "arxiv"     → _run_add_pipeline(kind="arxiv")
        "pmid"      → _run_add_pipeline(kind="pmid")
        "isbn"      → _run_add_pipeline(kind="isbn")
        "url"       → _run_url (which itself sub-routes by URL pattern)
        "citation"  → _run_cite_pipeline
        "filepath"  → _run_file if PDF/EPUB, else _run_import
        "unknown"   → ClickException with clear message
    """
    from pyzot.write.identifiers import detect_kind

    kind = detect_kind(input_value)

    if verbose:
        click.echo(f"Detected kind: {kind!r} for input: {input_value[:80]!r}", err=True)

    if kind in {"doi", "arxiv", "pmid", "isbn"}:
        pipeline._run_add_pipeline(
            ctx,
            kind,
            input_value,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
    elif kind == "url":
        url._run_url(
            ctx,
            input_value,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
            non_interactive=non_interactive,
        )
    elif kind == "citation":
        citation._run_cite_pipeline(
            ctx,
            input_value,
            threshold=50,
            gap=1.4,
            non_interactive=non_interactive,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            on_duplicate=on_duplicate,
            verbose=verbose,
        )
    elif kind == "filepath":
        files._run_filepath(
            ctx,
            input_value,
            collection=collection,
            tag=tag,
            dry_run=dry_run,
            wait_recognize=wait_recognize,
            verbose=verbose,
        )
    else:
        raise click.ClickException(
            f"Cannot determine input type for: {input_value!r}\n"
            "Supported kinds: DOI (10.NNNN/...), arXiv ID (YYMM.NNNNN), "
            "PMID (numeric), ISBN, URL (https://...), "
            "citation string (free text with spaces), "
            "local file path (/path/to/file.pdf).\n"
            "Use `zot add batch` for multi-item imports."
        )


# ---------------------------------------------------------------------------
# Retained add subcommands
# ---------------------------------------------------------------------------


@add.command("status")
@click.pass_context
def add_status(ctx: click.Context):
    """Check whether Zotero is running and report the current target.

    Prints reachability, selected collection, connector URL, and a hint
    about enabling write capability if not already enabled.
    """
    from pyzot.config import get_write_enabled
    from pyzot.write.preflight import check_zotero_running

    # Resolve connector URL from: CLI flag > config > default
    connector_url = resolve_connector_url(ctx)

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
    allow_write_env = os.environ.get("PYZOT_ALLOW_WRITE", "0") not in ("0", "", "false", "False")

    if write_ok or allow_write_flag or allow_write_env:
        click.echo("Write enabled : yes")
    else:
        click.echo("Write enabled : no")
        click.echo(
            "Hint: run `zot config set write.enabled true` to enable write capability, "
            "or pass --allow-write per command."
        )


@add.command("cite")
@click.argument("citation_text", required=False, default=None)
@click.option("--file", "-f", "refs_file", type=click.Path(exists=True), default=None)
@click.option("--threshold", type=int, default=50, show_default=True)
@click.option("--gap", type=float, default=1.4, show_default=True)
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
) -> None:
    """Add one or more items from free-text citation strings."""
    require_write_enabled(ctx)

    lines: list[str] = []
    if refs_file:
        with open(refs_file, encoding="utf-8") as fh:
            lines = [
                line.strip() for line in fh if line.strip() and not line.strip().startswith("#")
            ]
    elif citation_text:
        lines = [citation_text.strip()]
    else:
        raise click.UsageError(
            "Provide a CITATION_TEXT argument or --file with a file of citations."
        )

    any_failed = False
    for line in lines:
        try:
            citation._run_cite_pipeline(
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
            )
        except click.ClickException as exc:
            if len(lines) == 1:
                raise
            click.echo(f"Could not resolve: {line[:80]!r} — {exc.format_message()}", err=True)
            any_failed = True

    if any_failed:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# M5: zot add batch <path>
# ---------------------------------------------------------------------------


@add.command("batch")
@click.argument("path", metavar="FILE")
@click.option(
    "--collection", "-c", default=None, metavar="NAME", help="Collection name applied to all items."
)
@click.option(
    "--tag", "-t", multiple=True, metavar="TEXT", help="Tag to apply to all items (repeatable)."
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Resolve and print what would be submitted without making connector calls.",
)
@click.option(
    "--on-duplicate",
    type=click.Choice(["report", "skip", "force-add"]),
    default="report",
    show_default=True,
    help="Behaviour when a duplicate is found.",
)
@click.option(
    "-v", "--verbose", is_flag=True, default=False, help="Print verbose HTTP request/response info."
)
@click.option(
    "--non-interactive",
    "non_interactive",
    is_flag=True,
    default=False,
    help="Never prompt; fail/skip ambiguous citations.",
)
@click.option(
    "--jobs",
    "jobs",
    type=int,
    default=1,
    show_default=True,
    help="(Stub — reserved for parallel resolver lookups in v0.3.0; currently no-op.)",
)
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
    from pyzot.logging_setup import configure_logging

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

    from pyzot.write.identifiers import detect_kind

    for inp in inputs:
        kind = detect_kind(inp)
        try:
            _dispatch(
                ctx,
                inp,
                collection=collection,
                tag=tag,
                dry_run=dry_run,
                on_duplicate=on_duplicate,
                verbose=verbose,
                non_interactive=non_interactive,
            )
            results.append({"input": inp, "kind": kind, "status": "ok", "message": ""})
        except (click.ClickException, SystemExit, Exception) as exc:
            msg = getattr(exc, "format_message", None)
            msg = msg() if callable(msg) else str(exc)
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
        from rich.console import Console
        from rich.table import Table

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
            click.echo(
                f"[{mark}] {r['kind']}: {r['input'][:60]}"
                + (f" — {r['message'][:50]}" if r["message"] else "")
            )

    n_ok = sum(1 for r in results if r["status"] == "ok")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = 0  # currently no "skip" status (duplicates are counted as ok)
    click.echo(f"{n_ok} added, {n_skip} skipped, {n_fail} failed.")
