"""Resolver dispatcher for pyzot write pipeline.

Usage:
    from pyzot.write.resolvers import resolve
    csl = resolve("doi", "10.1038/example")

Each resolver returns a CSL-JSON-shaped dict.
Raises IdentifierNotFound if the identifier cannot be resolved.
"""

from __future__ import annotations


class IdentifierNotFound(LookupError):
    """Raised when an identifier cannot be found in the upstream registry."""

    def __init__(self, kind: str, identifier: str, detail: str = "") -> None:
        self.kind = kind
        self.identifier = identifier
        self.detail = detail
        msg = f"Identifier not found: {kind}:{identifier}"
        if detail:
            msg = f"{msg} — {detail}"
        super().__init__(msg)


_RESOLVER_MAP: dict[str, str] = {
    "doi": "pyzot.write.resolvers.crossref",
    "arxiv": "pyzot.write.resolvers.arxiv",
    "pmid": "pyzot.write.resolvers.pubmed",
    "isbn": "pyzot.write.resolvers.openlibrary",
}


def resolve(kind: str, identifier: str) -> dict:
    """Resolve an identifier to a CSL-JSON dict.

    Parameters
    ----------
    kind:
        One of "doi", "arxiv", "pmid", "isbn".
    identifier:
        The normalised identifier string.

    Returns
    -------
    dict
        A CSL-JSON record.

    Raises
    ------
    IdentifierNotFound
        If the identifier cannot be found.
    ValueError
        If *kind* is not supported.
    """
    module_path = _RESOLVER_MAP.get(kind)
    if module_path is None:
        raise ValueError(
            f"No resolver for identifier kind '{kind}'. Supported: {', '.join(_RESOLVER_MAP)}"
        )
    import importlib

    module = importlib.import_module(module_path)
    return module.resolve(identifier)
