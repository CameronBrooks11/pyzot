"""Tests for arXiv resolver using a minimal Atom XML fixture."""

from __future__ import annotations

import pytest

from pyzot.write.resolvers import IdentifierNotFound

# Minimal Atom XML response that matches what arXiv returns
ARXIV_ATOM = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom"
      xmlns="http://www.w3.org/2005/Atom">
  <id>http://arxiv.org/api/test</id>
  <title>arXiv Query</title>
  <updated>2024-01-01T00:00:00Z</updated>
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/abs/1706.03762v5</id>
    <title>Attention Is All You Need</title>
    <summary>The dominant sequence transduction models are based on complex recurrent or convolutional neural networks.</summary>
    <published>2017-06-12T17:52:35Z</published>
    <updated>2017-12-05T20:47:50Z</updated>
    <author>
      <name>Ashish Vaswani</name>
    </author>
    <author>
      <name>Noam Shazeer</name>
    </author>
    <arxiv:primary_category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
    <category term="cs.CL" scheme="http://arxiv.org/schemas/atom"/>
  </entry>
</feed>
"""

ARXIV_EMPTY = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>0</opensearch:totalResults>
</feed>
"""

ARXIV_ERROR = """\
<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
      xmlns:opensearch="http://a9.com/-/spec/opensearch/1.1/"
      xmlns:arxiv="http://arxiv.org/schemas/atom">
  <opensearch:totalResults>1</opensearch:totalResults>
  <entry>
    <id>http://arxiv.org/api/errors</id>
    <title>Error</title>
    <summary>There is no paper with id 9999.99999</summary>
  </entry>
</feed>
"""


class TestArxivResolve:
    def test_successful_resolve(self, httpserver, monkeypatch):
        """resolve() returns a CSL-JSON dict for a valid arXiv ID."""
        httpserver.expect_request("/api/query").respond_with_data(
            ARXIV_ATOM, content_type="application/atom+xml"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv._API_URL",
            httpserver.url_for("/api/query"),
        )

        from pyzot.write.resolvers.arxiv import resolve
        result = resolve("1706.03762")

        assert result["type"] == "posted-content"
        assert result["title"] == "Attention Is All You Need"
        assert len(result["author"]) == 2
        assert result["author"][0]["family"] == "Vaswani"
        assert result["issued"]["date-parts"][0][0] == 2017
        assert result["archive"] == "arXiv"
        assert "1706.03762" in result["archive_location"]

    def test_empty_response_raises_not_found(self, httpserver, monkeypatch):
        """resolve() raises IdentifierNotFound when arXiv returns no entries."""
        httpserver.expect_request("/api/query").respond_with_data(
            ARXIV_EMPTY, content_type="application/atom+xml"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv._API_URL",
            httpserver.url_for("/api/query"),
        )

        from pyzot.write.resolvers.arxiv import resolve
        with pytest.raises(IdentifierNotFound):
            resolve("9999.99999")

    def test_error_entry_raises_not_found(self, httpserver, monkeypatch):
        """resolve() raises IdentifierNotFound when arXiv returns an error entry."""
        httpserver.expect_request("/api/query").respond_with_data(
            ARXIV_ERROR, content_type="application/atom+xml"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv._API_URL",
            httpserver.url_for("/api/query"),
        )

        from pyzot.write.resolvers.arxiv import resolve
        with pytest.raises(IdentifierNotFound):
            resolve("9999.99999")

    def test_http_error_raises_runtime(self, httpserver, monkeypatch):
        """resolve() raises RuntimeError on non-200 HTTP status."""
        httpserver.expect_request("/api/query").respond_with_data(
            "Bad Gateway", status=502, content_type="text/plain"
        )

        monkeypatch.setattr(
            "pyzot.write.resolvers.arxiv._API_URL",
            httpserver.url_for("/api/query"),
        )

        from pyzot.write.resolvers.arxiv import resolve
        with pytest.raises(RuntimeError):
            resolve("1706.03762")

    def test_parse_atom_directly(self):
        """_parse_atom() correctly parses the sample Atom XML."""
        from pyzot.write.resolvers.arxiv import _parse_atom
        result = _parse_atom(ARXIV_ATOM, "1706.03762")
        assert result["title"] == "Attention Is All You Need"
        assert result["author"][0]["given"] == "Ashish"
        assert result["author"][0]["family"] == "Vaswani"
        assert result["issued"]["date-parts"][0] == [2017, 6, 12]
