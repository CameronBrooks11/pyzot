"""Click option helpers for `zot add`."""

from __future__ import annotations

import click

_COMMON_ADD_OPTIONS = [
    click.option(
        "--collection",
        "-c",
        default=None,
        metavar="NAME",
        help="Collection name to add the item to.",
    ),
    click.option(
        "--tag",
        "-t",
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
        "-v",
        "--verbose",
        is_flag=True,
        default=False,
        help="Print verbose HTTP request/response info.",
    ),
    click.option(
        "--non-interactive",
        "non_interactive",
        is_flag=True,
        default=False,
        help="Never prompt for citation disambiguation.",
    ),
]


def _apply_common_options(func):
    """Decorator that applies all common add options to a command."""
    for option in reversed(_COMMON_ADD_OPTIONS):
        func = option(func)
    return func
