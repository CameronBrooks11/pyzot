"""Integration tests for ConnectorClient using pytest-httpserver.

Tests:
- Successful GET /connector/ping → dict
- Successful GET /connector/getSelectedCollection → dict
- 500-then-200 retry behaviour (transient 5xx → retry → success)
- Connection refused → ConnectorUnreachable
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_client(base_url: str):
    from pyzot.write.connector_client import ConnectorClient
    # Use max_retries=2 and a short timeout for tests
    return ConnectorClient(base_url=base_url, timeout=5.0, max_retries=2)


# ---------------------------------------------------------------------------
# ping — success
# ---------------------------------------------------------------------------

def test_ping_success(httpserver):
    """ping() returns parsed JSON when /connector/ping responds 200."""
    httpserver.expect_request("/connector/ping").respond_with_json(
        {"version": "7.0.0", "prefs": {}}
    )
    client = make_client(httpserver.url_for("").rstrip("/"))
    result = client.ping()
    assert result["version"] == "7.0.0"


# ---------------------------------------------------------------------------
# getSelectedCollection — success
# ---------------------------------------------------------------------------

def test_get_selected_collection_success(httpserver):
    """get_selected_collection() returns parsed JSON on 200."""
    httpserver.expect_request("/connector/getSelectedCollection").respond_with_json(
        {"id": 42, "name": "Smart Grid", "libraryID": 1}
    )
    client = make_client(httpserver.url_for("").rstrip("/"))
    result = client.get_selected_collection()
    assert result is not None
    assert result["name"] == "Smart Grid"


# ---------------------------------------------------------------------------
# Retry on transient 5xx — success after retry
# ---------------------------------------------------------------------------

def test_ping_retries_on_5xx(httpserver):
    """ping() retries on 500 and succeeds on the subsequent 200."""
    # First request → 500, second → 200
    httpserver.expect_ordered_request("/connector/ping").respond_with_data(
        "Internal Server Error", status=500, content_type="text/plain"
    )
    httpserver.expect_ordered_request("/connector/ping").respond_with_json(
        {"version": "7.0.0"}
    )
    client = make_client(httpserver.url_for("").rstrip("/"))
    result = client.ping()
    assert result["version"] == "7.0.0"


# ---------------------------------------------------------------------------
# Connection refused → ConnectorUnreachable
# ---------------------------------------------------------------------------

def test_ping_connection_refused():
    """ping() raises ConnectorUnreachable when the connector is not running."""
    from pyzot.write.connector_client import ConnectorClient, ConnectorUnreachable
    # Use a port that is almost certainly not listening
    client = ConnectorClient(base_url="http://127.0.0.1:19999", timeout=2.0, max_retries=0)
    with pytest.raises(ConnectorUnreachable) as exc_info:
        client.ping()
    assert "Zotero" in str(exc_info.value)
    assert "not reachable" in str(exc_info.value).lower() or "closed" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# ConnectorUnreachable message quality
# ---------------------------------------------------------------------------

def test_connector_unreachable_message_mentions_zotero():
    """ConnectorUnreachable message contains actionable text about Zotero."""
    from pyzot.write.connector_client import ConnectorUnreachable
    exc = ConnectorUnreachable("http://127.0.0.1:23119", "connection refused")
    msg = str(exc)
    assert "Zotero" in msg
    assert "--no-require-zotero" in msg


# ---------------------------------------------------------------------------
# All retries exhausted → ConnectorUnreachable
# ---------------------------------------------------------------------------

def test_ping_raises_after_max_retries(httpserver):
    """After exhausting retries on persistent 5xx, raises ConnectorUnreachable."""
    from pyzot.write.connector_client import ConnectorUnreachable

    # Always return 500
    httpserver.expect_request("/connector/ping").respond_with_data(
        "error", status=500, content_type="text/plain"
    )
    # max_retries=1 → 2 total attempts
    client = make_client(httpserver.url_for("").rstrip("/"))
    client.max_retries = 1
    with pytest.raises(ConnectorUnreachable):
        client.ping()
