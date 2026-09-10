"""The book is valued at the instant the venue fills, and the NAV row is written there.

Record `148` retired the independent valuation clock. A run used to declare a valuation agenda
of its own (AC-M7: value every session the venue printed, even when the strategy decided
monthly); now every strategy is asked on every session at the run's `at`, a `Hold` still
reaches the venue's execution instant, and the book is valued there from the prices it would
have filled at. There is no second clock to keep independent, because the one clock already
reaches every session.

What that clock guaranteed still has to hold, and this file guards it on its successor:

- a strategy that decides once and holds still leaves a NAV at **every** session, because each
  Hold is valued at its execution instant;
- the NAV row is written by the valuation path at the fill instant -- stage `VALUATION`,
  `event_time` the fill instant, `observed_at` the mark instant, one row per fill or held
  valuation -- and NAV moves with the price between decisions;
- the callback's own account row is a fallback for a mark nothing recorded, and a real run
  never needs it: every mark the venue's prices produce is recorded where it is taken.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.account.account import Account, AccountMode
from vqapr.account.marking import ValuationService
from vqapr.authoring import Hold, StrategyModel
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.account_state import AccountMark, AccountSnapshot, AccountState
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.flow.engine.run_state import RunStateRepository
from vqapr.flow.run.loop import strategy_loop
from vqapr.project.run import ComplianceSet, StrategyConfig

KST = ZoneInfo("Asia/Seoul")

# Ten consecutive weekday sessions. The strategy decides on the first one only, so every later
# session is a day the book is merely held -- and must still be valued.
SESSIONS = tuple(date(2024, 3, 4) + timedelta(days=offset) for offset in range(5)) + tuple(
    date(2024, 3, 11) + timedelta(days=offset) for offset in range(5)
)

STRATEGIES = textwrap.dedent(
    '''
    from decimal import Decimal

    from vqapr.authoring import (
        DatasetInput, Hold, Rebalance, RowsLookback, StrategyModel,
    )
    from vqapr.portfolio.budgets import Budget, PortfolioDirection
    from vqapr.public import AcademicExchange, ListingAccess, TradeRule

    BUDGET = Budget(
        direction=PortfolioDirection.LONG_ONLY,
        cash_lower=Decimal(0),
        cash_upper=Decimal(1),
        target_lower=Decimal(0),
        target_upper=Decimal(1),
    )


    class MonthlyDecider(StrategyModel):
        """Buys once and then holds, so decisions and sessions cannot be confused.

        Called on every session (record 148); the cadence is a rule inside the strategy, kept in
        `self.memory`, which the framework restores before every callback and snapshots after it.
        """

        def inputs(self):
            return {
                "prices": DatasetInput(
                    dataset_id="price_daily",
                    fields=("close",),
                    lookback=RowsLookback(rows=1),
                ),
            }

        def decide(self, call):
            state = self.memory if isinstance(self.memory, dict) else {}
            observed = call.read("prices", "close").latest()
            if state.get("formed") or not observed:
                return Hold(reason="already-formed")
            self.memory = {"formed": True}
            return Rebalance(
                target_weights={"A005930": Decimal("0.5")},
                cash_weight=Decimal("0.5"),
                budget=BUDGET,
            )


    class ClockExchange(AcademicExchange):
        """Whole shares, no cost. The venue is not what this file measures."""

        def __init__(self):
            super().__init__(
                {
                    "A005930": TradeRule(
                        "A005930", Decimal(1), Decimal(1), False, ListingAccess.SIGNED
                    )
                },
                "clock-academic",
            )
    '''
)

RUNNER = textwrap.dedent(
    '''
    import sys
    from datetime import date, datetime, time
    from decimal import Decimal
    from pathlib import Path
    from zoneinfo import ZoneInfo

    from vqapr.public import (
        AccountMode, AccountSnapshot, DatasetRegistration,
        RunAgenda, RunDefinition, RunExecution, RunFill, SourceSpec, StrategyEntry, preflight_run,
        register_dataset, register_exchange, register_instruments, register_strategy_model, run,
    )

    import authored_strategies

    KST = ZoneInfo("Asia/Seoul")
    root, exec_path = Path(sys.argv[1]), Path(sys.argv[2])
    price_path = Path(sys.argv[3])
    sessions = tuple(date.fromisoformat(day) for day in sys.argv[4].split(","))

    register_dataset(
        root,
        DatasetRegistration.of(
            "price_daily", "clock-observation",
            instrument_field="instrument",
            available_at="available_at",
            grain="instrument_instant",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
            field_types={"close": "DOUBLE"},
        ),
        SourceSpec.of("clock-observation", price_path),
    )
    register_dataset(
        root,
        DatasetRegistration.of(
            'krx-daily',
            'clock-execution',
            instrument_field="instrument",
            available_at="trade_at",
            grain="instrument_instant",
            key_fields=("trade_at", "instrument"),
            fields={"close": "close", "is_tradable": "is_tradable"},
            field_types={"close": "DOUBLE", "is_tradable": "BOOLEAN"},
            execution={"is_tradable": "is_tradable"},
        ),
        SourceSpec.of("clock-execution", exec_path),
    )

    # Through the doors that prove conformance before they write (record 170); the hand-built
    # `ComponentRef` these replaced was registered without it.
    source = Path(authored_strategies.__file__).resolve()
    register_strategy_model(root, "clock-strategy", source, "MonthlyDecider")
    register_exchange(root, "clock-exchange", source, "ClockExchange")
    register_instruments(root, {"A005930": "stock"})

    # By id, not by ref: a run is a registered document and the workspace resolves what it names
    # at preflight (record 139). The run declares its sessions and wall time itself (record 148):
    # every session, decided at 08:00, filled and valued at the 15:30 print.
    definition = RunDefinition(
        run_id="clock",
        strategy=StrategyEntry("clock-strategy"),
        instruments=("A005930",),
        timezone="Asia/Seoul",
        agenda=RunAgenda(every="1d", at=(time(8, 0),)),
        exchange="clock-exchange",
        execution=RunExecution(
            dataset='krx-daily',
            trade_price='close',
            fill=RunFill(at=time(15, 30)),
        ),
        start=datetime.combine(sessions[0], time(0, 0), tzinfo=KST),
        end=datetime.combine(sessions[-1], time(23, 0), tzinfo=KST),
        initial_account_snapshot=AccountSnapshot(0, Decimal("1000000"), {}),
        initial_account_mode=AccountMode.SIGNED,
        writes="clock-weights",
    )

    result = run(root, preflight_run(root, definition)).result()

    # `vqapr.account` is the framework's own NAV table. Each row is one committed mark, so the
    # distinct observed instants ARE the NAV series resolution.
    account_rows = result.final_state.recorder_rows.get("vqapr.account", ())
    for row in account_rows:
        print(
            f"NAV|{row.get('stage')}|{row.get('event_time')}|{row.get('observed_at')}|"
            f"{row.get('nav')}|{row.get('account_version')}|"
            f"{row.get('instrument')}|{row.get('price')}"
        )
    kinds = [entry.kind.value for entry in result.final_state.lifecycle_trace]
    accepted = kinds.count("ACCEPTED_INTENT")
    callbacks = sum(
        1 for trace in result.occurrences if type(trace).__name__ == "OccurrenceTrace"
    )
    executions = sum(
        1 for trace in result.occurrences if type(trace).__name__ == "DueExecutionTrace"
    )
    print(f"SUMMARY|{accepted}|{callbacks}|{executions}")
    '''
)


@pytest.fixture(scope="module")
def clock_run(tmp_path_factory) -> tuple[list[dict], dict]:
    """One run of the monthly decider over ten sessions, with execution prices that MOVE.

    Module-scoped because every test here reads the same run and asserts a different property of
    it; the run is a subprocess so the authored strategies module is imported by path exactly as a
    registered component is.
    """
    tmp_path = tmp_path_factory.mktemp("clock")
    (tmp_path / "authored_strategies.py").write_text(STRATEGIES, encoding="utf-8")
    (tmp_path / "runner.py").write_text(RUNNER, encoding="utf-8")

    rows = ",\n".join(
        f"('A005930', TIMESTAMPTZ '{session.isoformat()} 15:30:00+09', TRUE, {72000 + n * 500}.0)"
        for n, session in enumerate(SESSIONS)
    )
    execution = tmp_path / "exec.parquet"
    # The observation the strategy declares, stamped at 07:00 so the 08:00 callback can see the
    # session it decides on. The execution table keeps its own 15:30 stamps: a decision and the
    # print it is filled and valued at are different instants.
    observed = ",\n".join(
        f"('A005930', TIMESTAMPTZ '{session.isoformat()} 07:00:00+09', {72000 + n * 500}.0)"
        for n, session in enumerate(SESSIONS)
    )
    prices = tmp_path / "prices.parquet"
    connection = duckdb.connect()
    # `CAST(... AS DOUBLE)` on both tables: a bare `72000.0` is DECIMAL(6,1) to duckdb, and a
    # price column is the DOUBLE a real parquet holds (`docs/issues/archive/088`).
    connection.execute(
        f"""COPY (SELECT instrument, trade_at, is_tradable, CAST(close AS DOUBLE) AS close
        FROM (VALUES
        {rows}
        ) AS t(instrument, trade_at, is_tradable, close))
        TO '{execution.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.execute(
        f"""COPY (SELECT instrument, available_at, CAST(close AS DOUBLE) AS close FROM (VALUES
        {observed}
        ) AS t(instrument, available_at, close))
        TO '{prices.as_posix()}' (FORMAT PARQUET)"""
    )
    connection.close()

    root = tmp_path / "project"
    root.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(tmp_path / "runner.py"),
            str(root),
            str(execution),
            str(prices),
            ",".join(session.isoformat() for session in SESSIONS),
        ],
        capture_output=True,
        text=True,
        timeout=600,
        cwd=str(tmp_path),
    )
    assert result.returncode == 0, result.stdout + result.stderr

    marks: list[dict] = []
    summary: dict = {}
    for line in result.stdout.strip().splitlines():
        if line.startswith("NAV|"):
            _, stage, event_time, observed_at, nav, version, instrument, price = line.split("|")
            marks.append(
                {
                    "stage": stage,
                    "event_time": event_time,
                    "observed_at": observed_at,
                    "nav": nav,
                    "account_version": version,
                    "instrument": instrument,
                    "price": price,
                }
            )
        elif line.startswith("SUMMARY|"):
            _, intents, callbacks, executions = line.split("|")
            summary = {
                "accepted_intents": int(intents),
                "callbacks": int(callbacks),
                "executions": int(executions),
            }
    return marks, summary


def _run_summary(clock_run) -> tuple[list[dict], dict]:
    marks, summary = clock_run
    assert marks, "the run wrote no account rows at all"
    return marks, summary


def _account_rows(marks: list[dict]) -> list[dict]:
    return [mark for mark in marks if mark["instrument"] == "_ACCOUNT"]


def test_a_monthly_decider_leaves_a_nav_at_every_session(clock_run) -> None:
    """AC-M7 on its successor: one decision, ten sessions, ten valuations.

    The strategy is asked on every session and holds on nine of them. Each Hold is still bound to
    the venue's 15:30 print and valued there, so the NAV series has the venue's resolution and not
    the decision's.
    """
    marks, summary = _run_summary(clock_run)

    assert summary["accepted_intents"] == 1, "the strategy must decide exactly once"
    assert summary["callbacks"] == len(SESSIONS), "every session asks the strategy (record 148)"
    assert summary["executions"] == len(SESSIONS), "one fill, nine held valuations"

    valued_sessions = {mark["event_time"][:10] for mark in _account_rows(marks)}
    assert valued_sessions == {session.isoformat() for session in SESSIONS}, (
        f"the NAV series does not cover every session: {sorted(valued_sessions)}"
    )
    # The accepted intent committed: the fill advanced the account, and nothing displaced it.
    assert "1" in {mark["account_version"] for mark in marks}


def test_the_nav_row_is_written_at_the_fill_instant_by_the_valuation_path(clock_run) -> None:
    """Stage `VALUATION`, dated by the instant the mark was taken -- which is the fill instant.

    `event_time` and `observed_at` are the same instant on purpose: the measurement rides the
    same run-state transition as the mark it came from. Dating the series by the 08:00 decision
    that led to the fill would put every value one commit late; measured once, that mislabelling
    took a factor correlation from 0.93 to 0.02.
    """
    marks, _ = _run_summary(clock_run)

    for row in _account_rows(marks):
        assert row["stage"] == "VALUATION", row
        event = datetime.fromisoformat(row["event_time"]).astimezone(KST)
        observed = datetime.fromisoformat(row["observed_at"]).astimezone(KST)
        assert observed == event, (
            f"NAV dated {event.isoformat()} but measured {observed.isoformat()}"
        )
        assert (event.hour, event.minute) == (15, 30), (
            f"NAV dated {event.isoformat()}, which is not the venue's print instant"
        )

    # A held instrument's row carries the instant ITS price was observed, which on a session the
    # venue priced it is the same print.
    priced = [
        row
        for row in marks
        if row["instrument"] != "_ACCOUNT" and row["price"] not in ("None", "")
    ]
    assert priced, "no instrument row carried a price"
    for row in priced:
        assert row["stage"] == "VALUATION"
        observed = datetime.fromisoformat(row["observed_at"]).astimezone(KST)
        assert observed == datetime.fromisoformat(row["event_time"]).astimezone(KST)


def test_one_row_per_fill_instant_and_none_from_the_callback(clock_run) -> None:
    """Each measurement is recorded once, where it is taken.

    Two rows for one instant would pair a real value with a duplicate -- 056 measured that as HML
    0.9726 -> 0.6877 -- and a callback row beside a valuation row is exactly that pairing. The
    callback writes its fallback row only for a mark nothing recorded, and in a real run every
    mark is recorded by the valuation path first, so no callback-stage account row exists at all.
    """
    marks, _ = _run_summary(clock_run)

    instants = [row["observed_at"] for row in _account_rows(marks)]
    assert len(instants) == len(SESSIONS), f"{len(instants)} NAV rows across {len(SESSIONS)} fills"
    assert len(set(instants)) == len(instants), f"a measurement was recorded twice: {instants}"
    assert not [row for row in marks if row["stage"] != "VALUATION"], (
        "the callback wrote an account row beside the valuation's for the same mark"
    )


def test_nav_moves_with_the_price_between_decisions(clock_run) -> None:
    """The book is held throughout, and the price rises every session, so NAV must rise too.

    A replayed mark would hold NAV flat across the whole hold period. Asserting movement rather
    than mere presence is what makes this a value check and not a row count.
    """
    marks, _ = _run_summary(clock_run)

    navs = [Decimal(row["nav"]) for row in _account_rows(marks)]
    assert len(navs) == len(SESSIONS)
    # The first valuation is the fill itself; from then on the book is held and the price rises.
    held = navs[1:]
    assert held == sorted(held) and len(set(held)) == len(held), (
        f"NAV does not rise with a rising price on a held book: {navs}"
    )


# --- the fallback row, in isolation ------------------------------------------------------------


class _Holds(StrategyModel):
    def decide(self, call) -> Hold:
        return Hold(reason="hold")


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("Hold callbacks must not execute orders")


def _component(raw_id: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(raw_id, kind, Path("component.py"), "Component", fingerprint="0" * 64)


def test_the_callback_writes_a_nav_row_only_for_a_mark_nothing_recorded() -> None:
    """The fallback's one legitimate case: a committed mark no valuation path has recorded.

    A flow without execution authority never values against venue prices, so the only mark it can
    see is one the account arrived with. Nothing recorded that instant, so the callback's row is
    the only record of the book's value there is, and it is dated by the mark instant rather than
    by the occurrence that wrote it.
    """
    snapshot = AccountSnapshot(0, Decimal("100"), {"A": Decimal("2")})
    marked_at = datetime(2024, 3, 1, 15, 30, tzinfo=KST)
    batch = ValuationService().mark(snapshot, {"A": Decimal("10")})
    arrived_marked = AccountState(
        snapshot,
        marks=(
            AccountMark(
                0, batch, snapshot.cash + batch.total_value, provenance=None, marked_at=marked_at
            ),
        ),
    )
    occurrence = OperationOccurrence(
        "strategy-1",
        LocalInstantDeclaration(date(2024, 3, 4), time(8, 0), "Asia/Seoul", 0, "+09:00"),
    )
    frozen = FrozenRun(
        run_id="fallback",
        strategy=FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", ComponentKind.STRATEGY_MODEL),
                    "strategy",
                ),
                compliance=ComplianceSet(()),
                agenda=FrozenAgenda("strategy", (occurrence,)),
            ),
        start=occurrence.evaluation_time,
        end=occurrence.evaluation_time,
        initial_account_snapshot=snapshot,
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A",),
        writes="fallback-weights",
    )

    def window_for_occurrence(item: OperationOccurrence) -> ModelWindow:
        return ModelWindow(
            evaluation_time=item.evaluation_time,
            instruments=("A",),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(),
            consumer_id="test-consumer",
        )

    state = RunStateRepository(initial_account=arrived_marked)
    result = strategy_loop(
        frozen,
        _Holds(),
        state,
        strategy_window_for_occurrence=window_for_occurrence,
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_Exchange(),
        compliance=(),
    ).run()

    rows = [
        row
        for row in result.final_state.recorder_rows["vqapr.account"]
        if row["instrument"] == "_ACCOUNT"
    ]
    assert len(rows) == 1
    (row,) = rows
    assert row["stage"] == "STRATEGY_CALLBACK"
    assert row["event_time"] == occurrence.evaluation_time
    assert row["observed_at"] == marked_at, "dated by when the nav was measured, not written"
    assert row["nav"] == Decimal("120")
