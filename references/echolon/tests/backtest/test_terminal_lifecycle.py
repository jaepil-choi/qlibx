"""Falsifiers for strict terminal reconciliation and liquidation lifecycle."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

import pandas as pd
import pytest

from echolon.backtest.book import (
    BookBacktestConfig,
    BookLifecycleContract,
    DailyBookBacktester,
    full_result_manifest_sha256,
    verify_full_result_manifest_sha256,
)
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


class _Panel:
    snapshot_version = "strict-lifecycle-synthetic"

    def __init__(
        self,
        *,
        dates: tuple[dt.date, ...],
        prices: tuple[float, ...],
        current_contracts: tuple[str, ...] | None = None,
        exact_rows: dict[dt.date, tuple[str, ...]] | None = None,
        suspended: frozenset[dt.date] = frozenset(),
        commission: float = 1.0,
        multiplier: float = 1.0,
        tick: float = 1.0,
        margin_rate: float = 0.1,
    ) -> None:
        self.instruments = ["asset"]
        self.calendar = list(dates)
        contracts = current_contracts or tuple("A1" for _ in dates)
        self._main = _bars(dates, prices, contracts)
        rows: list[pd.DataFrame] = []
        for date, price, current in zip(dates, prices, contracts):
            for contract in (exact_rows or {}).get(date, (current,)):
                row = _bars((date,), (price,), (contract,))
                if date in suspended:
                    row["suspended"] = 1.0
                rows.append(row)
        self._contracts = pd.concat(rows) if rows else self._main.iloc[0:0].copy()
        self._meta = InstrumentMeta(
            instrument_id="asset",
            sector="generic",
            multiplier=multiplier,
            tick=tick,
            margin_rate=margin_rate,
            commission=commission,
            commission_type="per_contract",
            close_today_commission=commission,
            currency="RMB",
        )

    def view(self, date: dt.date) -> "_View":
        return _View(self, date)


class _View:
    def __init__(self, panel: _Panel, date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        del instrument
        return self._panel._main.loc[self._panel._main.index <= self.date].tail(
            lookback
        )

    def current_bar(self, instrument: str):
        del instrument
        rows = self._panel._main.loc[self._panel._main.index == self.date]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        del instrument
        rows = self._panel._contracts.loc[
            (self._panel._contracts.index == self.date)
            & (self._panel._contracts["contract"] == contract)
        ]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        del instrument
        rows = self._panel._contracts.loc[
            (self._panel._contracts.index <= self.date)
            & (self._panel._contracts["contract"] == contract)
        ]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        assert instrument == "asset"
        return self._panel._meta


class _Strategy:
    def __init__(self, lots: float) -> None:
        self.lots = lots
        self.calls: list[dt.date] = []

    def rebalance(self, view: _View, book: BookState):
        del book
        self.calls.append(view.date)
        return (
            TargetBook(date=view.date, targets={"asset": self.lots}),
            RebalanceRecord(date=view.date, instruments={}),
        )


class _MultiPanel:
    snapshot_version = "strict-lifecycle-multi-synthetic"

    def __init__(
        self,
        *,
        dates: tuple[dt.date, ...],
        prices: dict[str, tuple[float, ...]],
        missing: frozenset[tuple[str, dt.date]] = frozenset(),
        suspended: frozenset[tuple[str, dt.date]] = frozenset(),
        commission: float = 1.0,
        multiplier: float = 1.0,
        margin_rate: float = 0.1,
    ) -> None:
        self.instruments = sorted(prices)
        self.calendar = list(dates)
        self._missing = missing
        self._bars: dict[str, pd.DataFrame] = {}
        self._contracts: dict[str, pd.DataFrame] = {}
        self._meta: dict[str, InstrumentMeta] = {}
        for instrument in self.instruments:
            contract = f"{instrument}-1"
            main = _bars(dates, prices[instrument], tuple(contract for _ in dates))
            self._bars[instrument] = main
            exact = main.loc[
                [
                    (instrument, date) not in missing
                    for date in main.index
                ]
            ].copy()
            for date in dates:
                if (instrument, date) in suspended and date in exact.index:
                    exact.loc[date, "suspended"] = 1.0
            self._contracts[instrument] = exact
            self._meta[instrument] = InstrumentMeta(
                instrument_id=instrument,
                sector="generic",
                multiplier=multiplier,
                tick=1.0,
                margin_rate=margin_rate,
                commission=commission,
                commission_type="per_contract",
                close_today_commission=commission,
                currency="RMB",
            )

    def view(self, date: dt.date) -> "_MultiView":
        return _MultiView(self, date)


class _MultiView:
    def __init__(self, panel: _MultiPanel, date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        return self._panel._bars[instrument].loc[
            self._panel._bars[instrument].index <= self.date
        ].tail(lookback)

    def current_bar(self, instrument: str):
        if (instrument, self.date) in self._panel._missing:
            return None
        rows = self._panel._bars[instrument].loc[
            self._panel._bars[instrument].index == self.date
        ]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        rows = self._panel._contracts[instrument].loc[
            (self._panel._contracts[instrument].index == self.date)
            & (self._panel._contracts[instrument]["contract"] == contract)
        ]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        rows = self._panel._contracts[instrument].loc[
            (self._panel._contracts[instrument].index <= self.date)
            & (self._panel._contracts[instrument]["contract"] == contract)
        ]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._panel._meta[instrument]


class _MultiStrategy:
    def __init__(self, targets: dict[dt.date, dict[str, float]]) -> None:
        self.targets = targets
        self.calls: list[dt.date] = []

    def rebalance(self, view: _MultiView, book: BookState):
        del book
        self.calls.append(view.date)
        return (
            TargetBook(date=view.date, targets=self.targets.get(view.date, {})),
            RebalanceRecord(date=view.date, instruments={}),
        )


def _bars(
    dates: tuple[dt.date, ...],
    prices: tuple[float, ...],
    contracts: tuple[str, ...],
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": prices,
            "high": prices,
            "low": prices,
            "close": prices,
            "settle": prices,
            "volume": [1000] * len(dates),
            "open_interest": [5000] * len(dates),
            "contract": contracts,
            "symbol": contracts,
        },
        index=dates,
    )


def _strict_run(
    tmp_path: Path,
    panel: _Panel,
    strategy: _Strategy,
    *,
    initial_equity: float,
    slippage_bps: float = 0.0,
    commission_multiplier: float = 1.0,
):
    return DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=slippage_bps,
        rebalance_weekday=None,
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=panel.calendar[0],
            end=panel.calendar[-1],
            initial_equity_rmb=initial_equity,
            panel_snapshot=panel.snapshot_version,
            commission_multiplier=commission_multiplier,
            lifecycle_contract=BookLifecycleContract(
                terminal_open_date=panel.calendar[-1]
            ),
        ),
    )


@pytest.mark.parametrize(
    (
        "initial_equity",
        "prices",
        "lots",
        "commission",
        "multiplier",
        "tick",
        "slippage_bps",
        "expected_cash",
    ),
    [
        (10_000.0, (100.0, 100.0, 100.0, 100.0), 100.0, 17.5, 1.0, 1.0, 0.0, 6_500.0),
        (1_000.0, (100.0, 100.0, 90.0, 90.0), 1.0, 106.0, 10.0, 1.0, 0.0, 688.0),
        (1_000.0, (100.0, 100.0, 100.0, 100.0), 1.0, 170.0, 10.0, 1.0, 1.0, 640.0),
    ],
)
def test_liquidation_cash_oracles_use_real_close_path(
    tmp_path: Path,
    initial_equity: float,
    prices: tuple[float, ...],
    lots: float,
    commission: float,
    multiplier: float,
    tick: float,
    slippage_bps: float,
    expected_cash: float,
):
    dates = tuple(dt.date(2025, 1, 6) + dt.timedelta(days=i) for i in range(4))
    panel = _Panel(
        dates=dates,
        prices=prices,
        commission=commission,
        multiplier=multiplier,
        tick=tick,
        margin_rate=10.0,
    )
    strategy = _Strategy(lots)

    result = _strict_run(
        tmp_path,
        panel,
        strategy,
        initial_equity=initial_equity,
        slippage_bps=slippage_bps,
    )

    assert result.outcome.status == "LIQUIDATED_HALT"
    assert result.outcome.ending_cash_rmb == expected_cash
    assert [trade.date for trade in result.trades] == [dates[1], dates[2]]
    assert strategy.calls == [dates[0]]


def test_liquidation_retries_exact_held_contract_and_freezes_strategy(tmp_path: Path):
    dates = tuple(dt.date(2025, 2, 3) + dt.timedelta(days=i) for i in range(5))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 5,
        current_contracts=("A1", "A1", "B1", "B1", "B1"),
        exact_rows={
            dates[0]: ("A1",),
            dates[1]: ("A1",),
            dates[2]: ("B1",),
            dates[3]: ("A1", "B1"),
            dates[4]: ("B1",),
        },
        commission=17.5,
        margin_rate=1.0,
    )
    strategy = _Strategy(100.0)

    result = _strict_run(tmp_path, panel, strategy, initial_equity=10_000.0)

    assert result.outcome.status == "LIQUIDATED_HALT"
    assert [(trade.date, trade.contract) for trade in result.trades] == [
        (dates[1], "A1"),
        (dates[3], "A1"),
    ]
    assert strategy.calls == [dates[0]]
    assert any(
        event["date"] == dates[2].isoformat()
        and event["type"] == "liquidation_close_deferred"
        and event["detail"]["reason"] == "missing_exact_held_contract_bar"
        for event in result.events
    )


def test_partial_liquidation_retains_suspended_position_then_retries(tmp_path: Path):
    dates = tuple(dt.date(2025, 2, 10) + dt.timedelta(days=i) for i in range(5))
    panel = _MultiPanel(
        dates=dates,
        prices={"asset": (100.0,) * 5, "peer": (100.0,) * 5},
        suspended=frozenset({("peer", dates[2])}),
        commission=1.0,
        margin_rate=10.0,
    )
    strategy = _MultiStrategy({dates[0]: {"asset": 1.0, "peer": 1.0}})
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1],
            initial_equity_rmb=1_000.0,
            panel_snapshot=panel.snapshot_version,
            lifecycle_contract=BookLifecycleContract(terminal_open_date=dates[-1]),
        ),
    )

    assert result.outcome.status == "LIQUIDATED_HALT"
    assert [(trade.instrument, trade.date) for trade in result.trades] == [
        ("asset", dates[1]),
        ("peer", dates[1]),
        ("asset", dates[2]),
        ("peer", dates[3]),
    ]
    retry_point = next(row for row in result.equity_curve if row.date == dates[2])
    assert retry_point.cash_rmb == 997.0
    assert retry_point.margin_used_rmb == 1_000.0
    assert any(
        event["type"] == "liquidation_close_deferred"
        and event["detail"]["instrument"] == "peer"
        and event["detail"]["reason"] == "suspended"
        for event in result.events
    )
    assert strategy.calls == [dates[0]]


def test_flat_insolvency_cancels_deferred_normal_intent(tmp_path: Path):
    dates = tuple(dt.date(2025, 2, 17) + dt.timedelta(days=i) for i in range(4))
    panel = _MultiPanel(
        dates=dates,
        prices={
            "asset": (100.0, 100.0, 80.0, 80.0),
            "peer": (100.0,) * 4,
        },
        missing=frozenset({("peer", dates[2])}),
        commission=50.0,
        multiplier=10.0,
        margin_rate=0.01,
    )
    strategy = _MultiStrategy(
        {
            dates[0]: {"asset": 1.0},
            dates[1]: {"asset": 0.0, "peer": 1.0},
        }
    )
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1],
            initial_equity_rmb=200.0,
            panel_snapshot=panel.snapshot_version,
            lifecycle_contract=BookLifecycleContract(terminal_open_date=dates[-1]),
        ),
    )

    assert result.outcome.status == "INSOLVENT_HALT"
    assert result.outcome.ending_cash_rmb == -100.0
    assert not result.outcome.ending_positions
    assert not result.outcome.ending_pending_intents
    assert any(
        event["type"] == "target_cancelled"
        and event["detail"]["instrument"] == "peer"
        and event["detail"]["reason"] == "insolvent_halt"
        for event in result.events
    )


def test_last_day_breach_is_blocked_not_fake_completion(tmp_path: Path):
    dates = tuple(dt.date(2025, 3, 3) + dt.timedelta(days=i) for i in range(2))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 2,
        commission=17.5,
        margin_rate=1.0,
    )
    strategy = _Strategy(100.0)
    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(
        strategy,
        panel,
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1] + dt.timedelta(days=1),
            initial_equity_rmb=10_000.0,
            panel_snapshot=panel.snapshot_version,
            lifecycle_contract=BookLifecycleContract(
                terminal_open_date=dates[-1] + dt.timedelta(days=1)
            ),
        ),
    )
    assert result.outcome.status == "LIQUIDATION_BLOCKED_HALT"
    assert result.outcome.liquidation_trigger_date == dates[-1]
    assert result.outcome.liquidation_completion_date is None
    assert len(result.trades) == 1


def test_liquidation_fill_can_end_insolvent(tmp_path: Path):
    dates = tuple(dt.date(2025, 4, 7) + dt.timedelta(days=i) for i in range(4))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 4,
        commission=120.0,
        margin_rate=10.0,
    )
    result = _strict_run(tmp_path, panel, _Strategy(1.0), initial_equity=200.0)
    assert result.outcome.status == "INSOLVENT_HALT"
    assert result.outcome.ending_cash_rmb == -40.0


def test_terminal_exact_open_flatten_is_valid_and_costed(tmp_path: Path):
    dates = tuple(dt.date(2025, 5, 5) + dt.timedelta(days=i) for i in range(3))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 3,
        commission=2.0,
        margin_rate=0.1,
    )
    result = _strict_run(tmp_path, panel, _Strategy(1.0), initial_equity=1_100.0)
    assert result.outcome.status == "VALID_COMPLETE"
    assert result.outcome.ending_cash_rmb == 1_096.0
    assert [(trade.date, trade.position_after) for trade in result.trades] == [
        (dates[1], 1.0),
        (dates[2], 0.0),
    ]


def test_terminal_exact_close_helper_uses_stressed_commission(tmp_path: Path):
    dates = tuple(dt.date(2025, 5, 12) + dt.timedelta(days=i) for i in range(3))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 3,
        commission=2.0,
        margin_rate=0.1,
    )
    result = _strict_run(
        tmp_path,
        panel,
        _Strategy(1.0),
        initial_equity=1_100.0,
        commission_multiplier=3.0,
    )

    assert result.outcome.status == "VALID_COMPLETE"
    assert result.outcome.ending_cash_rmb == 1_088.0
    assert [trade.commission_rmb for trade in result.trades] == [6.0, 6.0]
    assert result.trades[-1].position_after == 0.0


def test_blocked_terminal_close_is_invalid_and_replayable(tmp_path: Path):
    dates = tuple(dt.date(2025, 6, 2) + dt.timedelta(days=i) for i in range(3))
    panel = _Panel(
        dates=dates,
        prices=(100.0,) * 3,
        exact_rows={dates[0]: ("A1",), dates[1]: ("A1",), dates[2]: ()},
        commission=2.0,
        margin_rate=0.1,
    )
    first = _strict_run(tmp_path / "first", panel, _Strategy(1.0), initial_equity=1_100.0)
    second = _strict_run(tmp_path / "second", panel, _Strategy(1.0), initial_equity=1_100.0)

    assert first.outcome.status == "INVALID_INCOMPLETE"
    assert first.outcome.ending_positions[0].contract == "A1"
    assert first.summary.determinism_hash == second.summary.determinism_hash
    assert first.summary.full_result_manifest_sha256 == full_result_manifest_sha256(first)
    assert verify_full_result_manifest_sha256(first)
    tampered = first.model_copy(update={"events": [*first.events, {"type": "tampered"}]})
    assert not verify_full_result_manifest_sha256(tampered)
    runtime_tampered = first.model_copy(
        update={
            "runtime_manifest": first.runtime_manifest.model_copy(
                update={"slippage_bps": 99.0}
            )
        }
    )
    assert not verify_full_result_manifest_sha256(runtime_tampered)
    config_payload = dict(first.runtime_manifest.config)
    config_payload["panel_snapshot"] = "tampered"
    config_tampered = first.model_copy(
        update={
            "runtime_manifest": first.runtime_manifest.model_copy(
                update={"config": config_payload}
            )
        }
    )
    assert not verify_full_result_manifest_sha256(config_tampered)
    trade_tampered = first.model_copy(
        update={
            "trades": [
                first.trades[0].model_copy(update={"commission_rmb": 999.0}),
                *first.trades[1:],
            ]
        }
    )
    assert not verify_full_result_manifest_sha256(trade_tampered)
    record_tampered = first.model_copy(
        update={"rebalance_records": [*first.rebalance_records, {"tampered": True}]}
    )
    assert not verify_full_result_manifest_sha256(record_tampered)
    outcome_tampered = first.model_copy(
        update={
            "outcome": first.outcome.model_copy(
                update={"terminal_reason": "tampered"}
            )
        }
    )
    assert not verify_full_result_manifest_sha256(outcome_tampered)


def test_default_path_is_explicitly_legacy_uncertified(tmp_path: Path):
    dates = tuple(dt.date(2025, 7, 7) + dt.timedelta(days=i) for i in range(3))
    panel = _Panel(dates=dates, prices=(100.0,) * 3)
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        _Strategy(1.0),
        panel,
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1],
            initial_equity_rmb=1_100.0,
            panel_snapshot=panel.snapshot_version,
        ),
    )
    assert result.outcome.status == "LEGACY_UNCERTIFIED"
    assert (tmp_path / "outcome.json").is_file()
    assert (tmp_path / "book_result.json").is_file()
