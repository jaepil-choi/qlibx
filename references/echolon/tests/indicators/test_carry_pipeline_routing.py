"""Kind-routing of curve_carry indicators in the indicator pipeline (Step 2b/2c).

curve_carry indicators (the 5 forward-curve carry signals) cannot go through the
per-contract TA-Lib path (``_resolve_function`` would IND-002 on them — they take
a multi-contract snapshot, not a single-contract df). The processor partitions the
declared indicator_list by catalog KIND: curve_carry -> a dedicated curve stage,
everything else (TA-Lib + registered classifiers) -> the per-contract path. The
split is DORMANT unless a curve_carry name is declared.
"""
from __future__ import annotations

import pytest

from echolon.config.markets.factory import MarketFactory
from echolon.indicators.engine.processor import IndicatorProcessor, _split_curve_carry


# --------------------------------------------------------------------------- #
# Routing-split logic (hermetic — pure partition, no processor run)
# --------------------------------------------------------------------------- #
def test_split_routes_carry_to_curve_stage():
    il = {"atr": {"timeperiod": 14}, "carry_front_back": {}, "carry_z_3m": {}}
    curve, per_contract = _split_curve_carry(il)
    assert set(curve) == {"carry_front_back", "carry_z_3m"}
    assert set(per_contract) == {"atr"}


def test_split_keeps_classifiers_and_unknowns_per_contract():
    # registered-classifier names + unknown names are NOT in the catalog ->
    # info() is None -> they fall through to the per-contract path untouched.
    il = {"market_regime": {}, "trs_regime": {}, "totally_unknown_xyz": {}}
    curve, per_contract = _split_curve_carry(il)
    assert curve == {}
    assert set(per_contract) == set(il)


def test_split_is_case_insensitive_for_carry():
    curve, per_contract = _split_curve_carry({"CARRY_FRONT_BACK": {}, "ATR": {}})
    assert "CARRY_FRONT_BACK" in curve
    assert "ATR" in per_contract


def test_split_empty():
    assert _split_curve_carry({}) == ({}, {})


def test_split_preserves_param_specs():
    curve, per_contract = _split_curve_carry({"atr": {"timeperiod": [5, 30]}})
    assert per_contract == {"atr": {"timeperiod": [5, 30]}}


# --------------------------------------------------------------------------- #
# __init__ guards (fail-loud; raise before any data/paths access)
# --------------------------------------------------------------------------- #
@pytest.fixture
def interday_ctx():
    return MarketFactory.create(
        market="SHFE", instrument="al", frequency="interday", bar_size="1d"
    )


@pytest.fixture
def intraday_ctx():
    return MarketFactory.create(
        market="SHFE", instrument="al", frequency="intraday", bar_size="15m"
    )


def test_carry_on_intraday_raises(intraday_ctx, tmp_path):
    with pytest.raises(ValueError, match="interday-only"):
        IndicatorProcessor(
            ctx=intraday_ctx,
            trading_date_list=[],
            indicator_list={"carry_front_back": {}},
            output_dir=str(tmp_path),
            paths=None,  # guard raises before paths is used
        )


def test_carry_with_param_spec_raises(interday_ctx, tmp_path):
    with pytest.raises(ValueError, match="do not accept a param spec"):
        IndicatorProcessor(
            ctx=interday_ctx,
            trading_date_list=[],
            indicator_list={"carry_z_3m": {"window": [40, 80]}},
            output_dir=str(tmp_path),
            paths=None,
        )


def test_carry_empty_spec_routes_clean(interday_ctx, tmp_path):
    # Declared with an empty spec -> no raise; split populated correctly.
    proc = IndicatorProcessor(
        ctx=interday_ctx,
        trading_date_list=[],
        indicator_list={"atr": {"timeperiod": 14}, "carry_front_back": {}},
        output_dir=str(tmp_path),
        paths=None,
    )
    assert set(proc._curve_carry_list) == {"carry_front_back"}
    assert set(proc._per_contract_indicator_list) == {"atr"}
