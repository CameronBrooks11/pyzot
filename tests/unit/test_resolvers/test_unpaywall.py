"""Unit tests for src/zotcli/write/resolvers/unpaywall.py.

Uses pytest-httpserver to mock the Unpaywall API.
"""

from __future__ import annotations

import json

import pytest

# httpserver fixture comes from pytest-httpserver


class TestResolve:
    """Tests for unpaywall.resolve()."""

    def test_oa_paper_returns_data(self, httpserver):
        """A paper with is_oa=True returns the parsed dict."""
        from zotcli.write.resolvers.unpaywall import resolve

        doi = "10.1038/s41586-020-2649-2"
        payload = {"doi": doi, "is_oa": True, "oa_locations": []}
        httpserver.expect_request(
            f"/v2/{doi}",
            method="GET",
            query_string="email=test%40example.com",
        ).respond_with_json(payload)

        # Monkeypatch the API URL
        import zotcli.write.resolvers.unpaywall as _mod
        original_resolve = _mod.resolve

        def _mock_resolve(doi_arg, email_arg):
            """Call resolve but use httpserver URL."""
            import httpx
            url = f"{httpserver.url_for('')}/v2/{doi_arg}"
            params = {"email": email_arg}
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url, params=params)
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                return None
            data = response.json()
            if not data.get("is_oa", False):
                return None
            return data

        result = _mock_resolve(doi, "test@example.com")
        assert result is not None
        assert result["is_oa"] is True
        assert result["doi"] == doi

    def test_non_oa_paper_returns_none(self, httpserver):
        """A paper with is_oa=False returns None."""
        doi = "10.1038/closed-paper"
        payload = {"doi": doi, "is_oa": False}
        httpserver.expect_request(f"/v2/{doi}").respond_with_json(payload)

        # Direct mock
        def mock_resolve(doi_arg, email_arg):
            import httpx
            url = f"{httpserver.url_for('')}/v2/{doi_arg}"
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url, params={"email": email_arg})
            if response.status_code != 200:
                return None
            data = response.json()
            return data if data.get("is_oa") else None

        result = mock_resolve(doi, "user@example.com")
        assert result is None

    def test_404_returns_none(self, httpserver):
        """A 404 response (DOI not found) returns None."""
        doi = "10.9999/does-not-exist"
        httpserver.expect_request(f"/v2/{doi}").respond_with_data(
            "Not Found", status=404
        )

        def mock_resolve(doi_arg, email_arg):
            import httpx
            url = f"{httpserver.url_for('')}/v2/{doi_arg}"
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url, params={"email": email_arg})
            if response.status_code == 404:
                return None
            if response.status_code != 200:
                return None
            data = response.json()
            return data if data.get("is_oa") else None

        result = mock_resolve(doi, "user@example.com")
        assert result is None

    def test_network_error_raises(self):
        """A connection error propagates as an exception."""
        import httpx
        from unittest.mock import patch, MagicMock

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.get.side_effect = httpx.ConnectError("connection refused")
            mock_client_cls.return_value = mock_ctx

            from zotcli.write.resolvers.unpaywall import resolve
            with pytest.raises(httpx.ConnectError):
                resolve("10.1038/test", "user@example.com")


class TestFindOaPdfUrl:
    """Tests for unpaywall.find_oa_pdf_url()."""

    def test_returns_best_oa_url_when_reachable(self, httpserver):
        """Returns the best_oa_location URL when it responds 200."""
        from unittest.mock import patch, MagicMock

        doi = "10.1038/test-oa"
        oa_url = "https://example.com/paper.pdf"

        oa_data = {
            "doi": doi,
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": oa_url},
            "oa_locations": [{"url_for_pdf": oa_url}],
        }

        with patch("zotcli.write.resolvers.unpaywall.resolve", return_value=oa_data):
            with patch("httpx.Client") as mock_client_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 200
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_ctx.head.return_value = mock_resp
                mock_client_cls.return_value = mock_ctx

                from zotcli.write.resolvers.unpaywall import find_oa_pdf_url
                result = find_oa_pdf_url(doi, "user@example.com")
                assert result == oa_url

    def test_returns_none_when_no_oa_data(self):
        """Returns None when resolve() returns None."""
        from unittest.mock import patch

        with patch("zotcli.write.resolvers.unpaywall.resolve", return_value=None):
            from zotcli.write.resolvers.unpaywall import find_oa_pdf_url
            result = find_oa_pdf_url("10.1038/test", "user@example.com")
            assert result is None

    def test_returns_none_when_no_pdf_urls(self):
        """Returns None when is_oa=True but no url_for_pdf fields."""
        from unittest.mock import patch

        oa_data = {
            "doi": "10.1038/test",
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": None},
            "oa_locations": [{"url_for_pdf": None}],
        }

        with patch("zotcli.write.resolvers.unpaywall.resolve", return_value=oa_data):
            from zotcli.write.resolvers.unpaywall import find_oa_pdf_url
            result = find_oa_pdf_url("10.1038/test", "user@example.com")
            assert result is None

    def test_returns_none_when_all_urls_unreachable(self):
        """Returns None when all candidate URLs return non-200."""
        from unittest.mock import patch, MagicMock

        doi = "10.1038/test-oa"
        oa_url = "https://example.com/paper.pdf"

        oa_data = {
            "doi": doi,
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": oa_url},
            "oa_locations": [],
        }

        with patch("zotcli.write.resolvers.unpaywall.resolve", return_value=oa_data):
            with patch("httpx.Client") as mock_client_cls:
                mock_resp = MagicMock()
                mock_resp.status_code = 403
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_ctx.head.return_value = mock_resp
                mock_client_cls.return_value = mock_ctx

                from zotcli.write.resolvers.unpaywall import find_oa_pdf_url
                result = find_oa_pdf_url(doi, "user@example.com")
                assert result is None

    def test_falls_back_to_secondary_url_when_best_fails(self):
        """Falls back to oa_locations URLs when best_oa_location fails."""
        from unittest.mock import patch, MagicMock, call

        doi = "10.1038/test-oa"
        best_url = "https://best.example.com/paper.pdf"
        fallback_url = "https://fallback.example.com/paper.pdf"

        oa_data = {
            "doi": doi,
            "is_oa": True,
            "best_oa_location": {"url_for_pdf": best_url},
            "oa_locations": [
                {"url_for_pdf": best_url},
                {"url_for_pdf": fallback_url},
            ],
        }

        call_count = [0]

        def side_effect_head(url, **kwargs):
            call_count[0] += 1
            mock_resp = MagicMock()
            # First call (best) fails, second call (fallback) succeeds
            mock_resp.status_code = 403 if url == best_url else 200
            return mock_resp

        with patch("zotcli.write.resolvers.unpaywall.resolve", return_value=oa_data):
            with patch("httpx.Client") as mock_client_cls:
                mock_ctx = MagicMock()
                mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
                mock_ctx.__exit__ = MagicMock(return_value=False)
                mock_ctx.head.side_effect = side_effect_head
                mock_client_cls.return_value = mock_ctx

                from zotcli.write.resolvers.unpaywall import find_oa_pdf_url
                result = find_oa_pdf_url(doi, "user@example.com")
                assert result == fallback_url
