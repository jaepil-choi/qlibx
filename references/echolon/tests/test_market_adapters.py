"""Tests for market adapter instantiation and core methods.

SHFEAdapter tests avoid methods that require external data files
(get_main_contract, should_rollover, etc.) and focus on spec lookups,
commission/margin calculations, and properties.

CryptoAdapter has no data-file dependencies, so all methods are tested.
"""
from datetime import date, datetime

import pytest

from echolon.markets.shfe.adapter import SHFEAdapter
from echolon.markets.crypto.adapter import CryptoAdapter
from echolon.markets.interface import ContractSpec


def test_contract_spec_equity_cost_anchors_are_side_aware():
    spec = ContractSpec(
        symbol="equity",
        multiplier=1.0,
        tick_size=0.01,
        margin_rate=1.0,
        commission=0.00025,
        commission_type="percentage",
        stamp_duty_rate=0.0005,
        transfer_fee_rate=0.00001,
        min_commission=5.0,
        long_only=True,
        t_plus_one=True,
        min_order_size=100.0,
    )

    assert spec.calculate_commission(10.0, 200, side="SELL") == pytest.approx(6.02, abs=0.01)
    assert spec.calculate_commission(10.0, 200, side="BUY") == pytest.approx(5.02, abs=0.01)
    assert spec.calculate_commission(50.0, 10_000, side="BUY") == pytest.approx(130.0, abs=0.01)


# =========================================================================
# SHFEAdapter
# =========================================================================


class TestSHFEAdapterProperties:
    """Test SHFEAdapter properties and basic instantiation."""

    @pytest.fixture
    def adapter(self):
        return SHFEAdapter(symbol="al")

    def test_instantiation(self, adapter):
        assert adapter is not None

    def test_market_code(self, adapter):
        assert adapter.market_code == "SHFE"

    def test_market_name(self, adapter):
        assert adapter.market_name == "Shanghai Futures Exchange"

    def test_timezone(self, adapter):
        assert adapter.timezone == "Asia/Shanghai"

    def test_symbol(self, adapter):
        assert adapter.symbol == "al"

    def test_has_contract_expiry(self, adapter):
        assert adapter.has_contract_expiry is True

    def test_supports_overnight_positions(self, adapter):
        assert adapter.supports_overnight_positions is True

    def test_repr(self, adapter):
        r = repr(adapter)
        assert "SHFEAdapter" in r
        assert "al" in r

    def test_night_session_product(self, adapter):
        # Aluminum trades in night session
        assert adapter.is_night_session_product() is True

    def test_trading_sessions_count(self, adapter):
        # al has night session -> 4 sessions (day1, day2, afternoon, night)
        assert len(adapter.trading_sessions) == 4


class TestSHFEAdapterContractSpec:
    """Test contract spec lookups (no data files needed)."""

    @pytest.fixture
    def adapter(self):
        return SHFEAdapter(symbol="al")

    def test_get_contract_spec_base_symbol(self, adapter):
        spec = adapter.get_contract_spec("al")
        assert spec.multiplier == 5.0
        assert spec.tick_size == 5.0

    def test_get_contract_spec_full_code(self, adapter):
        """Full contract code (e.g. al2403) resolves to base symbol spec."""
        spec = adapter.get_contract_spec("al2403")
        assert spec.multiplier == 5.0

    def test_get_contract_spec_unknown_raises(self, adapter):
        with pytest.raises(KeyError):
            adapter.get_contract_spec("xyz")

    def test_get_contract_spec_cu(self):
        adapter = SHFEAdapter(symbol="cu")
        spec = adapter.get_contract_spec("cu")
        assert spec.multiplier == 5.0
        assert spec.commission_type == "percentage"


class TestSHFEAdapterCalculations:
    """Test financial calculations."""

    @pytest.fixture
    def adapter(self):
        return SHFEAdapter(symbol="al")

    def test_calculate_commission(self, adapter):
        comm = adapter.calculate_commission("al", 1, 20000.0)
        # al uses the exchange-standard 3.0 CNY per lot (akshare +0.01 broker offset
        # stripped per the ratified full-panel commission authority, 2026-07-20)
        assert comm == pytest.approx(3.0)

    def test_side_keyword_is_accepted_but_ignored_for_futures(self, adapter):
        assert adapter.calculate_commission("al", 1, 20000.0, side="SELL") == pytest.approx(3.0)

    def test_calculate_margin(self, adapter):
        margin = adapter.calculate_margin("al", 1, 20000.0)
        # margin = size * price * multiplier * margin_rate
        # = 1 * 20000 * 5 * 0.09 = 9000
        assert margin == pytest.approx(9000.0)

    def test_calculate_contract_value(self, adapter):
        cv = adapter.calculate_contract_value("al", 1, 20000.0)
        # = size * price * multiplier = 1 * 20000 * 5 = 100000
        assert cv == pytest.approx(100000.0)

    def test_calculate_pnl_long(self, adapter):
        pnl = adapter.calculate_pnl("al", 1, 20000.0, 20100.0)
        # = size * (exit - entry) * multiplier = 1 * 100 * 5 = 500
        assert pnl == pytest.approx(500.0)

    def test_calculate_pnl_short(self, adapter):
        pnl = adapter.calculate_pnl("al", -1, 20000.0, 19900.0)
        # = -1 * (19900 - 20000) * 5 = -1 * -100 * 5 = 500
        assert pnl == pytest.approx(500.0)


class TestSHFEAdapterPrecision:
    """Test price/size precision."""

    @pytest.fixture
    def adapter(self):
        return SHFEAdapter(symbol="al")

    def test_price_precision(self, adapter):
        # al tick_size = 5.0 (>= 1) -> precision 0
        assert adapter.get_price_precision("al") == 0

    def test_size_precision(self, adapter):
        # SHFE always uses whole lots
        assert adapter.get_size_precision("al") == 0

    def test_round_size_uses_min_order_size(self, adapter):
        assert adapter.round_size(3.4, "al") == 3


# =========================================================================
# CryptoAdapter
# =========================================================================


class TestCryptoAdapterProperties:
    """Test CryptoAdapter properties and basic instantiation."""

    @pytest.fixture
    def adapter(self):
        return CryptoAdapter(symbol="btc")

    def test_instantiation(self, adapter):
        assert adapter is not None

    def test_market_code(self, adapter):
        assert adapter.market_code == "CRYPTO"

    def test_market_name(self, adapter):
        assert adapter.market_name == "Cryptocurrency"

    def test_timezone(self, adapter):
        assert adapter.timezone == "UTC"

    def test_symbol(self, adapter):
        assert adapter.symbol == "btc"

    def test_has_contract_expiry(self, adapter):
        assert adapter.has_contract_expiry is False

    def test_supports_overnight_positions(self, adapter):
        assert adapter.supports_overnight_positions is True

    def test_repr(self, adapter):
        r = repr(adapter)
        assert "CryptoAdapter" in r
        assert "btc" in r


class TestCryptoAdapterContracts:
    """Test perpetual contract behavior."""

    @pytest.fixture
    def adapter(self):
        return CryptoAdapter(symbol="btc")

    def test_get_main_contract(self, adapter):
        mc = adapter.get_main_contract(date(2024, 1, 15))
        assert mc == "BTC-PERP"

    def test_should_rollover_always_false(self, adapter):
        assert adapter.should_rollover("BTC-PERP", date.today(), 1) is False

    def test_rollover_target_always_none(self, adapter):
        assert adapter.get_rollover_target("BTC-PERP", date.today()) is None

    def test_expiry_date_always_none(self, adapter):
        assert adapter.get_contract_expiry_date("BTC-PERP") is None


class TestCryptoAdapterCalendar:
    """Test 24/7 trading calendar."""

    @pytest.fixture
    def adapter(self):
        return CryptoAdapter(symbol="btc")

    def test_is_trading_day_always_true(self, adapter):
        # Crypto trades every day including weekends
        assert adapter.is_trading_day(date(2024, 12, 25)) is True

    def test_is_session_active_always_true(self, adapter):
        assert adapter.is_session_active(datetime(2024, 1, 1, 3, 0, 0)) is True

    def test_next_trading_day(self, adapter):
        assert adapter.get_next_trading_day(date(2024, 1, 15)) == date(2024, 1, 16)

    def test_previous_trading_day(self, adapter):
        assert adapter.get_previous_trading_day(date(2024, 1, 15)) == date(2024, 1, 14)


class TestCryptoAdapterFunding:
    """Test funding rate utilities."""

    @pytest.fixture
    def adapter(self):
        return CryptoAdapter(symbol="btc")

    def test_next_funding_time(self, adapter):
        # 10:00 UTC -> next funding at 16:00 UTC
        nft = adapter.get_next_funding_time(datetime(2024, 1, 15, 10, 0, 0))
        assert nft == datetime(2024, 1, 15, 16, 0, 0)

    def test_near_funding(self, adapter):
        # 7:50 AM is 10 minutes before 8:00 funding
        assert adapter.is_near_funding(datetime(2024, 1, 15, 7, 50, 0)) is True

    def test_not_near_funding(self, adapter):
        # 10:00 AM is far from any funding window
        assert adapter.is_near_funding(datetime(2024, 1, 15, 10, 0, 0)) is False

    def test_estimate_funding_cost_long(self, adapter):
        # Long position with positive rate pays funding
        cost = adapter.estimate_funding_cost(100000, 0.01, is_long=True)
        assert cost == pytest.approx(1000.0)

    def test_estimate_funding_cost_short(self, adapter):
        # Short position with positive rate receives funding
        cost = adapter.estimate_funding_cost(100000, 0.01, is_long=False)
        assert cost == pytest.approx(-1000.0)
