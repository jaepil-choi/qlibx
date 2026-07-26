from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from qlib_extended.research import (
    ConsensusHybridInputs,
    DataCatalog,
    build_consensus_hybrid_specs,
    load_alpha_definitions,
    prepare_consensus_hybrid_scores,
)


ROOT = Path(__file__).resolve().parents[1]


def _definition():
    catalog = DataCatalog.from_directory(ROOT / "configs" / "data")
    return load_alpha_definitions(
        ROOT / "configs" / "alphas", data_catalog=catalog
    )["consensus.revision_market_event_drift"]


def test_consensus_hybrid_grid_is_bounded_and_quarterly_or_faster() -> None:
    specs = build_consensus_hybrid_specs(_definition())

    assert len(specs) == 20
    assert {spec.holding_days for spec in specs} == {21, 63}
    assert max(spec.holding_days for spec in specs) <= 63
    assert {spec.source for spec in specs} == {
        "eps_revision_20d",
        "fy1_confirmation_10d_40d",
    }


def test_market_condition_at_event_uses_no_same_day_return() -> None:
    dates = pd.bdate_range("2025-01-02", periods=80)
    tickers = pd.Index([f"A{i}" for i in range(6)])
    base_returns = pd.DataFrame(
        np.linspace(-0.01, 0.01, len(dates) * len(tickers)).reshape(
            len(dates), len(tickers)
        ),
        index=dates,
        columns=tickers,
    )
    changed_returns = base_returns.copy()
    event_date = dates[70]
    changed_returns.loc[event_date, "A0"] = 0.90
    base = _synthetic_inputs(base_returns)
    changed = _synthetic_inputs(changed_returns)

    _, _, base_market = prepare_consensus_hybrid_scores(base)
    _, _, changed_market = prepare_consensus_hybrid_scores(changed)

    pd.testing.assert_series_equal(
        base_market["momentum_21d"].loc[event_date],
        changed_market["momentum_21d"].loc[event_date],
    )
    assert not base_market["momentum_21d"].loc[dates[71]].equals(
        changed_market["momentum_21d"].loc[dates[71]]
    )


def _synthetic_inputs(returns: pd.DataFrame) -> ConsensusHybridInputs:
    tickers = returns.columns
    industry = pd.DataFrame(
        np.tile([100, 100, 100, 200, 200, 200], (len(returns), 1)),
        index=returns.index,
        columns=tickers,
    )
    universe = pd.DataFrame(True, index=returns.index, columns=tickers)
    base = np.arange(len(returns), dtype="float64")[:, None]
    cross_section = np.arange(len(tickers), dtype="float64")[None, :]
    consensus = pd.DataFrame(
        100.0 + base + cross_section,
        index=returns.index,
        columns=tickers,
    )
    return ConsensusHybridInputs(
        returns=returns,
        transaction_amount=pd.DataFrame(
            100.0 + base + cross_section,
            index=returns.index,
            columns=tickers,
        ),
        universe=universe,
        industry=industry,
        consensus={"forward_eps": consensus, "net_income_fy1": consensus * 10.0},
        data_fingerprint="synthetic",
    )
