"""PubMed resolver — PMID → CSL-JSON.

GET https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi
    ?db=pubmed&id={pmid}&rettype=abstract&retmode=xml

Parses the XML response using stdlib xml.etree.ElementTree.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET

logger = logging.getLogger(__name__)

_EFETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"


def resolve(pmid: str) -> dict:
    """Fetch metadata for *pmid* from NCBI eUtils and return a CSL-JSON dict.

    Parameters
    ----------
    pmid:
        A normalised PMID string (digits only).

    Returns
    -------
    dict
        A CSL-JSON record with ``type: "journal-article"``.

    Raises
    ------
    IdentifierNotFound
        If the PMID is not found.
    RuntimeError
        On HTTP or parse errors.
    """
    from pyzot.write.resolvers._http import require_httpx

    httpx = require_httpx()
    params = {
        "db": "pubmed",
        "id": pmid,
        "rettype": "abstract",
        "retmode": "xml",
    }
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.get(_EFETCH_URL, params=params, follow_redirects=True)
    except Exception as exc:
        raise RuntimeError(f"Failed to reach PubMed for PMID '{pmid}': {exc}") from exc

    if resp.status_code != 200:
        raise RuntimeError(
            f"PubMed eUtils returned HTTP {resp.status_code} for PMID '{pmid}': {resp.text[:200]}"
        )

    return _parse_pubmed_xml(resp.text, pmid)


def _text(el: ET.Element | None) -> str:
    """Return stripped text content of an element, or empty string."""
    if el is None:
        return ""
    return (el.text or "").strip()


def _parse_pubmed_xml(xml_text: str, pmid: str) -> dict:
    """Parse PubMed efetch XML and return a CSL-JSON dict."""
    from pyzot.write.resolvers import IdentifierNotFound

    root = ET.fromstring(xml_text)

    article_el = root.find(".//PubmedArticle")
    if article_el is None:
        raise IdentifierNotFound("pmid", pmid, "No PubmedArticle element in response")

    medline = article_el.find("MedlineCitation")
    if medline is None:
        raise IdentifierNotFound("pmid", pmid, "No MedlineCitation element")

    article = medline.find("Article")
    if article is None:
        raise IdentifierNotFound("pmid", pmid, "No Article element")

    # --- Title ---
    title_el = article.find("ArticleTitle")
    title = _text(title_el)

    # --- Authors ---
    creators: list[dict] = []
    author_list = article.find("AuthorList")
    if author_list is not None:
        for author in author_list.findall("Author"):
            last = _text(author.find("LastName"))
            fore = _text(author.find("ForeName"))
            collective = _text(author.find("CollectiveName"))
            if collective:
                creators.append({"literal": collective, "creatorType": "author"})
            elif last:
                creators.append({
                    "given": fore,
                    "family": last,
                })

    # --- Date ---
    pub_date_el = article.find("Journal/JournalIssue/PubDate")
    date_parts_list: list[list[int]] = []
    date_str = ""
    if pub_date_el is not None:
        year_str = _text(pub_date_el.find("Year"))
        month_str = _text(pub_date_el.find("Month"))
        day_str = _text(pub_date_el.find("Day"))
        # MedlineDate fallback (e.g. "2021 Jan-Feb")
        medline_date = _text(pub_date_el.find("MedlineDate"))
        if year_str:
            parts = [int(year_str)]
            if month_str:
                try:
                    import calendar
                    month_names = {m.lower(): i for i, m in enumerate(calendar.month_abbr) if m}
                    month_num = month_names.get(month_str.lower()[:3])
                    if month_num is None:
                        month_num = int(month_str)
                    parts.append(month_num)
                except (ValueError, AttributeError):
                    pass
                if day_str:
                    try:
                        parts.append(int(day_str))
                    except ValueError:
                        pass
            date_parts_list = [parts]
            date_str = year_str
        elif medline_date:
            year_match = __import__("re").search(r"\b(\d{4})\b", medline_date)
            if year_match:
                date_parts_list = [[int(year_match.group(1))]]
                date_str = year_match.group(1)

    # --- Journal ---
    journal_el = article.find("Journal")
    journal_title = ""
    journal_abbrev = ""
    volume = ""
    issue = ""
    issn = ""
    if journal_el is not None:
        journal_title = _text(journal_el.find("Title"))
        journal_abbrev = _text(journal_el.find("ISOAbbreviation"))
        journal_issue = journal_el.find("JournalIssue")
        if journal_issue is not None:
            volume = _text(journal_issue.find("Volume"))
            issue = _text(journal_issue.find("Issue"))
        issn_el = journal_el.find("ISSN")
        if issn_el is not None:
            issn = _text(issn_el)

    # --- Pages ---
    pagination = article.find("Pagination/MedlinePgn")
    pages = _text(pagination)

    # --- Abstract ---
    abstract_parts: list[str] = []
    abstract_el = article.find("Abstract")
    if abstract_el is not None:
        for ab_text in abstract_el.findall("AbstractText"):
            label = ab_text.get("Label", "")
            text = _text(ab_text)
            if text:
                abstract_parts.append(f"{label}: {text}" if label else text)
    abstract = "\n".join(abstract_parts)

    # --- DOI ---
    doi = ""
    article_ids = article_el.find("PubmedData/ArticleIdList")
    if article_ids is not None:
        for aid in article_ids.findall("ArticleId"):
            if aid.get("IdType") == "doi":
                doi = _text(aid)
                break

    # Also check ELocationID
    if not doi:
        for loc in article.findall("ELocationID"):
            if loc.get("EIdType") == "doi":
                doi = _text(loc)
                break

    # --- Language ---
    lang_el = article.find("Language")
    language = _text(lang_el)

    # Build CSL-JSON
    csl: dict = {
        "type": "journal-article",
        "title": title,
        "author": creators,
        "abstract": abstract,
        "language": language,
    }
    if date_parts_list:
        csl["issued"] = {"date-parts": date_parts_list}
    elif date_str:
        csl["issued"] = {"literal": date_str}
    if journal_title:
        csl["container-title"] = journal_title
    if journal_abbrev:
        csl["container-title-short"] = journal_abbrev
    if volume:
        csl["volume"] = volume
    if issue:
        csl["issue"] = issue
    if pages:
        csl["page"] = pages
    if issn:
        csl["ISSN"] = issn
    if doi:
        csl["DOI"] = doi

    return csl
