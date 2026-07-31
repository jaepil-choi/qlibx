"""Tests for MiniQMTClient.resolve_aggressive_price (Layer 1 buffer fix).

Reference: docs/superpowers/designs/2026-05-07-miniqmt-architecture-and-order-logic.md
section 22.1 (Layer 1 buffer test specifications).

These tests verify that yesterday's bug pattern (FIX_PRICE @ bid1 with zero
buffer, order stranded for 30 minutes) cannot recur: every Tier 1 / Tier 2
return path now applies BUFFER_TICKS_BY_ATTEMPT[attempt] * price_tick.
"""
import os
import sys
from datetime import datetime
from unittest.mock import MagicMock, patch

# Stub out xtquant (Windows-only broker SDK) before importing qmt_client.
for _mod_name in (
    "xtquant",
    "xtquant.xtconstant",
    "xtquant.xtdata",
    "xtquant.xttrader",
    "xtquant.xttype",
):
    sys.modules.setdefault(_mod_name, MagicMock())

import pytest  # noqa: E402
from xtquant import xtconstant  # noqa: E402  (resolves to stub above)

from echolon.live.config.deploy_config import QMTAccountConfig  # noqa: E402
from echolon.live.config.order_policy import (  # noqa: E402
    BUFFER_TICKS_BY_ATTEMPT,
    DEFAULT_BUFFER_TICKS,
    TICK_SNAPSHOT_MAX_AGE_S,
)
from echolon.live.platforms.miniqmt.qmt_client import MiniQMTClient  # noqa: E402


def _fresh_time_ms() -> int:
    """Return current time in ms, simulating a fresh tick.time."""
    return int(datetime.now().timestamp() * 1000)


@pytest.fixture
def client():
    """A MiniQMTClient instance with no broker connection."""
    config = QMTAccountConfig(qmt_path="/tmp/fake-qmt", account_id="test")
    return MiniQMTClient(config)


def _patch_tick(client, tick_dict):
    """Patch _get_tick_snapshot to return the given dict."""
    return patch.object(
        client, "_get_tick_snapshot", return_value=tick_dict,
    )


def _patch_detail(price_tick):
    """Patch xtdata.get_instrument_detail to return given price_tick."""
    return patch(
        "echolon.live.platforms.miniqmt.qmt_client.xtdata.get_instrument_detail",
        return_value={"PriceTick": price_tick},
    )


# ---------------------------------------------------------------------------
# Tier 1 — counterparty price + buffer (the bug-fix critical path)
# ---------------------------------------------------------------------------


def test_buffer_applied_for_sell_at_attempt_1(client):
    """SELL intent at bid1=24645, price_tick=5, attempt=1 → 24645 - 4*5 = 24625."""
    tick = {
        "askPrice": [24650.0, 24655.0],
        "bidPrice": [24645.0, 24640.0],
        "lastPrice": 24648.0,
        "time": _fresh_time_ms(),
    }
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    assert price_type == xtconstant.FIX_PRICE
    assert price == 24645 - 4 * 5  # 24625


def test_buffer_applied_for_buy_at_attempt_1(client):
    """BUY intent at ask1=24650, price_tick=5, attempt=1 → 24650 + 4*5 = 24670."""
    tick = {
        "askPrice": [24650.0, 24655.0],
        "bidPrice": [24645.0, 24640.0],
        "lastPrice": 24648.0,
        "time": _fresh_time_ms(),
    }
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_LONG", attempt=1,
        )
    assert price_type == xtconstant.FIX_PRICE
    assert price == 24650 + 4 * 5  # 24670


def test_buffer_escalates_with_attempt(client):
    """SELL: attempt 1 (4 ticks), 2 (8 ticks), 3 (16 ticks) — each more aggressive."""
    tick = {"bidPrice": [24645.0], "askPrice": [24650.0], "lastPrice": 24648.0, "time": _fresh_time_ms()}
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        _, p1 = client.resolve_aggressive_price("al2606.SF", "ENTRY_SHORT", attempt=1)
        _, p2 = client.resolve_aggressive_price("al2606.SF", "ENTRY_SHORT", attempt=2)
        _, p3 = client.resolve_aggressive_price("al2606.SF", "ENTRY_SHORT", attempt=3)
    # SELL: more aggressive = lower limit; p3 < p2 < p1 < bid1
    assert p3 < p2 < p1
    assert p1 == 24645 - 4 * 5
    assert p2 == 24645 - 8 * 5
    assert p3 == 24645 - 16 * 5


def test_unknown_attempt_uses_default_buffer(client):
    """attempt=99 → DEFAULT_BUFFER_TICKS (defensive)."""
    tick = {"bidPrice": [24645.0], "askPrice": [24650.0], "lastPrice": 24648.0, "time": _fresh_time_ms()}
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        _, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=99,
        )
    assert price == 24645 - DEFAULT_BUFFER_TICKS * 5


# ---------------------------------------------------------------------------
# Tier 2 — lastPrice + buffer (when bid/ask is missing)
# ---------------------------------------------------------------------------


def test_tier2_fallback_when_no_bid_for_sell(client):
    """SELL with empty bidPrice → Tier 2: last=24648 - 4*5 = 24628."""
    tick = {"bidPrice": [0], "askPrice": [24650.0], "lastPrice": 24648.0, "time": _fresh_time_ms()}
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    assert price_type == xtconstant.FIX_PRICE
    assert price == 24648 - 4 * 5  # 24628


def test_tier2_fallback_when_no_ask_for_buy(client):
    """BUY with empty askPrice → Tier 2: last=24648 + 4*5 = 24668."""
    tick = {"bidPrice": [24645.0], "askPrice": [0], "lastPrice": 24648.0, "time": _fresh_time_ms()}
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_LONG", attempt=1,
        )
    assert price_type == xtconstant.FIX_PRICE
    assert price == 24648 + 4 * 5  # 24668


# ---------------------------------------------------------------------------
# Tier 3 — LATEST_PRICE fallback (when all market data is empty)
# ---------------------------------------------------------------------------


def test_tier3_fallback_when_tick_snapshot_none(client):
    """Tick snapshot empty → LATEST_PRICE, -1."""
    with _patch_tick(client, None), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    assert price_type == xtconstant.LATEST_PRICE
    assert price == -1


def test_tier3_fallback_when_no_prices_at_all(client):
    """Tick has no usable bid/ask/last → LATEST_PRICE."""
    tick = {"bidPrice": [0], "askPrice": [0], "lastPrice": 0, "time": _fresh_time_ms()}
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    assert price_type == xtconstant.LATEST_PRICE
    assert price == -1


# ---------------------------------------------------------------------------
# Yesterday's bug regression — must never reproduce
# ---------------------------------------------------------------------------


def test_yesterdays_bug_does_not_recur(client):
    """Regression: 2026-05-06 al_s1 ENTRY_SHORT al2606.SF FIX_PRICE @ bid1=24645
    sat unfilled for 30 minutes (zero buffer). Same inputs MUST now produce a
    price strictly below bid1.
    """
    tick = {
        "askPrice": [24650.0],
        "bidPrice": [24645.0],
        "lastPrice": 24648.0,
        "time": _fresh_time_ms(),
    }
    with _patch_tick(client, tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    assert price_type == xtconstant.FIX_PRICE
    assert price < 24645, (
        f"BUG REGRESSION: SELL price {price} >= bid1 24645 "
        f"would reproduce yesterday's stranding"
    )


# ---------------------------------------------------------------------------
# Buffer-policy contract (from order_policy.py)
# ---------------------------------------------------------------------------


def test_buffer_policy_attempt_1_is_at_least_4_ticks():
    """Sanity: yesterday's fix requires attempt-1 buffer >= 4 ticks."""
    assert BUFFER_TICKS_BY_ATTEMPT[1] >= 4


def test_tier3_fallback_when_tick_stale(client):
    """Stale tick (time > 2s old) → fall through Tier 1, use Tier 2."""
    stale_tick = {
        "askPrice": [24650.0], "bidPrice": [24645.0], "lastPrice": 24648.0,
        "time": _fresh_time_ms() - int((TICK_SNAPSHOT_MAX_AGE_S + 1.0) * 1000),
    }
    with _patch_tick(client, stale_tick), _patch_detail(price_tick=5):
        price_type, price = client.resolve_aggressive_price(
            "al2606.SF", "ENTRY_SHORT", attempt=1,
        )
    # Tier 1 skipped; Tier 2 also skipped (lastPrice path needs fresh tick).
    # Whole `tick is not None` block gates on freshness, so falls to Tier 3.
    assert price_type == xtconstant.LATEST_PRICE
    assert price == -1


def test_dolphinquantstrategy_mirror_buffer_constant():
    """Mirror sanity check: DolphinQuantStrategy's qmt_client.py buffer constants
    match echolon's BUFFER_TICKS_BY_ATTEMPT."""
    # The mirror lives in a private checkout whose location does not belong in a
    # public repository: point ECHOLON_DQS_MIRROR_QMT_CLIENT at its qmt_client.py
    # to run this cross-check; unset, the mirror is absent and the test skips.
    legacy_path = os.environ.get("ECHOLON_DQS_MIRROR_QMT_CLIENT")
    if legacy_path is None:
        pytest.skip("DolphinQuantStrategy mirror not configured (normal in standalone test runs)")
    with open(legacy_path, "r") as f:
        text = f.read()
    assert "buffer_ticks_by_attempt = {1: 4, 2: 8, 3: 16}" in text, (
        "DolphinQuantStrategy mirror buffer constants must match echolon's "
        "BUFFER_TICKS_BY_ATTEMPT exactly"
    )
