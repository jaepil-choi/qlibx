"""TwoSleeveStrategy falsifiers: cadence, summation, capital split, guards."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import pytest

from echolon.panel.models import InstrumentMeta, PanelManifest
from echolon.panel.snapshot import PanelData
from echolon.portfolio import BookState, ConstructorConfig, PortfolioStrategy, TwoSleeveStrategy
from echolon.signals import ScoreVector, SignalEngine

N_DAYS = 120
START = dt.date(2024, 1, 1)


def _panel(drift_per_day: float = 0.001) -> PanelData:
    dates = [START + dt.timedelta(days=index) for index in range(N_DAYS)]
    specs = {"aa": 100.0, "bb": 200.0, "cc": 150.0}
    bars = {}
    for instrument, base in specs.items():
        settles = [base * (1.0 + drift_per_day * index) for index in range(N_DAYS)]
        bars[instrument] = pd.DataFrame(
            {
                "open": settles, "high": settles, "low": settles, "close": settles,
                "settle": settles,
                "open_raw": settles, "high_raw": settles, "low_raw": settles,
                "close_raw": settles, "settle_raw": settles,
                "open_adj": settles, "high_adj": settles, "low_adj": settles,
                "close_adj": settles, "settle_adj": settles,
                "adj_factor": [1.0] * N_DAYS,
                "volume": [1000] * N_DAYS,
                "open_interest": [5000.0] * N_DAYS,
                "contract": ["X1"] * N_DAYS,
            },
            index=dates,
        )
    meta = {
        instrument: InstrumentMeta(
            instrument_id=instrument, sector="metals", multiplier=10.0, tick=1.0,
            margin_rate=0.10, commission=3.0, commission_type="per_contract",
            close_today_commission=None, currency="RMB",
        )
        for instrument in specs
    }
    manifest = PanelManifest(
        schema="panel/v1", version="two_sleeve_test", created_at="2024-01-01T00:00:00+00:00",
        source_refs=["synthetic"], calendar_start=dates[0], calendar_end=dates[-1],
        instruments=list(specs), files={}, qc_report="qc_report.json", qc_status="PASS",
    )
    return PanelData(
        snapshot_dir=None, manifest=manifest, bars=bars, curves={}, contracts={}, meta=meta,
    )


class _StubSignal(SignalEngine):
    """Deterministic stub: score = fn(view.date, instrument), capped input."""

    def __init__(self, signal_id: str, fn) -> None:
        self.signal_id = signal_id
        self.family = "tsmom"
        self.params = {}
        self.data_requirements = {}
        self._fn = fn

    def compute(self, view) -> ScoreVector:
        scores = {
            instrument: self._fn(view.date, instrument)
            for instrument in view._panel.instruments
        }
        return ScoreVector(signal_id=self.signal_id, family=self.family, date=view.date, scores=scores)


def _cfg() -> ConstructorConfig:
    return ConstructorConfig(
        vol_target_ann_pct=12.0,
        sector_caps_pct={"metals": 1000.0},
        max_margin_utilization_pct=1000.0,
        min_abs_score_for_position=0.0,
        sizing_mode="research",
        rebalance_band_lots=0.0,
    )


def _slow_strategy(fn=None) -> PortfolioStrategy:
    fn = fn or (lambda date, inst: 1.0)
    return PortfolioStrategy([_StubSignal("slow_sig", fn)], {"slow_sig": 1.0}, _cfg())


def _fast_strategy(fn=None) -> PortfolioStrategy:
    fn = fn or (lambda date, inst: -1.0)
    return PortfolioStrategy([_StubSignal("fast_sig", fn)], {"fast_sig": 1.0}, _cfg())


def _book(date: dt.date) -> BookState:
    return BookState(date=date, equity_rmb=1_000_000.0, cash_rmb=1_000_000.0, margin_used_rmb=0.0)


def _weekly_dates(count: int) -> list[dt.date]:
    return [START + dt.timedelta(days=7 * index + 30) for index in range(count)]


def test_slow_targets_hold_between_refreshes_and_refresh_on_schedule():
    # Fast sleeve inert (score 0 -> no positions): combined == slow component.
    inert_fast = _fast_strategy(lambda date, inst: 0.0)
    # Slow signal flips its scores each call date, so a refresh is observable.
    slow = _slow_strategy(lambda date, inst: 1.0 if date.day % 2 else -1.0)
    strategy = TwoSleeveStrategy(
        slow=slow, fast=inert_fast,
        slow_capital_fraction=0.8, fast_capital_fraction=0.2,
        slow_interval_weeks=2,
    )
    panel = _panel()
    dates = _weekly_dates(3)

    targets = []
    held_flags = []
    for date in dates:
        target, record = strategy.rebalance(panel.view(date), _book(date))
        targets.append(target.targets)
        held_flags.append(
            any(cap.get("cap") == "slow_sleeve_held" for cap in record.instruments["aa"].caps_applied)
        )

    # Week 0: refresh; week 1: held (same targets despite moved prices/scores);
    # week 2: refresh again (2-week interval).
    assert held_flags == [False, True, False]
    assert targets[1] == pytest.approx(targets[0])
    assert targets[2] != pytest.approx(targets[0])


def test_combined_targets_are_sum_of_sleeve_targets_on_refresh():
    slow = _slow_strategy()
    fast = _fast_strategy()
    strategy = TwoSleeveStrategy(
        slow=slow, fast=fast,
        slow_capital_fraction=0.8, fast_capital_fraction=0.2,
        slow_interval_weeks=4,
    )
    panel = _panel()
    date = _weekly_dates(1)[0]
    view = panel.view(date)
    book = _book(date)

    combined, _ = strategy.rebalance(view, book)

    slow_alone, _ = _slow_strategy().rebalance(view, BookState(
        date=date, equity_rmb=800_000.0, cash_rmb=800_000.0, margin_used_rmb=0.0))
    fast_alone, _ = _fast_strategy().rebalance(view, BookState(
        date=date, equity_rmb=200_000.0, cash_rmb=200_000.0, margin_used_rmb=0.0))
    for instrument in combined.targets:
        assert combined.targets[instrument] == pytest.approx(
            slow_alone.targets[instrument] + fast_alone.targets[instrument]
        )
        # Long slow sleeve + short fast sleeve genuinely nets.
        assert slow_alone.targets[instrument] > 0 > fast_alone.targets[instrument]


def test_capital_fraction_scales_sleeve_sizing_linearly():
    panel = _panel()
    date = _weekly_dates(1)[0]
    view = panel.view(date)

    small = TwoSleeveStrategy(
        slow=_slow_strategy(lambda d, i: 0.0), fast=_fast_strategy(),
        slow_capital_fraction=0.5, fast_capital_fraction=0.2, slow_interval_weeks=4,
    )
    large = TwoSleeveStrategy(
        slow=_slow_strategy(lambda d, i: 0.0), fast=_fast_strategy(),
        slow_capital_fraction=0.5, fast_capital_fraction=0.4, slow_interval_weeks=4,
    )
    small_targets, _ = small.rebalance(view, _book(date))
    large_targets, _ = large.rebalance(view, _book(date))

    for instrument in small_targets.targets:
        assert large_targets.targets[instrument] == pytest.approx(
            2.0 * small_targets.targets[instrument], rel=1e-9
        )


def test_holiday_gap_delays_slow_refresh_instead_of_skipping_it():
    inert_fast = _fast_strategy(lambda date, inst: 0.0)
    slow = _slow_strategy(lambda date, inst: 1.0 if date.day % 2 else -1.0)
    strategy = TwoSleeveStrategy(
        slow=slow, fast=inert_fast,
        slow_capital_fraction=0.8, fast_capital_fraction=0.2,
        slow_interval_weeks=2,
    )
    panel = _panel()
    base = _weekly_dates(1)[0]
    # Week 0 refresh; week 1 held; week 2 skipped (holiday); week 3 call:
    # 21 days since refresh >= 14 -> MUST refresh (a modulo rule would hold).
    dates = [base, base + dt.timedelta(days=7), base + dt.timedelta(days=21)]
    held = []
    for date in dates:
        _, record = strategy.rebalance(panel.view(date), _book(date))
        held.append(
            any(cap.get("cap") == "slow_sleeve_held" for cap in record.instruments["aa"].caps_applied)
        )
    assert held == [False, True, False]


def test_fast_sleeve_bands_against_its_own_last_targets():
    # Falling prices make same-direction lot targets GROW week over week (the
    # band deliberately never blocks reductions); a huge band must hold the
    # fast sleeve at its own prior targets — impossible unless the sleeve
    # sees them as book positions.
    panel = _panel(drift_per_day=-0.001)
    banded_cfg = _cfg().model_copy(update={"rebalance_band_lots": 10_000.0})
    fast = PortfolioStrategy([_StubSignal("fast_sig", lambda d, i: -1.0)], {"fast_sig": 1.0}, banded_cfg)
    strategy = TwoSleeveStrategy(
        slow=_slow_strategy(lambda d, i: 0.0), fast=fast,
        slow_capital_fraction=0.5, fast_capital_fraction=0.5,
        slow_interval_weeks=4,
    )
    dates = _weekly_dates(2)

    first, _ = strategy.rebalance(panel.view(dates[0]), _book(dates[0]))
    second, record = strategy.rebalance(panel.view(dates[1]), _book(dates[1]))

    assert second.targets == pytest.approx(first.targets)
    assert any(
        cap.get("cap") == "rebalance_band_lots"
        for cap in record.instruments["aa"].caps_applied
    )


def test_guards_reject_bad_composition():
    with pytest.raises(ValueError, match="share signal ids"):
        TwoSleeveStrategy(
            slow=_slow_strategy(), fast=PortfolioStrategy(
                [_StubSignal("slow_sig", lambda d, i: 0.0)], {"slow_sig": 1.0}, _cfg()),
            slow_capital_fraction=0.8, fast_capital_fraction=0.2,
        )
    with pytest.raises(ValueError, match="exceed 1.0"):
        TwoSleeveStrategy(
            slow=_slow_strategy(), fast=_fast_strategy(),
            slow_capital_fraction=0.9, fast_capital_fraction=0.2,
        )
    with pytest.raises(ValueError, match="positive"):
        TwoSleeveStrategy(
            slow=_slow_strategy(), fast=_fast_strategy(),
            slow_capital_fraction=0.0, fast_capital_fraction=0.2,
        )
    with pytest.raises(ValueError, match=">= 1"):
        TwoSleeveStrategy(
            slow=_slow_strategy(), fast=_fast_strategy(),
            slow_capital_fraction=0.8, fast_capital_fraction=0.2, slow_interval_weeks=0,
        )


def test_slow_only_mode_runs_baseline_through_the_same_cadence_rule():
    # fast=None: the certification baseline path — identical elapsed-time rule,
    # combined targets equal the slow sleeve alone.
    strategy = TwoSleeveStrategy(
        slow=_slow_strategy(), fast=None,
        slow_capital_fraction=1.0, fast_capital_fraction=0.0,
        slow_interval_weeks=4,
    )
    panel = _panel()
    date = _weekly_dates(1)[0]

    combined, record = strategy.rebalance(panel.view(date), _book(date))

    slow_alone, _ = _slow_strategy().rebalance(panel.view(date), _book(date))
    assert combined.targets == pytest.approx(slow_alone.targets)
    assert "slow_sig" in record.instruments["aa"].raw_scores
    with pytest.raises(ValueError, match="must be 0.0 when fast is None"):
        TwoSleeveStrategy(
            slow=_slow_strategy(), fast=None,
            slow_capital_fraction=0.8, fast_capital_fraction=0.2,
        )


def test_reset_makes_instance_reuse_equal_fresh_instance():
    # Review M2 falsifier: without reset, a reused instance seeds the second
    # window's band with the first window's held lots; reset() must restore
    # fresh-instance behavior exactly.
    panel = _panel(drift_per_day=-0.001)
    banded_cfg = _cfg().model_copy(update={"rebalance_band_lots": 10_000.0})

    def build():
        return TwoSleeveStrategy(
            slow=PortfolioStrategy(
                [_StubSignal("slow_sig", lambda d, i: 1.0)], {"slow_sig": 1.0}, banded_cfg),
            fast=PortfolioStrategy(
                [_StubSignal("fast_sig", lambda d, i: -1.0)], {"fast_sig": 1.0}, banded_cfg),
            slow_capital_fraction=0.8, fast_capital_fraction=0.2,
            slow_interval_weeks=2,
        )

    window_a = _weekly_dates(2)
    window_b = [date + dt.timedelta(days=21) for date in window_a]

    reused = build()
    for date in window_a:
        reused.rebalance(panel.view(date), _book(date))
    dirty_targets, _ = reused.rebalance(panel.view(window_b[0]), _book(window_b[0]))

    reused.reset()
    reset_targets, _ = reused.rebalance(panel.view(window_b[0]), _book(window_b[0]))
    fresh_targets, _ = build().rebalance(panel.view(window_b[0]), _book(window_b[0]))

    assert reset_targets.targets == pytest.approx(fresh_targets.targets)
    # And the falsifier half: the un-reset instance really was contaminated
    # (band held it at window A's lots on falling prices).
    assert dirty_targets.targets != pytest.approx(fresh_targets.targets)


def test_engine_run_is_deterministic_with_two_sleeve_strategy():
    from echolon.backtest.book import BookBacktestConfig, DailyBookBacktester

    panel = _panel()
    config = BookBacktestConfig(
        start=START + dt.timedelta(days=30),
        end=START + dt.timedelta(days=110),
        initial_equity_rmb=1_000_000.0,
        panel_snapshot="two_sleeve_test",
    )

    def run(output_dir):
        strategy = TwoSleeveStrategy(
            slow=_slow_strategy(), fast=_fast_strategy(),
            slow_capital_fraction=0.8, fast_capital_fraction=0.2,
            slow_interval_weeks=4,
        )
        backtester = DailyBookBacktester(
            output_dir=output_dir, rebalance_weekday=4, rebalance_interval_weeks=1,
        )
        return backtester.run(strategy, panel, config)

    import tempfile

    with tempfile.TemporaryDirectory() as tmp_a, tempfile.TemporaryDirectory() as tmp_b:
        first = run(tmp_a)
        second = run(tmp_b)

    assert first.summary.determinism_hash == second.summary.determinism_hash
    assert first.summary.n_trades > 0
