"""Unit tests for zotcli.write.oa_search."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest


def _fake_response(payload):
    """Build a context manager that mimics urllib's response object."""
    class _Resp:
        def __init__(self, data):
            self._data = data
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return self._data

    return _Resp(json.dumps(payload).encode())


def test_search_oa_empty_doi_returns_empty_without_network():
    from zotcli.write.oa_search import search_oa
    with patch("urllib.request.urlopen") as m:
        assert search_oa("") == []
        assert search_oa("   ") == []
        m.assert_not_called()


def test_search_oa_parses_url_and_page_url_and_version():
    from zotcli.write.oa_search import search_oa
    payload = [
        {"url": "https://x/y.pdf", "pageURL": "https://doi.org/z", "version": "publishedVersion"},
        {"pageURL": "https://other/page", "version": "submittedVersion"},
    ]
    with patch("urllib.request.urlopen", return_value=_fake_response(payload)):
        results = search_oa("10.1234/abc")
    assert len(results) == 2
    assert results[0].url == "https://x/y.pdf"
    assert results[0].page_url == "https://doi.org/z"
    assert results[0].version == "publishedVersion"
    assert results[1].url is None
    assert results[1].page_url == "https://other/page"


def test_search_oa_swallows_network_errors():
    import urllib.error
    from zotcli.write.oa_search import search_oa
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("boom")):
        assert search_oa("10.1234/x") == []


def test_search_oa_swallows_invalid_json():
    from zotcli.write.oa_search import search_oa

    class _BadResp:
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False
        def read(self):
            return b"not-json"

    with patch("urllib.request.urlopen", return_value=_BadResp()):
        assert search_oa("10.1234/x") == []


def test_search_oa_handles_non_list_response():
    from zotcli.write.oa_search import search_oa
    with patch("urllib.request.urlopen", return_value=_fake_response({"error": "x"})):
        assert search_oa("10.1234/x") == []
