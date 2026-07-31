"""Falsifiers for sealed nominal-cycle scheduling and strict book timing."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest
from pydantic import ValidationError

from echolon.backtest.book import (
    BookBacktestConfig,
    BookLifecycleContract,
    DailyBookBacktester,
    ExecutionContractSchedule,
    NominalCycleSchedule,
    create_nominal_cycle_schedule,
    load_nominal_cycle_schedule,
    write_nominal_cycle_schedule,
)
from echolon.backtest.book.schedule import canonical_schedule_sha256
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


_MANIFEST_SHA = "a" * 64
_AUTHORITY_SHA = "b" * 64
_ANCHOR = dt.date(2024, 1, 5)  # Friday; deliberately absent from authority.
_AUTHORITY = (
    dt.date(2024, 1, 4),
    dt.date(2024, 1, 8),
    dt.date(2024, 1, 9),
    dt.date(2024, 1, 10),
    dt.date(2024, 2, 2),
    dt.date(2024, 2, 5),
    dt.date(2024, 2, 6),
    dt.date(2024, 3, 1),
    dt.date(2024, 3, 4),
    dt.date(2024, 3, 5),
)


def _schedule(
    *,
    panel_dates: tuple[dt.date, ...] | None = None,
    nominal_end: dt.date = dt.date(2024, 2, 2),
    authority: tuple[dt.date, ...] = _AUTHORITY,
    coverage_end: dt.date | None = None,
) -> NominalCycleSchedule:
    union = panel_dates or _AUTHORITY[:7]
    return create_nominal_cycle_schedule(
        source_panel_snapshot="synthetic-panel-v1",
        source_panel_manifest_sha256=_MANIFEST_SHA,
        authoritative_calendar_id="synthetic-authority-calendar",
        authoritative_calendar_source_sha256=_AUTHORITY_SHA,
        authoritative_coverage_basis="observed_open_session_bounds_only",
        authoritative_sessions=authority,
        coverage_start=authority[0],
        coverage_end=coverage_end or authority[-1],
        panel_union_sessions=union,
        cadence_id="synthetic-28d-friday-v1",
        nominal_anchor=_ANCHOR,
        nominal_start=_ANCHOR,
        nominal_end=nominal_end,
    )


class _Panel:
    snapshot_version = "synthetic-panel-v1"
    manifest_sha256 = _MANIFEST_SHA
    instruments = ["asset"]

    def __init__(
        self,
        dates: tuple[dt.date, ...],
        *,
        contract_by_date: dict[dt.date, str] | None = None,
    ) -> None:
        self.calendar = list(dates)
        selected = contract_by_date or {date: "S1" for date in dates}
        self._bars = _bars([(date, "POISON_MAIN", 9_999.0) for date in dates])
        contract_rows: list[tuple[dt.date, str, float]] = []
        for index, date in enumerate(dates):
            contract_rows.append((date, "S1", 100.0 + index))
            contract_rows.append((date, "S2", 200.0 + index))
        self._contracts = _bars(contract_rows)
        self._selected = selected
        self._meta = InstrumentMeta(
            instrument_id="asset",
            sector="generic",
            multiplier=1.0,
            tick=1.0,
            margin_rate=0.1,
            commission=0.0,
            commission_type="per_contract",
            close_today_commission=0.0,
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
        contract = self._panel._selected[self.date]
        rows = self._panel._contracts.loc[
            self._panel._contracts["contract"] == contract
        ]
        return rows.loc[rows.index <= self.date].tail(lookback).copy()

    def current_bar(self, instrument: str):
        del instrument
        rows = self._panel._bars.loc[self._panel._bars.index == self.date]
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


class _TargetsByDecision:
    def __init__(self, targets: dict[dt.date, float]) -> None:
        self.targets = targets
        self.calls: list[dt.date] = []

    def rebalance(self, view: _View, book: BookState):
        del book
        self.calls.append(view.date)
        return (
            TargetBook(date=view.date, targets={"asset": self.targets[view.date]}),
            RebalanceRecord(date=view.date, instruments={}),
        )


def _bars(rows: list[tuple[dt.date, str, float]]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "settle": price,
                "volume": 1000,
                "open_interest": 5000,
                "contract": contract,
                "symbol": contract,
            }
            for _, contract, price in rows
        ],
        index=[date for date, _, _ in rows],
    )


def _config(
    schedule: NominalCycleSchedule,
    panel: _Panel,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    execution_schedule: ExecutionContractSchedule | None = None,
) -> BookBacktestConfig:
    return BookBacktestConfig(
        start=start or panel.calendar[0],
        end=end or panel.calendar[-1],
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
        panel_manifest_sha256=_MANIFEST_SHA,
        rebalance_mode="nominal_cycle_schedule",
        nominal_cycle_schedule=schedule,
        execution_contract_schedule=execution_schedule,
    )


def _run(
    tmp_path: Path,
    panel: _Panel,
    schedule: NominalCycleSchedule,
    strategy: _TargetsByDecision,
    *,
    start: dt.date | None = None,
    end: dt.date | None = None,
    execution_schedule: ExecutionContractSchedule | None = None,
):
    return DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=2,
        rebalance_interval_weeks=3,
    ).run(
        strategy,
        panel,
        _config(
            schedule,
            panel,
            start=start,
            end=end,
            execution_schedule=execution_schedule,
        ),
    )


def _execution_schedule(
    panel: _Panel,
    contract_by_date: dict[dt.date, str],
    *,
    non_executable_dates: frozenset[dt.date] = frozenset(),
) -> ExecutionContractSchedule:
    return ExecutionContractSchedule.create(
        source_panel_snapshot=panel.snapshot_version,
        source_panel_manifest_sha256=_MANIFEST_SHA,
        selection_rule="synthetic_prior_visible_contract",
        availability_assumption="synthetic_rows_visible_before_fill_open",
        instruments=("asset",),
        start=panel.calendar[0],
        end=panel.calendar[-1],
        rows=[
            (
                {
                    "fill_date": date,
                    "instrument": "asset",
                    "status": "no_eligible_prior_contract",
                    "contract": None,
                    "source_date": None,
                    "source_volume": None,
                    "source_open_interest": None,
                }
                if date in non_executable_dates
                else {
                    "fill_date": date,
                    "instrument": "asset",
                    "status": "executable",
                    "contract": contract_by_date[date],
                    "source_date": date - dt.timedelta(days=1),
                    "source_volume": "1000",
                    "source_open_interest": "5000",
                }
            )
            for date in panel.calendar
        ],
    )


def test_holiday_nominal_friday_resolves_once_to_monday_then_tuesday():
    schedule = _schedule()
    first = schedule.rows[0]
    assert first.nominal_date == dt.date(2024, 1, 5)
    assert first.decision_date == dt.date(2024, 1, 8)
    assert first.decision_status == "scheduled"
    assert first.catch_up_days == 3
    assert first.fill_date == dt.date(2024, 1, 9)
    assert first.fill_status == "scheduled"
    assert first.exit_fill_date == dt.date(2024, 2, 5)


def test_authority_open_panel_missing_is_explicit_and_never_catches_up():
    panel_dates = tuple(date for date in _AUTHORITY[:7] if date != dt.date(2024, 1, 8))
    schedule = _schedule(panel_dates=panel_dates)
    first = schedule.rows[0]
    assert first.decision_date == dt.date(2024, 1, 8)
    assert first.decision_status == "panel_data_missing"
    assert first.catch_up_days == 3
    assert first.fill_date is None
    assert first.fill_status == "no_decision"
    assert dt.date(2024, 1, 9) not in [
        row.decision_date for row in schedule.rows
    ]


def test_fill_candidate_missing_from_panel_is_retained_without_catch_up():
    panel_dates = tuple(date for date in _AUTHORITY[:7] if date != dt.date(2024, 1, 9))
    schedule = _schedule(panel_dates=panel_dates)
    first = schedule.rows[0]
    assert first.decision_status == "scheduled"
    assert first.fill_date == dt.date(2024, 1, 9)
    assert first.fill_status == "panel_data_missing"


def test_coverage_exhaustion_is_distinct_from_panel_missing():
    authority = _AUTHORITY[:7]
    schedule = _schedule(
        authority=authority,
        panel_dates=authority,
        coverage_end=authority[-1],
        nominal_end=dt.date(2024, 3, 1),
    )
    last = schedule.rows[-1]
    assert last.nominal_date == dt.date(2024, 3, 1)
    assert last.decision_date is None
    assert last.decision_status == "authority_coverage_missing"
    assert last.fill_status == "no_decision"


def test_absolute_anchor_is_v1_genesis_and_rejects_pre_anchor_cycles():
    with pytest.raises(ValidationError, match="must not precede.*nominal_anchor"):
        create_nominal_cycle_schedule(
            source_panel_snapshot="synthetic-panel-v1",
            source_panel_manifest_sha256=_MANIFEST_SHA,
            authoritative_calendar_id="synthetic-authority-calendar",
            authoritative_calendar_source_sha256=_AUTHORITY_SHA,
            authoritative_coverage_basis="observed_open_session_bounds_only",
            authoritative_sessions=_AUTHORITY,
            coverage_start=_AUTHORITY[0],
            coverage_end=_AUTHORITY[-1],
            panel_union_sessions=_AUTHORITY[:7],
            cadence_id="synthetic-28d-friday-v1",
            nominal_anchor=_ANCHOR,
            nominal_start=_ANCHOR - dt.timedelta(days=28),
            nominal_end=_ANCHOR,
        )


def test_long_authority_gap_rejects_colliding_scheduled_cycles():
    authority = (
        dt.date(2024, 1, 1),
        dt.date(2024, 3, 1),
        dt.date(2024, 3, 4),
    )
    with pytest.raises(ValidationError, match="duplicate scheduled decision date"):
        create_nominal_cycle_schedule(
            source_panel_snapshot="synthetic-panel-v1",
            source_panel_manifest_sha256=_MANIFEST_SHA,
            authoritative_calendar_id="synthetic-long-gap-calendar",
            authoritative_calendar_source_sha256=_AUTHORITY_SHA,
            authoritative_coverage_basis="observed_open_session_bounds_only",
            authoritative_sessions=authority,
            coverage_start=authority[0],
            coverage_end=authority[-1],
            panel_union_sessions=authority,
            cadence_id="synthetic-28d-friday-v1",
            nominal_anchor=_ANCHOR,
            nominal_start=_ANCHOR,
            nominal_end=dt.date(2024, 2, 2),
        )


def test_hash_round_trip_exclusive_writer_and_independent_recipe(tmp_path: Path):
    schedule = _schedule()
    payload = schedule.model_dump(mode="json")
    sealed_sha = payload.pop("sha256")
    assert sealed_sha == hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()

    destination = tmp_path / "nominal-cycle.json"
    assert write_nominal_cycle_schedule(destination, schedule) == destination.resolve()
    assert load_nominal_cycle_schedule(destination) == schedule
    with pytest.raises(FileExistsError):
        write_nominal_cycle_schedule(destination, schedule)


@pytest.mark.parametrize(
    "mutate,match",
    [
        (
            lambda payload: payload.update(
                authoritative_sessions_sha256="c" * 64
            ),
            "session-list hash mismatch",
        ),
        (
            lambda payload: payload.update(
                decision_rule="publisher_chosen_decision"
            ),
            "decision_rule",
        ),
        (
            lambda payload: payload["rows"][0].update(
                decision_date=dt.date(2024, 1, 9)
            ),
            "rows do not match recomputation",
        ),
    ],
)
def test_tampered_sessions_policy_or_rows_fail_even_with_recomputed_outer_hash(
    mutate, match
):
    payload = _schedule().model_dump(mode="python")
    payload.pop("sha256")
    mutate(payload)
    payload["sha256"] = canonical_schedule_sha256(payload)
    with pytest.raises(ValidationError, match=match):
        NominalCycleSchedule.model_validate(payload)


def test_future_append_preserves_closed_prefix_and_overlapping_cycle_ids():
    short = _schedule(nominal_end=dt.date(2024, 2, 2))
    extended = _schedule(
        panel_dates=_AUTHORITY,
        nominal_end=dt.date(2024, 3, 1),
    )
    assert short.rows[:-1] == extended.rows[: len(short.rows) - 1]
    assert [row.cycle_id for row in short.rows] == [
        row.cycle_id for row in extended.rows[: len(short.rows)]
    ]
    assert short.rows[-1].exit_fill_status == "no_next_cycle"
    assert extended.rows[len(short.rows) - 1].exit_fill_status == "scheduled"


def test_strict_mode_ignores_legacy_weekday_and_executes_on_declared_fill(
    tmp_path: Path,
):
    dates = _AUTHORITY[:7]
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    strategy = _TargetsByDecision(
        {dt.date(2024, 1, 8): 1.0, dt.date(2024, 2, 2): 2.0}
    )
    result = _run(tmp_path, panel, schedule, strategy)

    assert strategy.calls == [dt.date(2024, 1, 8), dt.date(2024, 2, 2)]
    assert [(trade.date, trade.lots) for trade in result.trades] == [
        (dt.date(2024, 1, 9), 1.0),
        (dt.date(2024, 2, 5), 1.0),
    ]
    record_cycle_ids = [
        record["nominal_cycle_schedule"]["cycle_id"]
        for record in result.rebalance_records
    ]
    assert record_cycle_ids == [
        schedule.rows[0].cycle_id,
        schedule.rows[1].cycle_id,
    ]
    assert all(
        record["nominal_cycle_schedule"]["sha256"] == schedule.sha256
        for record in result.rebalance_records
    )


def test_future_target_cannot_resize_intervening_roll_before_declared_fill(
    tmp_path: Path,
):
    dates = tuple(sorted((*_AUTHORITY[:7], dt.date(2024, 2, 3))))
    contract_by_date = {
        date: ("S2" if date >= dt.date(2024, 2, 3) else "S1") for date in dates
    }
    panel = _Panel(dates, contract_by_date=contract_by_date)
    nominal = _schedule(panel_dates=dates)
    contracts = _execution_schedule(panel, contract_by_date)
    strategy = _TargetsByDecision(
        {dt.date(2024, 1, 8): 1.0, dt.date(2024, 2, 2): 3.0}
    )

    result = _run(
        tmp_path,
        panel,
        nominal,
        strategy,
        execution_schedule=contracts,
    )

    roll_open = [
        trade
        for trade in result.trades
        if trade.date == dt.date(2024, 2, 3) and trade.contract == "S2"
    ]
    assert len(roll_open) == 1
    assert roll_open[0].lots == 1.0
    assert roll_open[0].position_after == 1.0
    fill = [trade for trade in result.trades if trade.date == dt.date(2024, 2, 5)]
    assert len(fill) == 1
    assert fill[0].lots == 2.0
    assert fill[0].position_after == 3.0


def test_non_executable_declared_fill_retries_after_fill_with_cycle_identity(
    tmp_path: Path,
):
    dates = _AUTHORITY[:7]
    contract_by_date = {date: "S1" for date in dates}
    panel = _Panel(dates, contract_by_date=contract_by_date)
    nominal = _schedule(panel_dates=dates)
    contracts = _execution_schedule(
        panel,
        contract_by_date,
        non_executable_dates=frozenset({dt.date(2024, 1, 9)}),
    )
    strategy = _TargetsByDecision({dt.date(2024, 1, 8): 1.0})

    result = _run(
        tmp_path,
        panel,
        nominal,
        strategy,
        end=dt.date(2024, 1, 10),
        execution_schedule=contracts,
    )

    assert [(trade.date, trade.lots) for trade in result.trades] == [
        (dt.date(2024, 1, 10), 1.0)
    ]
    deferred = [event for event in result.events if event["type"] == "target_deferred"]
    assert len(deferred) == 1
    assert deferred[0]["date"] == "2024-01-09"
    assert deferred[0]["detail"]["eligible_fill_date"] == "2024-01-09"
    assert deferred[0]["detail"]["cycle_id"] == nominal.rows[0].cycle_id
    assert deferred[0]["detail"]["nominal_cycle_schedule_sha256"] == nominal.sha256
    assert not [event for event in result.events if event["type"] == "target_unresolved_at_end"]


def test_panel_start_before_genesis_anchor_does_not_require_pre_anchor_row(
    tmp_path: Path,
):
    dates = _AUTHORITY[:7]
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    strategy = _TargetsByDecision(
        {dt.date(2024, 1, 8): 1.0, dt.date(2024, 2, 2): 1.0}
    )
    result = _run(tmp_path, panel, schedule, strategy)
    assert result.rebalance_records


def test_shifted_run_start_preserves_overlapping_cycle_identity(tmp_path: Path):
    dates = _AUTHORITY[:7]
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    full_strategy = _TargetsByDecision(
        {dt.date(2024, 1, 8): 1.0, dt.date(2024, 2, 2): 1.0}
    )
    shifted_strategy = _TargetsByDecision({dt.date(2024, 2, 2): 1.0})
    full = _run(tmp_path / "full", panel, schedule, full_strategy)
    shifted = _run(
        tmp_path / "shifted",
        panel,
        schedule,
        shifted_strategy,
        start=dt.date(2024, 1, 10),
    )
    assert shifted.rebalance_records[0]["nominal_cycle_schedule"] == (
        full.rebalance_records[1]["nominal_cycle_schedule"]
    )


def test_panel_missing_cycle_emits_skip_and_does_not_call_on_later_panel_date(
    tmp_path: Path,
):
    dates = tuple(date for date in _AUTHORITY[:7] if date != dt.date(2024, 1, 8))
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    strategy = _TargetsByDecision({dt.date(2024, 2, 2): 1.0})
    result = _run(tmp_path, panel, schedule, strategy)
    assert strategy.calls == [dt.date(2024, 2, 2)]
    skips = [event for event in result.events if event["type"] == "nominal_cycle_skipped"]
    assert skips[0]["date"] == "2024-01-08"
    assert skips[0]["detail"]["reason"] == "panel_data_missing"


def test_decision_with_fill_after_run_end_is_skipped_without_strategy_call(
    tmp_path: Path,
):
    dates = _AUTHORITY[:7]
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    strategy = _TargetsByDecision({dt.date(2024, 1, 8): 1.0})
    result = _run(
        tmp_path,
        panel,
        schedule,
        strategy,
        end=dt.date(2024, 2, 2),
    )
    assert strategy.calls == [dt.date(2024, 1, 8)]
    skips = [event for event in result.events if event["type"] == "nominal_cycle_skipped"]
    assert skips[-1]["detail"]["reason"] == "fill_outside_run_window"
    assert not [event for event in result.events if event["type"] == "target_unresolved_at_end"]


def test_model_copy_tampering_is_revalidated_before_output(tmp_path: Path):
    dates = _AUTHORITY[:7]
    panel = _Panel(dates)
    schedule = _schedule(panel_dates=dates)
    poisoned_row = schedule.rows[0].model_copy(
        update={"decision_date": dt.date(2024, 1, 9)}
    )
    poisoned = schedule.model_copy(update={"rows": (poisoned_row, *schedule.rows[1:])})
    with pytest.raises(ValidationError, match="rows do not match recomputation"):
        BookBacktestConfig(
            start=dates[0],
            end=dates[-1],
            initial_equity_rmb=1_000_000.0,
            panel_snapshot=panel.snapshot_version,
            panel_manifest_sha256=_MANIFEST_SHA,
            rebalance_mode="nominal_cycle_schedule",
            nominal_cycle_schedule=poisoned,
        )
    assert list(tmp_path.iterdir()) == []


def test_full_panel_calendar_and_manifest_are_bound_before_strategy(tmp_path: Path):
    dates = _AUTHORITY[:7]
    schedule = _schedule(panel_dates=dates)
    extra_date = dt.date(2024, 2, 7)
    panel = _Panel((*dates, extra_date))
    with pytest.raises(ValueError, match="full panel calendar"):
        _run(tmp_path / "calendar", panel, schedule, _TargetsByDecision({}))

    panel = _Panel(dates)
    panel.manifest_sha256 = "c" * 64
    with pytest.raises(ValueError, match="exposed manifest hash"):
        _run(tmp_path / "manifest", panel, schedule, _TargetsByDecision({}))

    panel.manifest_sha256 = _MANIFEST_SHA
    with pytest.raises(ValueError, match="exact panel union sessions"):
        _run(
            tmp_path / "endpoint",
            panel,
            schedule,
            _TargetsByDecision({}),
            start=_ANCHOR,
        )


def test_mode_mismatch_fails_and_legacy_dump_shape_is_unchanged():
    schedule = _schedule()
    with pytest.raises(ValidationError, match="requires nominal_cycle_schedule"):
        BookBacktestConfig(
            start=_AUTHORITY[0],
            end=_AUTHORITY[1],
            initial_equity_rmb=1.0,
            panel_snapshot="synthetic-panel-v1",
            rebalance_mode="nominal_cycle_schedule",
        )
    with pytest.raises(ValidationError, match="requires rebalance_mode"):
        BookBacktestConfig(
            start=_AUTHORITY[0],
            end=_AUTHORITY[1],
            initial_equity_rmb=1.0,
            panel_snapshot="synthetic-panel-v1",
            panel_manifest_sha256=_MANIFEST_SHA,
            nominal_cycle_schedule=schedule,
        )

    legacy = BookBacktestConfig(
        start=_AUTHORITY[0],
        end=_AUTHORITY[1],
        initial_equity_rmb=1.0,
        panel_snapshot="legacy-panel",
    )
    assert legacy.model_dump() == {
        "start": _AUTHORITY[0],
        "end": _AUTHORITY[1],
        "initial_equity_rmb": 1.0,
        "panel_snapshot": "legacy-panel",
        "slippage_bps_by_instrument": {},
    }


def test_strict_lifecycle_requires_every_complete_in_window_cycle(tmp_path: Path):
    dates = _AUTHORITY
    panel = _Panel(dates)
    schedule = _schedule(
        panel_dates=dates,
        nominal_end=dt.date(2024, 3, 1),
    )
    start = dates[0]
    end = dt.date(2024, 3, 4)
    strategy = _TargetsByDecision(
        {dt.date(2024, 1, 8): 1.0, dt.date(2024, 2, 2): 2.0}
    )
    execution_schedule = _execution_schedule(
        panel, {date: "S1" for date in dates}
    )

    complete_ids = (schedule.rows[0].cycle_id, schedule.rows[1].cycle_id)
    config = BookBacktestConfig(
        start=start,
        end=end,
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
        panel_manifest_sha256=_MANIFEST_SHA,
        rebalance_mode="nominal_cycle_schedule",
        nominal_cycle_schedule=schedule,
        execution_contract_schedule=execution_schedule,
        lifecycle_contract=BookLifecycleContract(
            expected_nominal_cycle_ids=complete_ids
        ),
    )
    result = DailyBookBacktester(
        output_dir=tmp_path / "complete",
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(strategy, panel, config)

    assert result.outcome.status == "VALID_COMPLETE"
    assert result.outcome.expected_nominal_cycle_ids == complete_ids
    assert result.outcome.executed_nominal_cycle_ids == complete_ids
    assert result.outcome.terminal_date == end
    assert strategy.calls == [dt.date(2024, 1, 8), dt.date(2024, 2, 2)]

    omitted = config.model_copy(
        update={
            "lifecycle_contract": BookLifecycleContract(
                expected_nominal_cycle_ids=(schedule.rows[0].cycle_id,)
            )
        }
    )
    with pytest.raises(ValueError, match="exactly equal all complete in-window cycles"):
        DailyBookBacktester(
            output_dir=tmp_path / "omitted",
            slippage_bps=0.0,
            rebalance_weekday=None,
        ).run(_TargetsByDecision({}), panel, omitted)
