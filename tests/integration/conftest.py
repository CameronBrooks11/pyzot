"""Integration-test conftest.

The 0.3.0 changes flip ``--with-pdf`` default to True (controlled by the
``autoattach.enabled`` config key, default True). Most pre-existing
integration tests assume ``add`` does NOT try to fetch a PDF unless asked.

This conftest installs an autouse fixture that monkeypatches
``_autoattach_enabled`` to return False for the duration of every
integration test, restoring the pre-0.3.0 default. Tests that specifically
exercise the auto-attach path can request the ``enable_autoattach`` fixture
to flip it back on.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _disable_autoattach_by_default(monkeypatch):
    """Disable auto-attach for every integration test.

    Without this, tests that just call ``add doi <id>`` would trigger the
    find-file pipeline and try to attach a PDF — which fails noisily against
    the mock connector and adds network calls that the test wasn't aware of.
    """
    monkeypatch.setattr("pyzot.cli.add._autoattach_enabled", lambda: False)
    yield


@pytest.fixture
def enable_autoattach(monkeypatch):
    """Opt-in fixture for tests that want to exercise the auto-attach path."""
    monkeypatch.setattr("pyzot.cli.add._autoattach_enabled", lambda: True)
    yield
