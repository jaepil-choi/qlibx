from __future__ import annotations

from echolon.backtest.book.engine import _slipped_price


def test_sub_tick_positive_slippage_charges_one_adverse_tick() -> None:
    assert _slipped_price(977.0, 1.0, 5.0, 1.0) == 978.0
    assert _slipped_price(977.0, -1.0, 5.0, 1.0) == 976.0


def test_zero_slippage_charges_nothing() -> None:
    assert _slipped_price(977.0, 1.0, 0.0, 1.0) == 977.0
    assert _slipped_price(977.0, -1.0, 0.0, 1.0) == 977.0


def test_over_tick_slippage_rounds_offset_away_from_fill_price() -> None:
    # A 10 bps charge at 2,500 is 2.5 price units, so a 1-unit tick costs 3.
    assert _slipped_price(2_500.0, 1.0, 10.0, 1.0) == 2_503.0
    assert _slipped_price(2_500.0, -1.0, 10.0, 1.0) == 2_497.0


def test_exact_whole_tick_offset_does_not_overcharge_for_float_noise() -> None:
    assert _slipped_price(19_010.0, 1.0, 10.0, 0.01) == 19_029.01
    assert _slipped_price(19_010.0, -1.0, 10.0, 0.01) == 18_990.99
