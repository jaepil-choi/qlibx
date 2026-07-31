"""Falsifiers for sealed prior-session execution-contract schedules."""
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
    DailyBookBacktester,
    ExecutionContractSchedule,
    ExecutionContractScheduleRow,
    load_execution_contract_schedule,
    write_execution_contract_schedule,
)
from echolon.panel.models import InstrumentMeta
from echolon.portfolio import BookState, RebalanceRecord, TargetBook


_MANIFEST_SHA = "a" * 64


class _SchedulePanel:
    snapshot_version = "synthetic-panel-v1"

    def __init__(
        self,
        *,
        dates: list[dt.date] | None = None,
        instruments: tuple[str, ...] = ("first",),
        main_contract: str = "POISON_MAIN",
        main_price: float = 9_999.0,
        contract_rows: dict[str, list[tuple[dt.date, str, float]]] | None = None,
    ) -> None:
        self.calendar = dates or [
            dt.date(2024, 1, 2) + dt.timedelta(days=index) for index in range(4)
        ]
        self.instruments = list(instruments)
        self.current_bar_calls = 0
        self._bars = {
            instrument: _bars(
                [(date, main_contract, main_price) for date in self.calendar]
            )
            for instrument in instruments
        }
        rows_by_instrument = contract_rows or {
            instrument: [(date, "S1", 100.0) for date in self.calendar]
            for instrument in instruments
        }
        self._contracts = {
            instrument: _contract_bars(rows_by_instrument[instrument])
            for instrument in instruments
        }
        self._meta = {
            instrument: InstrumentMeta(
                instrument_id=instrument,
                sector="generic",
                multiplier=1.0,
                tick=1.0,
                margin_rate=0.1,
                commission=0.0,
                commission_type="per_contract",
                close_today_commission=0.0,
                currency="RMB",
            )
            for instrument in instruments
        }

    def view(self, date: dt.date) -> "_ScheduleView":
        return _ScheduleView(self, date)


class _ScheduleView:
    def __init__(self, panel: _SchedulePanel, date: dt.date) -> None:
        self._panel = panel
        self.date = date

    def bars(self, instrument: str, lookback: int) -> pd.DataFrame:
        frame = self._panel._bars[instrument]
        return frame.loc[frame.index <= self.date].tail(lookback).copy()

    def current_bar(self, instrument: str):
        self._panel.current_bar_calls += 1
        rows = self._panel._bars[instrument].loc[
            self._panel._bars[instrument].index == self.date
        ]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar(self, instrument: str, contract: str):
        rows = self._panel._contracts[instrument]
        rows = rows.loc[rows.index == self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[0].copy()

    def contract_bar_asof(self, instrument: str, contract: str):
        rows = self._panel._contracts[instrument]
        rows = rows.loc[rows.index <= self.date]
        rows = rows[rows["contract"].astype(str) == str(contract)]
        return None if rows.empty else rows.iloc[-1].copy()

    def meta(self, instrument: str) -> InstrumentMeta:
        return self._panel._meta[instrument]


class _StaticTargets:
    def __init__(self, targets: dict[str, float]) -> None:
        self.targets = targets
        self.calls = 0

    def rebalance(self, view, book: BookState):
        self.calls += 1
        return (
            TargetBook(date=view.date, targets=self.targets),
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
            }
            for _, contract, price in rows
        ],
        index=[date for date, _, _ in rows],
    )


def _contract_bars(rows: list[tuple[dt.date, str, float]]) -> pd.DataFrame:
    frame = _bars(rows)
    return frame.assign(symbol=frame["contract"])


def _row(
    fill_date: dt.date,
    instrument: str,
    *,
    status: str = "executable",
    contract: str | None = "S1",
    source_date: dt.date | None = None,
) -> dict:
    if source_date is None and status == "executable":
        source_date = fill_date - dt.timedelta(days=1)
    return {
        "fill_date": fill_date,
        "instrument": instrument,
        "status": status,
        "contract": contract,
        "source_date": source_date,
        "source_volume": "1000" if status == "executable" else None,
        "source_open_interest": "5000" if status == "executable" else None,
    }


def _schedule(
    panel: _SchedulePanel,
    *,
    instruments: tuple[str, ...] | None = None,
    rows: list[dict] | None = None,
    manifest_sha256: str = _MANIFEST_SHA,
) -> ExecutionContractSchedule:
    declared = instruments or tuple(panel.instruments)
    payload_rows = rows or [
        _row(date, instrument)
        for date in panel.calendar
        for instrument in declared
    ]
    return ExecutionContractSchedule.create(
        source_panel_snapshot=panel.snapshot_version,
        source_panel_manifest_sha256=manifest_sha256,
        selection_rule="prior_visible_contract_rule",
        availability_assumption="source_rows_visible_before_fill_open",
        instruments=declared,
        start=panel.calendar[0],
        end=panel.calendar[-1],
        rows=payload_rows,
    )


def _config(
    panel: _SchedulePanel,
    schedule: ExecutionContractSchedule,
    *,
    manifest_sha256: str = _MANIFEST_SHA,
) -> BookBacktestConfig:
    return BookBacktestConfig(
        start=panel.calendar[0],
        end=panel.calendar[-1],
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
        panel_manifest_sha256=manifest_sha256,
        execution_contract_schedule=schedule,
    )


def _run(
    tmp_path: Path,
    panel: _SchedulePanel,
    schedule: ExecutionContractSchedule,
    targets: dict[str, float] | None = None,
):
    strategy = _StaticTargets(targets or {"first": 1.0})
    result = DailyBookBacktester(
        output_dir=tmp_path,
        slippage_bps=0.0,
        rebalance_weekday=None,
    ).run(strategy, panel, _config(panel, schedule))
    return result, strategy


def test_schedule_hash_is_canonical_and_round_trips_exclusively(tmp_path: Path):
    panel = _SchedulePanel()
    schedule = _schedule(panel)
    payload = schedule.model_dump(mode="json")
    sealed_sha = payload.pop("sha256")
    independent_sha = hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()
    assert sealed_sha == independent_sha
    assert schedule.rows[0].source_volume == "1000"

    destination = tmp_path / "schedule.json"
    written = write_execution_contract_schedule(destination, schedule)
    assert written == destination.resolve()
    assert load_execution_contract_schedule(destination) == schedule
    with pytest.raises(FileExistsError):
        write_execution_contract_schedule(destination, schedule)
    assert list(tmp_path.glob(".schedule.json.*.tmp")) == []

    tampered = schedule.model_copy(update={"selection_rule": "unsealed_change"})
    tampered_destination = tmp_path / "tampered.json"
    with pytest.raises(ValidationError, match="hash mismatch"):
        write_execution_contract_schedule(tampered_destination, tampered)
    assert not tampered_destination.exists()


@pytest.mark.parametrize(
    "value", [1000, 1000.0, "1000.0", "1e3", "+1000", "01000", "-0"]
)
def test_external_schedule_rejects_noncanonical_provenance(value):
    with pytest.raises(ValidationError, match="canonical|non-negative"):
        ExecutionContractScheduleRow(
            **{
                **_row(dt.date(2024, 1, 2), "first"),
                "source_volume": value,
            }
        )


def test_canonical_provenance_preserves_arbitrary_decimal_precision():
    precise = "123456789012345678901234567890.1234567890123456789"
    row = ExecutionContractScheduleRow(
        **{
            **_row(dt.date(2024, 1, 2), "first"),
            "source_volume": precise,
        }
    )
    assert row.source_volume == precise


def test_schedule_rejects_source_lookahead_duplicate_unordered_and_tampering():
    panel = _SchedulePanel(instruments=("first", "second"))
    with pytest.raises(ValidationError, match="strictly before"):
        ExecutionContractScheduleRow(
            **_row(
                panel.calendar[0],
                "first",
                source_date=panel.calendar[0],
            )
        )

    provenance_without_date = _row(
        panel.calendar[0],
        "first",
        status="no_prior_product_session",
        contract=None,
        source_date=None,
    )
    provenance_without_date["source_volume"] = "1"
    with pytest.raises(ValidationError, match="requires source_date"):
        ExecutionContractScheduleRow(**provenance_without_date)

    duplicate = [
        _row(panel.calendar[0], "first"),
        _row(panel.calendar[0], "first"),
    ]
    with pytest.raises(ValidationError, match="duplicate"):
        _schedule(panel, rows=duplicate)

    unordered = [
        _row(panel.calendar[0], "second"),
        _row(panel.calendar[0], "first"),
    ]
    with pytest.raises(ValidationError, match="strictly ordered"):
        _schedule(panel, rows=unordered)

    valid = _schedule(panel)
    tampered = valid.model_dump(mode="json")
    tampered["selection_rule"] = "changed_after_sealing"
    with pytest.raises(ValidationError, match="hash mismatch"):
        ExecutionContractSchedule.model_validate(tampered)


def test_preflight_rejects_missing_union_row_before_strategy_or_outputs(tmp_path: Path):
    panel = _SchedulePanel(instruments=("first", "second"))
    rows = [
        _row(date, instrument)
        for date in panel.calendar
        for instrument in panel.instruments
        if not (date == panel.calendar[1] and instrument == "second")
    ]
    schedule = _schedule(panel, rows=rows)
    strategy = _StaticTargets({"first": 1.0})
    output_dir = tmp_path / "must-not-exist"

    with pytest.raises(ValueError, match="row coverage"):
        DailyBookBacktester(
            output_dir=output_dir, slippage_bps=0.0, rebalance_weekday=None
        ).run(strategy, panel, _config(panel, schedule))

    assert strategy.calls == 0
    assert not output_dir.exists()


def test_strict_target_fill_uses_named_contract_and_never_current_main(tmp_path: Path):
    panel = _SchedulePanel(main_contract="POISON", main_price=1_000_000.0)
    schedule = _schedule(panel)

    result, _ = _run(tmp_path, panel, schedule)

    assert panel.current_bar_calls == 0
    assert [(trade.date, trade.contract, trade.intended_price) for trade in result.trades] == [
        (panel.calendar[1], "S1", 100.0)
    ]
    bound = result.events[0]
    assert bound["type"] == "execution_contract_schedule_bound"
    assert bound["detail"]["sha256"] == schedule.sha256
    assert bound["detail"]["instruments"] == ["first"]


def test_strict_fill_rejects_stale_right_contract_row(tmp_path: Path):
    class _StaleView(_ScheduleView):
        def contract_bar(self, instrument: str, contract: str):
            rows = self._panel._contracts[instrument]
            rows = rows.loc[rows.index < self.date]
            rows = rows[rows["contract"].astype(str) == str(contract)]
            return None if rows.empty else rows.iloc[-1].copy()

    class _StalePanel(_SchedulePanel):
        def view(self, date: dt.date) -> _StaleView:
            return _StaleView(self, date)

    panel = _StalePanel()
    output_dir = tmp_path / "out"
    with pytest.raises(ValueError, match="stale or future row"):
        _run(output_dir, panel, _schedule(panel))

    assert not output_dir.exists()


def test_explicit_nonexecutable_and_missing_exact_row_defer_distinctly(tmp_path: Path):
    panel = _SchedulePanel(
        contract_rows={
            "first": [
                (panel_date, "S1", 100.0)
                for panel_date in [
                    dt.date(2024, 1, 2),
                    dt.date(2024, 1, 4),
                    dt.date(2024, 1, 5),
                ]
            ]
        }
    )
    dates = panel.calendar
    rows = [
        _row(dates[0], "first"),
        _row(
            dates[1],
            "first",
            status="no_prior_product_session",
            contract=None,
            source_date=None,
        ),
        _row(dates[2], "first"),
        _row(dates[3], "first"),
    ]
    schedule = _schedule(panel, rows=rows)

    result, _ = _run(tmp_path, panel, schedule)

    assert [(trade.date, trade.contract) for trade in result.trades] == [
        (dates[2], "S1")
    ]
    target_deferrals = [
        event for event in result.events if event["type"] == "target_deferred"
    ]
    assert [event["detail"]["reason"] for event in target_deferrals] == [
        "scheduled_contract_non_executable",
    ]
    assert target_deferrals[0]["detail"]["schedule_status"] == "no_prior_product_session"

    missing_panel = _SchedulePanel(
        contract_rows={
            "first": [
                (dates[0], "S1", 100.0),
                (dates[2], "S1", 102.0),
                (dates[3], "S1", 103.0),
            ]
        }
    )
    missing_result, _ = _run(tmp_path / "missing", missing_panel, _schedule(missing_panel))
    missing_events = [
        event for event in missing_result.events if event["type"] == "target_deferred"
    ]
    assert missing_events[0]["detail"]["reason"] == "missing_exact_scheduled_contract_bar"
    assert missing_events[0]["detail"]["scheduled_contract"] == "S1"
    assert missing_result.trades[0].date == dates[2]


def test_scheduled_roll_closes_and_opens_only_exact_named_rows(tmp_path: Path):
    panel = _SchedulePanel(
        main_contract="POISON_MAIN",
        main_price=999_999.0,
        contract_rows={
            "first": [
                (dt.date(2024, 1, 2), "S1", 100.0),
                (dt.date(2024, 1, 3), "S1", 100.0),
                (dt.date(2024, 1, 4), "S1", 110.0),
                (dt.date(2024, 1, 4), "S2", 200.0),
                (dt.date(2024, 1, 5), "S2", 201.0),
            ]
        },
    )
    dates = panel.calendar
    schedule = _schedule(
        panel,
        rows=[
            _row(dates[0], "first", contract="S1"),
            _row(dates[1], "first", contract="S1"),
            _row(dates[2], "first", contract="S2"),
            _row(dates[3], "first", contract="S2"),
        ],
    )

    result, _ = _run(tmp_path, panel, schedule)

    assert panel.current_bar_calls == 0
    assert [(trade.date, trade.contract, trade.intended_price) for trade in result.trades] == [
        (dates[1], "S1", 100.0),
        (dates[2], "S1", 110.0),
        (dates[2], "S2", 200.0),
    ]


def test_missing_exact_scheduled_roll_row_defers_atomically(tmp_path: Path):
    dates = [dt.date(2024, 2, 1) + dt.timedelta(days=index) for index in range(4)]
    panel = _SchedulePanel(
        dates=dates,
        contract_rows={
            "first": [
                (dates[0], "S1", 100.0),
                (dates[1], "S1", 100.0),
                (dates[2], "S1", 110.0),
                (dates[3], "S1", 111.0),
                (dates[3], "S2", 200.0),
            ]
        },
    )
    schedule = _schedule(
        panel,
        rows=[
            _row(dates[0], "first", contract="S1"),
            _row(dates[1], "first", contract="S1"),
            _row(dates[2], "first", contract="S2"),
            _row(dates[3], "first", contract="S2"),
        ],
    )

    result, _ = _run(tmp_path, panel, schedule)

    assert [(trade.date, trade.contract) for trade in result.trades] == [
        (dates[1], "S1"),
        (dates[3], "S1"),
        (dates[3], "S2"),
    ]
    deferred = [event for event in result.events if event["type"] == "roll_deferred"]
    assert deferred[0]["detail"]["reason"] == "missing_exact_scheduled_contract_bar"
    assert deferred[0]["detail"]["next_contract"] == "S2"


def test_config_panel_window_and_instrument_mismatches_fail_closed(tmp_path: Path):
    panel = _SchedulePanel(instruments=("first", "second"))
    first_only = _schedule(panel, instruments=("first",))

    with pytest.raises(ValidationError, match="manifest"):
        _config(panel, first_only, manifest_sha256="b" * 64)
    with pytest.raises(ValidationError, match="window"):
        BookBacktestConfig(
            start=panel.calendar[0],
            end=panel.calendar[-1] + dt.timedelta(days=1),
            initial_equity_rmb=1_000_000.0,
            panel_snapshot=panel.snapshot_version,
            panel_manifest_sha256=_MANIFEST_SHA,
            execution_contract_schedule=first_only,
        )

    strategy = _StaticTargets({"second": 1.0})
    with pytest.raises(ValueError, match="outside execution contract schedule"):
        DailyBookBacktester(
            output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
        ).run(strategy, panel, _config(panel, first_only))

    unknown_schedule_payload = first_only.model_dump(mode="json")
    unknown_schedule_payload.pop("sha256")
    unknown_schedule_payload["instruments"] = ["third"]
    for row in unknown_schedule_payload["rows"]:
        row["instrument"] = "third"
    unknown = ExecutionContractSchedule.create(**unknown_schedule_payload)
    with pytest.raises(ValueError, match="absent from the panel"):
        DailyBookBacktester(
            output_dir=tmp_path / "unknown", slippage_bps=0.0, rebalance_weekday=None
        ).run(_StaticTargets({}), panel, _config(panel, unknown))


def test_strict_window_bounds_must_be_exact_union_sessions(tmp_path: Path):
    panel = _SchedulePanel()
    non_session_end = panel.calendar[-1] + dt.timedelta(days=1)
    schedule = ExecutionContractSchedule.create(
        source_panel_snapshot=panel.snapshot_version,
        source_panel_manifest_sha256=_MANIFEST_SHA,
        selection_rule="prior_visible_contract_rule",
        availability_assumption="source_rows_visible_before_fill_open",
        instruments=tuple(panel.instruments),
        start=panel.calendar[0],
        end=non_session_end,
        rows=[_row(date, "first") for date in panel.calendar],
    )
    config = BookBacktestConfig(
        start=panel.calendar[0],
        end=non_session_end,
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
        panel_manifest_sha256=_MANIFEST_SHA,
        execution_contract_schedule=schedule,
    )

    with pytest.raises(ValueError, match="exact panel union sessions"):
        DailyBookBacktester(
            output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
        ).run(_StaticTargets({"first": 1.0}), panel, config)


def test_snapshot_directory_manifest_bytes_are_independently_bound(tmp_path: Path):
    panel = _SchedulePanel()
    snapshot_dir = tmp_path / "snapshot"
    snapshot_dir.mkdir()
    manifest_path = snapshot_dir / "manifest.json"
    manifest_path.write_bytes(b'{"version":"synthetic-panel-v1"}\n')
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    panel.snapshot_dir = snapshot_dir
    schedule = _schedule(panel, manifest_sha256=manifest_sha)

    DailyBookBacktester(
        output_dir=tmp_path / "ok", slippage_bps=0.0, rebalance_weekday=None
    ).run(
        _StaticTargets({"first": 1.0}),
        panel,
        _config(panel, schedule, manifest_sha256=manifest_sha),
    )

    manifest_path.write_bytes(b'{"version":"tampered"}\n')
    with pytest.raises(ValueError, match="manifest bytes"):
        DailyBookBacktester(
            output_dir=tmp_path / "bad", slippage_bps=0.0, rebalance_weekday=None
        ).run(
            _StaticTargets({"first": 1.0}),
            panel,
            _config(panel, schedule, manifest_sha256=manifest_sha),
        )


def test_absent_schedule_preserves_legacy_main_contract_path(tmp_path: Path):
    panel = _SchedulePanel(main_contract="LEGACY_MAIN", main_price=321.0)
    strategy = _StaticTargets({"first": 1.0})
    config = BookBacktestConfig(
        start=panel.calendar[0],
        end=panel.calendar[-1],
        initial_equity_rmb=1_000_000.0,
        panel_snapshot=panel.snapshot_version,
    )
    assert set(config.model_dump()) == {
        "start",
        "end",
        "initial_equity_rmb",
        "panel_snapshot",
        "slippage_bps_by_instrument",
    }
    result = DailyBookBacktester(
        output_dir=tmp_path, slippage_bps=0.0, rebalance_weekday=None
    ).run(
        strategy,
        panel,
        config,
    )

    assert panel.current_bar_calls > 0
    assert result.trades[0].contract == "LEGACY_MAIN"
    assert result.trades[0].intended_price == 321.0
    assert not any(
        event["type"] == "execution_contract_schedule_bound"
        for event in result.events
    )
