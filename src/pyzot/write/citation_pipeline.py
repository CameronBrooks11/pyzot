"""Citation-string resolver pipeline.

resolve_citation(text, threshold, gap, interactive, console) → CSL-JSON | None

Pipeline:
1. Normalise whitespace + smart quotes.
2. crossref.bibliographic_search(text, rows=5).
3. If top hit has score >= threshold AND score / next_score >= gap
   (treat missing next as auto-accept), accept it → return crossref.resolve(doi).
4. Else if interactive: render a rich.table of top-5 candidates and prompt
   the user to pick one (1-N) or 'n' for none. On pick → crossref.resolve(doi).
   On 'n' or non-interactive ambiguous → fall through to OpenAlex.
5. openalex.search(text) → if a hit has a DOI, accept top result.
6. semantic_scholar.search(text) → same logic.
7. If still nothing → return None.

Returns a CSL-JSON dict (from crossref.resolve) when successful, else None.
"""

from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Text normalisation
# ---------------------------------------------------------------------------

def _normalise(text: str) -> str:
    """Normalise whitespace and smart quotes in a citation string."""
    # Collapse internal whitespace runs to single space
    text = re.sub(r"[ \t]+", " ", text)
    # Replace newlines/tabs with space
    text = re.sub(r"[\r\n]+", " ", text)
    # Unify smart/curly quotes to straight
    text = text.replace("‘", "'").replace("’", "'")
    text = text.replace("“", '"').replace("”", '"')
    return text.strip()


# ---------------------------------------------------------------------------
# Interactive disambiguation table
# ---------------------------------------------------------------------------

def _render_candidates(hits: list[dict], console=None) -> None:
    """Render a rich.table of candidate hits for interactive selection."""
    try:
        from rich.console import Console
        from rich.table import Table
    except ImportError:
        # Fallback: plain text
        _con = console
        for i, h in enumerate(hits, 1):
            authors = ", ".join(h.get("authors", [])[:3])
            year = h.get("year", "")
            title = (h.get("title") or "")[:80]
            score = h.get("score", "?")
            doi = h.get("doi", "")
            line = f"  [{i}] score={score} | {year} | {title} | {authors} | {doi}"
            if _con:
                _con.print(line)
            else:
                print(line)
        return

    c = console
    if c is None:
        c = Console(stderr=True)

    table = Table(title="Crossref candidates — pick a number or 'n' to skip")
    table.add_column("#", style="bold", width=3)
    table.add_column("Score", width=7)
    table.add_column("Year", width=6)
    table.add_column("Title", max_width=50)
    table.add_column("Authors", max_width=30)
    table.add_column("DOI", max_width=40)

    for i, h in enumerate(hits, 1):
        authors = "; ".join(h.get("authors", [])[:3])
        title = (h.get("title") or "")[:80]
        score_str = f"{h.get('score', '?'):.1f}" if isinstance(h.get("score"), float) else str(h.get("score", "?"))
        year = str(h.get("year", ""))
        doi = h.get("doi", "")
        table.add_row(str(i), score_str, year, title, authors, doi)

    c.print(table)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def resolve_citation(
    text: str,
    *,
    threshold: int = 50,
    gap: float = 1.4,
    interactive: bool = True,
    console=None,
) -> dict | None:
    """Resolve a free-text citation string to CSL-JSON.

    Parameters
    ----------
    text:
        Free-text citation string (author-year format, etc.).
    threshold:
        Minimum Crossref relevance score to auto-accept the top result.
    gap:
        Minimum ratio of top score to second score to auto-accept without
        interactive disambiguation. If only one result, auto-accept if
        score >= threshold.
    interactive:
        If ``True``, present a rich table for user selection when ambiguous.
        If ``False``, treat ambiguous results as failures and fall through.
    console:
        Optional ``rich.Console`` instance for output. If None, a default
        stderr console is used.

    Returns
    -------
    dict or None
        A CSL-JSON record on success, or ``None`` if the citation could not
        be resolved through any strategy.
    """
    from pyzot.write.resolvers import crossref, openalex, semantic_scholar

    # ------------------------------------------------------------------
    # Step 1: Normalise
    # ------------------------------------------------------------------
    text = _normalise(text)
    if not text:
        return None

    # ------------------------------------------------------------------
    # Step 2: Crossref bibliographic search
    # ------------------------------------------------------------------
    hits = crossref.bibliographic_search(text, rows=5)

    # ------------------------------------------------------------------
    # Step 3: Auto-accept top Crossref hit
    # ------------------------------------------------------------------
    accepted_doi: str | None = None

    if hits:
        top = hits[0]
        top_score = top.get("score") or 0
        top_doi = top.get("doi", "")

        if top_doi and top_score >= threshold:
            # Check gap condition
            if len(hits) == 1:
                # Only one result — auto-accept
                accepted_doi = top_doi
                logger.debug("Citation pipeline: auto-accepting sole Crossref hit (score=%.1f)", top_score)
            else:
                second_score = hits[1].get("score") or 0
                if second_score == 0 or (top_score / second_score) >= gap:
                    accepted_doi = top_doi
                    logger.debug(
                        "Citation pipeline: auto-accepting top Crossref hit "
                        "(score=%.1f, gap=%.2f)", top_score,
                        top_score / second_score if second_score else float("inf")
                    )

    # ------------------------------------------------------------------
    # Step 4: Interactive disambiguation
    # ------------------------------------------------------------------
    if accepted_doi is None and hits and interactive:
        _render_candidates(hits[:5], console=console)

        try:
            raw = input(f"Pick a candidate (1-{min(len(hits), 5)}) or 'n' to skip: ").strip()
        except (EOFError, KeyboardInterrupt):
            raw = "n"

        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(hits):
                chosen = hits[idx]
                chosen_doi = chosen.get("doi", "")
                if chosen_doi:
                    accepted_doi = chosen_doi
                    logger.debug("Citation pipeline: user picked candidate %d (DOI=%s)", idx + 1, accepted_doi)

    if accepted_doi:
        try:
            csl = crossref.resolve(accepted_doi)
            return csl
        except Exception as exc:
            logger.warning("Citation pipeline: crossref.resolve(%s) failed: %s", accepted_doi, exc)

    # ------------------------------------------------------------------
    # Step 5: OpenAlex fallback
    # ------------------------------------------------------------------
    oa_hits = openalex.search(text, per_page=5)
    if oa_hits:
        top_doi = oa_hits[0].get("doi", "")
        if top_doi:
            logger.debug("Citation pipeline: using OpenAlex top hit DOI=%s", top_doi)
            try:
                csl = crossref.resolve(top_doi)
                return csl
            except Exception as exc:
                logger.warning("Citation pipeline: crossref.resolve via OpenAlex (%s) failed: %s", top_doi, exc)

    # ------------------------------------------------------------------
    # Step 6: Semantic Scholar fallback
    # ------------------------------------------------------------------
    ss_hits = semantic_scholar.search(text, limit=5)
    if ss_hits:
        top_doi = ss_hits[0].get("doi", "")
        if top_doi:
            logger.debug("Citation pipeline: using Semantic Scholar top hit DOI=%s", top_doi)
            try:
                csl = crossref.resolve(top_doi)
                return csl
            except Exception as exc:
                logger.warning("Citation pipeline: crossref.resolve via S2 (%s) failed: %s", top_doi, exc)

    # ------------------------------------------------------------------
    # Step 7: Unresolved
    # ------------------------------------------------------------------
    logger.debug("Citation pipeline: could not resolve citation: %s", text[:120])
    return None
