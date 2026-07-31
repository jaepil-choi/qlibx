"""Tests for XtdcClient credential handling.

Regression coverage for 2026-05-07 — the previously-hardcoded Xuntou
token was leaked publicly via the open-source echolon repo. These tests
verify that:

- No hardcoded token appears in xtdc_client.py source
- XtdcClient raises XtdcCredentialsMissing when no token is provided
- Constructor kwargs are honored
- Environment variables are honored
"""
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

# Stub xtquant before importing
for _mod_name in (
    "xtquant", "xtquant.xtconstant", "xtquant.xtdata",
    "xtquant.xtdatacenter", "xtquant.xttrader", "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.live.platforms.miniqmt.xtdc_client import (  # noqa: E402
    XtdcClient,
    XtdcCredentialsMissing,
    XTDC_DEFAULT_PORT,
)


# ---------------------------------------------------------------------------
# Source-level guard — no hardcoded secrets may ever reappear
# ---------------------------------------------------------------------------


def test_xtdc_client_source_has_no_hardcoded_credentials():
    """Pattern check — xtdc_client.py must never call ``xtdc.set_token``
    with a string literal, and must never embed an IP:port literal in
    its source. Credentials live only in private deployments
    (e.g. ``goingmerry/credentials.py``).

    A specific-literal regression check (against any historically-leaked
    value) lives in the private repo — putting that literal in the
    open-source test file would re-publish it.
    """
    import re
    src = Path(__file__).resolve().parents[2] / (
        "echolon/live/platforms/miniqmt/xtdc_client.py"
    )
    text = src.read_text(encoding="utf-8")

    # Reject any call like xtdc.set_token("...") with a literal string.
    # The legitimate form is xtdc.set_token(self._token) — a variable.
    bad_set_token = re.search(
        r"""xtdc\.set_token\s*\(\s*['"][^'"]+['"]\s*\)""", text
    )
    assert bad_set_token is None, (
        "xtdc.set_token() must not be called with a string literal — "
        "credentials must come from constructor kwargs or env vars."
    )

    # Reject any IPv4:port string literal in the source.
    ip_port = re.search(r"""['"]\d{1,3}(?:\.\d{1,3}){3}:\d+['"]""", text)
    assert ip_port is None, (
        f"IP:port literal found in xtdc_client.py: {ip_port.group()} — "
        "Xuntou server addresses must come from goingmerry's "
        "xtdc_credentials.json, not be hardcoded."
    )

    # Reject any 40-char lowercase-hex literal that looks like a token.
    hex_token = re.search(r"""['"][0-9a-f]{40}['"]""", text)
    assert hex_token is None, (
        f"Possible token literal found in xtdc_client.py: "
        f"{hex_token.group()[:8]}... — credentials must come from "
        "constructor kwargs or env vars."
    )


# ---------------------------------------------------------------------------
# Constructor / env-var resolution
# ---------------------------------------------------------------------------


def _reset_env(monkeypatch):
    """Clear xtdc env vars so tests don't depend on the runner's env."""
    for k in ("XUNTOU_TOKEN", "XUNTOU_ADDR_LIST", "XUNTOU_PORT"):
        monkeypatch.delenv(k, raising=False)


@pytest.fixture(autouse=True)
def _reset_listener_flag():
    """Each test starts with the class-level listener flag cleared so
    _ensure_listener actually executes."""
    XtdcClient._listener_ready = False
    yield
    XtdcClient._listener_ready = False


def test_constructor_kwargs_take_priority(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("XUNTOU_TOKEN", "from-env")
    client = XtdcClient(token="from-kwarg", addr_list=["a:1", "b:2"], port=12345)
    assert client._token == "from-kwarg"
    assert client._addr_list == ["a:1", "b:2"]
    assert client._port == 12345


def test_env_var_fallback_when_no_kwargs(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("XUNTOU_TOKEN", "from-env")
    monkeypatch.setenv("XUNTOU_ADDR_LIST", "h1:1, h2:2 ,h3:3")
    monkeypatch.setenv("XUNTOU_PORT", "9999")
    client = XtdcClient()
    assert client._token == "from-env"
    # Whitespace stripped, empty entries filtered.
    assert client._addr_list == ["h1:1", "h2:2", "h3:3"]
    assert client._port == 9999


def test_default_port_when_none_supplied(monkeypatch):
    _reset_env(monkeypatch)
    monkeypatch.setenv("XUNTOU_TOKEN", "x")
    client = XtdcClient()
    assert client._port == XTDC_DEFAULT_PORT


def test_ensure_listener_raises_when_no_token(monkeypatch):
    _reset_env(monkeypatch)
    client = XtdcClient()
    assert client._token == ""
    with pytest.raises(XtdcCredentialsMissing):
        client._ensure_listener()


def test_connect_propagates_credentials_missing(monkeypatch):
    """connect() must raise XtdcCredentialsMissing rather than swallow
    it as a generic 'connection failed'. Otherwise mis-deployment would
    silently disable the data pipeline."""
    _reset_env(monkeypatch)
    client = XtdcClient()
    with pytest.raises(XtdcCredentialsMissing):
        client.connect()


def test_connect_switches_existing_xtdata_client_to_token_port(monkeypatch):
    _reset_env(monkeypatch)
    fake_xtdata = MagicMock()
    monkeypatch.setitem(sys.modules, "xtquant.xtdata", fake_xtdata)
    import xtquant

    monkeypatch.setattr(xtquant, "xtdata", fake_xtdata, raising=False)
    client = XtdcClient(token="fixture", port=58616)
    monkeypatch.setattr(client, "_ensure_listener", lambda: None)

    assert client.connect() is True

    fake_xtdata.disconnect.assert_called_once_with()
    fake_xtdata.connect.assert_called_once_with(port=58616)


def test_addr_list_omitted_when_empty(monkeypatch, caplog):
    """When no addr_list is supplied, the listener should warn and
    fall through to xtdc's built-in defaults."""
    import logging
    _reset_env(monkeypatch)
    monkeypatch.setenv("XUNTOU_TOKEN", "x")
    # When the real xtquant package is installed (Windows trading PC),
    # _ensure_listener would otherwise call into xtdc.init/listen and
    # attempt a real network connection. Stub xtquant.xtdatacenter (both
    # as a sys.modules entry and as an attribute on the xtquant package,
    # since `from xtquant import xtdatacenter` reads the attribute when
    # the package is already loaded) so the test exercises only our
    # pre-init logging branch.
    import sys
    from unittest.mock import MagicMock
    fake_xtdc = MagicMock()
    monkeypatch.setitem(sys.modules, "xtquant.xtdatacenter", fake_xtdc)
    import xtquant
    monkeypatch.setattr(xtquant, "xtdatacenter", fake_xtdc, raising=False)
    client = XtdcClient()
    assert client._addr_list == []
    with caplog.at_level(logging.WARNING):
        client._ensure_listener()
    assert any(
        "No addr_list supplied" in rec.message for rec in caplog.records
    ), "Expected a warning when addr_list is empty"


def test_shutdown_stops_listener_and_resets_class_state(monkeypatch):
    _reset_env(monkeypatch)
    client = XtdcClient(token="fixture")
    events = []
    monkeypatch.setattr(client, "disconnect", lambda: events.append("disconnect"))
    fake_xtdc = MagicMock()
    monkeypatch.setitem(sys.modules, "xtquant.xtdatacenter", fake_xtdc)
    import xtquant

    monkeypatch.setattr(xtquant, "xtdatacenter", fake_xtdc, raising=False)
    XtdcClient._listener_ready = True

    result = client.shutdown()

    assert result is True
    assert events == ["disconnect"]
    fake_xtdc.shutdown.assert_called_once_with()
    assert XtdcClient._listener_ready is False


def test_shutdown_without_initialized_listener_only_disconnects(monkeypatch):
    _reset_env(monkeypatch)
    client = XtdcClient(token="fixture")
    events = []
    monkeypatch.setattr(client, "disconnect", lambda: events.append("disconnect"))
    fake_xtdc = MagicMock()
    monkeypatch.setitem(sys.modules, "xtquant.xtdatacenter", fake_xtdc)
    import xtquant

    monkeypatch.setattr(xtquant, "xtdatacenter", fake_xtdc, raising=False)
    XtdcClient._listener_ready = False

    result = client.shutdown()

    assert result is True
    assert events == ["disconnect"]
    fake_xtdc.shutdown.assert_not_called()


def test_shutdown_reports_missing_native_symbol(monkeypatch):
    _reset_env(monkeypatch)
    client = XtdcClient(token="fixture")
    monkeypatch.setattr(client, "disconnect", lambda: None)
    fake_xtdc = MagicMock()
    fake_xtdc.shutdown.side_effect = AttributeError("missing native shutdown")
    monkeypatch.setitem(sys.modules, "xtquant.xtdatacenter", fake_xtdc)
    import xtquant

    monkeypatch.setattr(xtquant, "xtdatacenter", fake_xtdc, raising=False)
    XtdcClient._listener_ready = True

    result = client.shutdown()

    assert result is False
    assert XtdcClient._listener_ready is False
