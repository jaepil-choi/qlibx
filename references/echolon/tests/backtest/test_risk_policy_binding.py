"""Falsifiers for opaque risk-policy bindings at the book boundary."""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from echolon.backtest.book import (
    BookBacktestConfig,
    DailyBookBacktester,
    RiskPolicyBinding,
)
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import (
    BookState,
    Constructor,
    ConstructorConfig,
    PortfolioStrategy,
    RebalanceRecord,
    TargetBook,
)
from echolon.signals import ScoreVector, SignalEngine


_POLICY_SHA = "a" * 64


class _Panel:
    snapshot_version = "synthetic-risk-panel-v1"

    def __init__(self) -> None:
        self.calendar = [
            dt.date(2024, 1, 2) + dt.timedelta(days=index) for index in range(5)
        ]
        self.instruments = ["asset"]
        self.view_calls = 0
        prices = [100.0, 101.0, 99.0, 102.0, 103.0]
        self._bars = pd.DataFrame(
            {
                "open": prices,
                "high": [price + 1.0 for price in prices],
                "low": [price - 1.0 for price in prices],
                "close": prices,
                "settle": prices,
                "volume": [1000] * len(prices),
                "open_interest": [5000] * len(prices),
                "contract": ["C1"] * len(prices),
            },
            index=self.calendar,
        )
        self._meta = InstrumentMeta(
            instrument_id="asset",
            sector="generic",
            multiplier=1.0,
            tick=1.0,
            margin_rate=0.1,
            commission=1.0,
            commission_type="per_contract",
            close_today_commission=1.0,
            currency="RMB",
        )

    def view(self, date: dt.date) -> "_View":
        self.view_calls += 1
        return _View(self, date)


class _View:
    def __init__(self, panel: _Panel, date: dt.date) -> None:
        self._panel = panel
        self.date = date
        self.instruments = tuple(panel.instruments)

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        return self._panel._bars.loc[
            self._panel._bars.index <= self.date
        ].tail(lookback).copy()

    def current_bar(self, instrument: str):
        rows = self._panel._bars.loc[self._panel._bars.index == self.date]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        rows = self._panel._bars.loc[self._panel._bars.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        rows = self._panel._bars.loc[self._panel._bars.index <= self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._panel._meta


class _ConstantSignal(SignalEngine):
    signal_id = "constant"
    family = "generic"
    params = {}
    data_requirements = {}

    def __init__(self) -> None:
        self.calls = 0

    def compute(self, view) -> ScoreVector:
        self.calls += 1
        return ScoreVector(
            signal_id=self.signal_id,
            family=self.family,
            date=view.date,
            scores={"asset": 1.0},
        )


class _MutatingSignal(_ConstantSignal):
    def __init__(self) -> None:
        super().__init__()
        self.owner: PortfolioStrategy | None = None

    def compute(self, view) -> ScoreVector:
        assert self.owner is not None
        self.owner.constructor.config.vol_target_ann_pct = 1200.0
        return super().compute(view)


class _StrategySubclass(PortfolioStrategy):
    def rebalance(self, view, book):
        raise AssertionError("bound execution must reject this override before work")


class _ConstructorSubclass(Constructor):
    def construct(self, **kwargs):
        raise AssertionError("bound execution must reject this override before work")


class _StaticStrategy:
    def __init__(self) -> None:
        self.calls = 0

    def rebalance(self, view, book: BookState):
        self.calls += 1
        return (
            TargetBook(date=view.date, targets={}),
            RebalanceRecord(date=view.date, instruments={}),
        )


def _binding(target: str = "12") -> RiskPolicyBinding:
    return RiskPolicyBinding(
        policy_sha256=_POLICY_SHA,
        effective_constructor_vol_target_ann_pct=target,
    )


def _strategy(target: float = 12.0) -> tuple[PortfolioStrategy, _ConstantSignal]:
    signal = _ConstantSignal()
    strategy = PortfolioStrategy(
        [signal],
        {signal.signal_id: 1.0},
        ConstructorConfig(
            vol_target_ann_pct=target,
            sector_caps_pct={"generic": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
            sizing_mode="research",
        ),
    )
    return strategy, signal


def _strategy_with_signal(
    signal: SignalEngine,
    target: float = 12.0,
) -> PortfolioStrategy:
    return PortfolioStrategy(
        [signal],
        {signal.signal_id: 1.0},
        ConstructorConfig(
            vol_target_ann_pct=target,
            sector_caps_pct={"generic": 100.0},
            max_margin_utilization_pct=100.0,
            min_abs_score_for_position=0.0,
            sizing_mode="research",
        ),
    )


def _config(
    panel: _Panel,
    binding: RiskPolicyBinding | None = None,
) -> BookBacktestConfig:
    return BookBacktestConfig(
        start=panel.calendar[0],
        end=panel.calendar[-1],
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
        risk_policy_binding=binding,
    )


@pytest.mark.parametrize("target", ["0", "-1", "NaN", "Infinity", "-Infinity"])
def test_binding_rejects_nonpositive_or_nonfinite_target(target: str):
    with pytest.raises(ValidationError, match="finite and positive"):
        _binding(target)


@pytest.mark.parametrize("target", [12, 12.0, "12.0", "012", "+12", "1.2e1"])
def test_binding_rejects_noncanonical_target(target):
    with pytest.raises(ValidationError, match="canonical"):
        _binding(target)  # type: ignore[arg-type]


def test_binding_model_is_frozen():
    binding = _binding()
    with pytest.raises(ValidationError, match="frozen"):
        binding.policy_sha256 = "b" * 64


def test_model_copy_tamper_is_revalidated_before_any_mutation(tmp_path: Path):
    panel = _Panel()
    strategy, signal = _strategy()
    backtester = DailyBookBacktester(
        output_dir=tmp_path / "must-not-exist",
        rebalance_weekday=None,
    )
    sentinel_date = dt.date(1999, 1, 1)
    backtester._last_buy_fill_dates = {"sentinel": sentinel_date}
    tampered = _binding().model_copy(
        update={"effective_constructor_vol_target_ann_pct": "NaN"}
    )
    config = _config(panel).model_copy(update={"risk_policy_binding": tampered})

    with pytest.raises(ValueError, match="failed revalidation"):
        backtester.run(strategy, panel, config)

    assert backtester._last_buy_fill_dates == {"sentinel": sentinel_date}
    assert signal.calls == 0
    assert panel.view_calls == 0
    assert not backtester.output_dir.exists()


def test_missing_strategy_surface_and_target_mismatch_fail_before_work(
    tmp_path: Path,
):
    panel = _Panel()
    malformed = _StaticStrategy()
    malformed_output = tmp_path / "malformed"
    with pytest.raises(ValueError, match="exact built-in PortfolioStrategy"):
        DailyBookBacktester(
            output_dir=malformed_output,
            rebalance_weekday=None,
        ).run(malformed, panel, _config(panel, _binding()))  # type: ignore[arg-type]
    assert malformed.calls == 0
    assert panel.view_calls == 0
    assert not malformed_output.exists()

    strategy, signal = _strategy(13.0)
    mismatch_output = tmp_path / "mismatch"
    with pytest.raises(ValueError, match="does not match"):
        DailyBookBacktester(
            output_dir=mismatch_output,
            rebalance_weekday=None,
        ).run(strategy, panel, _config(panel, _binding("12")))
    assert signal.calls == 0
    assert panel.view_calls == 0
    assert not mismatch_output.exists()


def test_malformed_portfolio_strategy_constructor_surface_fails_closed(
    tmp_path: Path,
):
    panel = _Panel()
    strategy, signal = _strategy()
    strategy.constructor = object()  # type: ignore[assignment]
    output_dir = tmp_path / "malformed-constructor"

    with pytest.raises(ValueError, match="exact built-in Constructor"):
        DailyBookBacktester(
            output_dir=output_dir,
            rebalance_weekday=None,
        ).run(strategy, panel, _config(panel, _binding()))

    assert signal.calls == 0
    assert panel.view_calls == 0
    assert not output_dir.exists()


def test_portfolio_strategy_subclass_override_is_rejected_before_work(tmp_path: Path):
    panel = _Panel()
    base, signal = _strategy()
    strategy = _StrategySubclass(
        base.engines,
        base.combiner.weights,
        base.constructor.config,
    )
    output_dir = tmp_path / "strategy-subclass"

    with pytest.raises(ValueError, match="exact built-in PortfolioStrategy"):
        DailyBookBacktester(
            output_dir=output_dir,
            rebalance_weekday=None,
        ).run(strategy, panel, _config(panel, _binding()))

    assert signal.calls == 0
    assert panel.view_calls == 0
    assert not output_dir.exists()


def test_constructor_subclass_is_rejected_before_work(tmp_path: Path):
    panel = _Panel()
    strategy, signal = _strategy()
    strategy.constructor = _ConstructorSubclass(strategy.constructor.config)
    output_dir = tmp_path / "constructor-subclass"

    with pytest.raises(ValueError, match="exact built-in Constructor"):
        DailyBookBacktester(
            output_dir=output_dir,
            rebalance_weekday=None,
        ).run(strategy, panel, _config(panel, _binding()))

    assert signal.calls == 0
    assert panel.view_calls == 0
    assert not output_dir.exists()


def test_mid_compute_target_mutation_cannot_reach_bound_sizing(tmp_path: Path):
    baseline_panel = _Panel()
    baseline_strategy, _ = _strategy()
    baseline = DailyBookBacktester(
        output_dir=tmp_path / "baseline",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(
        baseline_strategy,
        baseline_panel,
        _config(baseline_panel, _binding()),
    )

    mutating_signal = _MutatingSignal()
    mutating_strategy = _strategy_with_signal(mutating_signal)
    mutating_signal.owner = mutating_strategy
    mutated_panel = _Panel()
    mutated = DailyBookBacktester(
        output_dir=tmp_path / "mutated",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(
        mutating_strategy,
        mutated_panel,
        _config(mutated_panel, _binding()),
    )

    assert mutating_signal.calls == len(mutated_panel.calendar) - 1
    assert mutating_strategy.constructor.config.vol_target_ann_pct == 1200.0
    assert mutated == baseline
    assert all(
        record["risk_policy_binding"][
            "effective_constructor_vol_target_ann_pct"
        ]
        == "12"
        for record in mutated.rebalance_records
    )


def test_mutation_and_restore_constructor_override_is_ignored_by_clone(
    tmp_path: Path,
):
    baseline_panel = _Panel()
    baseline_strategy, _ = _strategy()
    baseline = DailyBookBacktester(
        output_dir=tmp_path / "baseline-restore",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(
        baseline_strategy,
        baseline_panel,
        _config(baseline_panel, _binding()),
    )

    strategy, _ = _strategy()
    original_construct = strategy.constructor.construct
    override_calls = 0

    def mutating_construct(**kwargs):
        nonlocal override_calls
        override_calls += 1
        strategy.constructor.config.vol_target_ann_pct = 1200.0
        try:
            return original_construct(**kwargs)
        finally:
            strategy.constructor.config.vol_target_ann_pct = 12.0

    def overridden_rebalance(view, book):
        raise AssertionError("caller strategy override must not execute")

    strategy.constructor.construct = mutating_construct  # type: ignore[method-assign]
    strategy.rebalance = overridden_rebalance  # type: ignore[method-assign]
    panel = _Panel()
    result = DailyBookBacktester(
        output_dir=tmp_path / "mutation-restore",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(strategy, panel, _config(panel, _binding()))

    assert override_calls == 0
    assert strategy.constructor.config.vol_target_ann_pct == 12.0
    assert result == baseline


def test_success_binds_event_and_every_rebalance_record(tmp_path: Path):
    panel = _Panel()
    strategy, _ = _strategy()
    binding = _binding("12")
    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(strategy, panel, _config(panel, binding))

    expected = {
        "schema": "risk-policy-binding/v1",
        "policy_sha256": _POLICY_SHA,
        "effective_constructor_vol_target_ann_pct": "12",
    }
    assert result.events[0] == {
        "date": panel.calendar[0].isoformat(),
        "type": "risk_policy_bound",
        "detail": expected,
    }
    assert result.rebalance_records
    assert all(
        record["risk_policy_binding"] == expected
        for record in result.rebalance_records
    )
    assert json.loads((tmp_path / "events.jsonl").read_text().splitlines()[0]) == (
        result.events[0]
    )
    persisted_records = [
        json.loads(line)
        for line in (tmp_path / "rebalance_records.jsonl").read_text().splitlines()
    ]
    assert all(record["risk_policy_binding"] == expected for record in persisted_records)


def test_bound_run_is_repeatedly_deterministic(tmp_path: Path):
    first_strategy, _ = _strategy()
    second_strategy, _ = _strategy()
    first_panel = _Panel()
    second_panel = _Panel()
    first = DailyBookBacktester(
        output_dir=tmp_path / "first",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(first_strategy, first_panel, _config(first_panel, _binding()))
    second = DailyBookBacktester(
        output_dir=tmp_path / "second",
        slippage_bps=1.0,
        rebalance_weekday=None,
    ).run(second_strategy, second_panel, _config(second_panel, _binding()))

    assert first == second
    assert first.summary.determinism_hash == second.summary.determinism_hash
    for filename in (
        "equity_curve.csv",
        "trades.csv",
        "daily_returns.csv",
        "rebalance_records.jsonl",
        "events.jsonl",
        "summary.json",
    ):
        assert (tmp_path / "first" / filename).read_bytes() == (
            tmp_path / "second" / filename
        ).read_bytes()


@pytest.mark.parametrize(
    ("exact_decimal_target", "bound_target"),
    [
        (
            "0.12345678901234567890123456789",
            "0.12345678901234568",
        ),
        ("0.0000001", "0.0000001"),
    ],
)
def test_binding_matches_the_float_value_that_reaches_constructor(
    tmp_path: Path,
    exact_decimal_target: str,
    bound_target: str,
):
    constructor_float = float(exact_decimal_target)
    if bound_target == "0.0000001":
        assert str(constructor_float) == "1e-07"
    strategy, _ = _strategy(constructor_float)
    panel = _Panel()

    result = DailyBookBacktester(
        output_dir=tmp_path,
        rebalance_weekday=None,
    ).run(strategy, panel, _config(panel, _binding(bound_target)))

    assert result.events[0]["detail"][
        "effective_constructor_vol_target_ann_pct"
    ] == bound_target


def test_absent_binding_preserves_legacy_config_and_strategy_surface(tmp_path: Path):
    panel = _Panel()
    config = _config(panel)
    assert config.model_dump() == {
        "start": panel.calendar[0],
        "end": panel.calendar[-1],
        "initial_equity_rmb": 1_000_000.0,
        "panel_snapshot": panel.snapshot_version,
        "slippage_bps_by_instrument": {},
    }

    strategy = _StaticStrategy()
    result = DailyBookBacktester(
        output_dir=tmp_path,
        rebalance_weekday=None,
    ).run(strategy, panel, config)  # type: ignore[arg-type]

    assert strategy.calls == len(panel.calendar) - 1
    assert result.events == []
    assert result.rebalance_records
    assert all("risk_policy_binding" not in record for record in result.rebalance_records)
