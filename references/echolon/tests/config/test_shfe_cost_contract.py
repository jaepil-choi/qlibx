"""P1 SHFE cost contract tests from plans/SPECS.md S11."""
from __future__ import annotations

import pytest

from echolon.config.markets.core.types import InstrumentSpec
from echolon.config.markets.shfe.instruments import get_instrument
from echolon.markets.interface import ContractSpec
from echolon.markets.shfe.adapter import instrument_spec_to_contract_spec


def test_instrument_spec_supports_close_today_commission() -> None:
    spec = InstrumentSpec(
        code="xx",
        name="synthetic",
        market="SHFE",
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.09,
        commission=3.01,
        commission_type="per_contract",
        close_today_commission=9.99,
    )

    assert spec.calculate_commission(price=19000.0, size=1) == pytest.approx(3.01)
    assert spec.calculate_commission(
        price=19000.0,
        size=1,
        close_today=True,
    ) == pytest.approx(9.99)


def test_contract_spec_supports_close_today_commission() -> None:
    spec = ContractSpec(
        symbol="al",
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.09,
        commission=3.01,
        commission_type="per_contract",
        close_today_commission=9.99,
    )

    assert spec.calculate_commission(price=19000.0, size=1) == pytest.approx(3.01)
    assert spec.calculate_commission(
        price=19000.0,
        size=1,
        close_today=True,
    ) == pytest.approx(9.99)


def test_instrument_to_contract_spec_preserves_close_today_commission() -> None:
    instrument = InstrumentSpec(
        code="xx",
        name="synthetic",
        market="SHFE",
        multiplier=5.0,
        tick_size=5.0,
        margin_rate=0.09,
        commission=3.01,
        commission_type="per_contract",
        close_today_commission=9.99,
    )

    contract = instrument_spec_to_contract_spec(instrument)

    assert contract.close_today_commission == 9.99
    assert contract.calculate_commission(
        price=19000.0,
        size=1,
        close_today=True,
    ) == pytest.approx(9.99)


def test_cu_percentage_commission_includes_multiplier() -> None:
    cu = get_instrument("cu")

    assert cu.commission_type == "percentage"
    assert cu.calculate_commission(price=70000.0, size=1) == pytest.approx(17.50)


def test_close_today_none_defaults_to_normal_commission() -> None:
    # A synthetic percentage spec with no explicit close-today falls back to the normal
    # rate (mechanism test; kept synthetic so it is immune to real-instrument rate data
    # — e.g. cu now carries an explicit doubled 平今 leg per the ratified 2026-07-20
    # full-panel commission authority).
    spec = InstrumentSpec(
        code="xx",
        name="synthetic",
        market="SHFE",
        multiplier=5.0,
        tick_size=10.0,
        margin_rate=0.09,
        commission=0.00005,
        commission_type="percentage",
        close_today_commission=None,
    )

    assert spec.close_today_commission is None
    assert spec.calculate_commission(
        price=70000.0,
        size=1,
        close_today=True,
    ) == pytest.approx(spec.calculate_commission(price=70000.0, size=1))
