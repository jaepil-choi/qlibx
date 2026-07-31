"""Live-layer broker-unavailable error uses the LIV-001 catalog code."""
import sys
from unittest.mock import MagicMock

# Stub out xtquant (Windows-only broker SDK) before importing qmt_client.
# The helpers under test do not touch xtquant; the stubs only satisfy the
# module-level imports at qmt_client.py:42-44.
for _mod_name in (
    "xtquant",
    "xtquant.xtconstant",
    "xtquant.xtdata",
    "xtquant.xttrader",
    "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402

from echolon.errors import EchelonError  # noqa: E402


def test_raise_broker_unavailable_liv_001():
    from echolon.live.platforms.miniqmt.qmt_client import _raise_broker_unavailable

    with pytest.raises(EchelonError) as exc:
        _raise_broker_unavailable(
            account_id="test-acct-123",
            error="connection refused",
        )
    assert exc.value.code == "LIV-001"
    assert "test-acct-123" in str(exc.value)


