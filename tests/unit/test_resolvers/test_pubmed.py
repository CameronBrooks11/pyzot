"""Tests for PubMed resolver using minimal XML fixtures."""

from __future__ import annotations

import pytest

from pyzot.write.resolvers import IdentifierNotFound

PUBMED_XML = """\
<?xml version="1.0" ?>
<!DOCTYPE PubmedArticleSet PUBLIC "-//NLM//DTD PubMedArticle, 1st January 2025//EN" "">
<PubmedArticleSet>
<PubmedArticle>
  <MedlineCitation Status="MEDLINE" Owner="NLM">
    <PMID Version="1">31452104</PMID>
    <Article PubModel="Print">
      <Journal>
        <ISSN IssnType="Electronic">1940-6029</ISSN>
        <JournalIssue CitedMedium="Internet">
          <Volume>2053</Volume>
          <Issue>1</Issue>
          <PubDate><Year>2019</Year><Month>Jan</Month><Day>15</Day></PubDate>
        </JournalIssue>
        <Title>Methods in molecular biology</Title>
        <ISOAbbreviation>Methods Mol Biol</ISOAbbreviation>
      </Journal>
      <ArticleTitle>Molegro Virtual Docker for Docking</ArticleTitle>
      <Pagination><MedlinePgn>137-159</MedlinePgn></Pagination>
      <Abstract>
        <AbstractText>Molegro Virtual Docker (MVD) is a platform for molecular docking.</AbstractText>
      </Abstract>
      <AuthorList CompleteYN="Y">
        <Author ValidYN="Y">
          <LastName>Thomsen</LastName>
          <ForeName>Rene</ForeName>
        </Author>
        <Author ValidYN="Y">
          <LastName>Christensen</LastName>
          <ForeName>Mikael H</ForeName>
        </Author>
      </AuthorList>
      <Language>eng</Language>
      <ELocationID EIdType="doi" ValidYN="Y">10.1007/978-1-4939-9752-7_9</ELocationID>
    </Article>
  </MedlineCitation>
  <PubmedData>
    <ArticleIdList>
      <ArticleId IdType="pubmed">31452104</ArticleId>
      <ArticleId IdType="doi">10.1007/978-1-4939-9752-7_9</ArticleId>
    </ArticleIdList>
  </PubmedData>
</PubmedArticle>
</PubmedArticleSet>
"""

PUBMED_EMPTY_XML = """\
<?xml version="1.0" ?>
<PubmedArticleSet>
</PubmedArticleSet>
"""


class TestPubmedResolve:
    def test_successful_resolve(self, httpserver, monkeypatch):
        """resolve() returns CSL-JSON for a valid PMID."""
        httpserver.expect_request("/efetch.fcgi").respond_with_data(
            PUBMED_XML, content_type="text/xml"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.pubmed._EFETCH_URL",
            httpserver.url_for("/efetch.fcgi"),
        )

        from pyzot.write.resolvers.pubmed import resolve

        result = resolve("31452104")

        assert result["type"] == "journal-article"
        assert result["title"] == "Molegro Virtual Docker for Docking"
        assert len(result["author"]) == 2
        assert result["author"][0]["family"] == "Thomsen"
        assert result["volume"] == "2053"
        assert result["page"] == "137-159"
        assert result["DOI"] == "10.1007/978-1-4939-9752-7_9"

    def test_no_article_raises_not_found(self, httpserver, monkeypatch):
        """resolve() raises IdentifierNotFound when no PubmedArticle in response."""
        httpserver.expect_request("/efetch.fcgi").respond_with_data(
            PUBMED_EMPTY_XML, content_type="text/xml"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.pubmed._EFETCH_URL",
            httpserver.url_for("/efetch.fcgi"),
        )

        from pyzot.write.resolvers.pubmed import resolve

        with pytest.raises(IdentifierNotFound):
            resolve("99999999")

    def test_http_error_raises_runtime(self, httpserver, monkeypatch):
        """resolve() raises RuntimeError on non-200 HTTP status."""
        httpserver.expect_request("/efetch.fcgi").respond_with_data(
            "Bad Gateway", status=502, content_type="text/plain"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.pubmed._EFETCH_URL",
            httpserver.url_for("/efetch.fcgi"),
        )

        from pyzot.write.resolvers.pubmed import resolve

        with pytest.raises(RuntimeError):
            resolve("31452104")

    def test_parse_pubmed_xml_directly(self):
        """_parse_pubmed_xml() correctly parses the sample XML."""
        from pyzot.write.resolvers.pubmed import _parse_pubmed_xml

        result = _parse_pubmed_xml(PUBMED_XML, "31452104")
        assert result["title"] == "Molegro Virtual Docker for Docking"
        assert result["issued"]["date-parts"][0][0] == 2019
        assert result["issued"]["date-parts"][0][1] == 1
        assert result["issued"]["date-parts"][0][2] == 15
        assert result["container-title"] == "Methods in molecular biology"
        assert result["ISSN"] == "1940-6029"
        assert result["language"] == "eng"
