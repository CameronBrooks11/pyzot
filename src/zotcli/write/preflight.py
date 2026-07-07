"""Preflight check — probe the Zotero connector before any write operation.

Never raises; all outcomes are encoded in the returned PreflightReport.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PreflightReport:
    """Result of a preflight check against the Zotero connector.

    Attributes
    ----------
    reachable:
        True if the connector responded successfully to /connector/ping.
    selected_collection:
        Name of the currently selected collection in Zotero, or None.
    version:
        Connector/Zotero version string reported by /connector/ping, or None.
    error:
        Human-readable error message if ``reachable`` is False, else None.
    """

    reachable: bool
    selected_collection: str | None = field(default=None)
    version: str | None = field(default=None)
    error: str | None = field(default=None)


def check_zotero_running(
    connector_url: str = "http://127.0.0.1:23119",
) -> PreflightReport:
    """Probe the Zotero connector and return a PreflightReport.

    Never raises — all errors are captured in ``PreflightReport.error``.

    Parameters
    ----------
    connector_url:
        Base URL of the Zotero connector.  Defaults to the standard loopback
        address used by Zotero.
    """
    from zotcli.write.connector_client import ConnectorClient, ConnectorUnreachable

    client = ConnectorClient(base_url=connector_url)

    # --- ping ---
    try:
        ping_data = client.ping()
    except ConnectorUnreachable as exc:
        return PreflightReport(reachable=False, error=str(exc))
    except Exception as exc:  # noqa: BLE001
        return PreflightReport(reachable=False, error=f"Unexpected error: {exc}")

    version: str | None = None
    if isinstance(ping_data, dict):
        # Zotero returns {"prefs": {...}} or similar; version may be in different keys
        version = (
            ping_data.get("version")
            or ping_data.get("zoteroVersion")
            or ping_data.get("prefs", {}).get("version")
        )

    # --- selected collection ---
    selected_collection: str | None = None
    try:
        col_data = client.get_selected_collection()
        if col_data:
            selected_collection = col_data.get("name") or col_data.get("collection")
    except Exception:  # noqa: BLE001
        # Non-fatal — collection info is nice-to-have
        pass

    return PreflightReport(
        reachable=True,
        selected_collection=selected_collection,
        version=version,
    )
