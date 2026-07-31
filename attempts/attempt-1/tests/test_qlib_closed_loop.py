from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from qlibx._vendor.qlib_backend.backend import QlibClosedLoopBackend


def _scenario(*, volume: float = 1_000.0):
    dates = pd.bdate_range("2025-01-02", periods=6)
    prices = pd.DataFrame({"A": [100.0, 102.0, 101.0, 103.0, 99.0, 104.0]}, index=dates)
    return SimpleNamespace(
        execution_price=prices,
        valuation_price=prices,
        universe=pd.DataFrame(True, index=dates, columns=["A"]),
        booksize=1_000.0,
        active_booksize=1_000.0,
        position_unit_factor=pd.DataFrame(1.0, index=dates, columns=["A"]),
        volume=pd.DataFrame(volume, index=dates, columns=["A"]),
        buyable=pd.DataFrame(True, index=dates, columns=["A"]),
        sellable=pd.DataFrame(True, index=dates, columns=["A"]),
        asset_class=pd.Series("stock", index=["A"]),
        lot_size=pd.Series(1, index=["A"]),
        cost_policy={"stock": {"buy_rate": 0.0, "sell_rate": 0.0, "sell_tax": 0.0}},
        max_volume_participation=1.0,
        suspended=None,
        upper_price_limit=None,
        lower_price_limit=None,
    )


def test_partial_fill_uses_qlib_dealt_quantity() -> None:
    scenario = _scenario(volume=5.0)
    targets = pd.DataFrame(1.0, index=scenario.execution_price.index, columns=["A"])
    result = QlibClosedLoopBackend().run_targets(scenario, targets)
    first_fill = result.fills().iloc[0]
    first_position = result.positions().query("trade_date == @scenario.execution_price.index[0]")
    assert first_fill["filled_quantity"] == 5
    assert first_fill["reason_code"] == "volume_limited"
    assert first_position.iloc[0]["held_quantity"] == 5


def test_resume_matches_uninterrupted_observable_tables() -> None:
    scenario = _scenario()
    targets = pd.DataFrame(
        {"A": [0.0, 0.5, 0.5, 0.0, 0.8, 0.2]}, index=scenario.execution_price.index
    )
    backend = QlibClosedLoopBackend()
    full = backend.run_targets(scenario, targets)
    first = backend.run_targets(scenario, targets, end_position=3)
    resumed = backend.run_targets(
        scenario,
        targets,
        start_position=3,
        resume_state=first.evidence["resume_state"],
    )
    for name in ("orders", "fills", "positions", "account_daily"):
        combined = pd.concat([getattr(first, name)(), getattr(resumed, name)()]).reset_index(
            drop=True
        )
        expected = getattr(full, name)().reset_index(drop=True)
        pd.testing.assert_frame_equal(combined, expected)
