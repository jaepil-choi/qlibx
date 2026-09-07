"""What monitoring measured reaches the record, one row per constraint per commit.

Before record `140` a monitoring occurrence's findings lived on its trace and nowhere else. The
strategy record's `contract` block counted them (`held` / `checked`), so a run could say THAT a
limit was breached and never WHICH name, against WHAT bound, by HOW MUCH -- the three things PRD
7.1 says a breach must leave behind. `vqapr.monitoring` is where they go now, through the same
accept funnel every other package table uses, so a run with a store streams them to disk as it
goes.

Record `148` moved WHEN they arrive. Monitoring has no occurrence of its own any more: the
declared constraints judge the committed, marked book right after each commit -- a fill's, or a
held book's valuation at its execution instant -- and the findings are dated by that instant.
The flow here holds on every session, so every session reaches the venue's 15:30 print, is
valued there, and is judged there.

Three properties, asserted directly:

- a run with a store writes one row per declared constraint per commit, typed -- a `Decimal`
  reads back a `Decimal`, `passed` a bool, `offenders` the breaching ids joined by a space --
  stage `MONITORING`, `event_time` the fill instant, and keeps none of them on its roots;
- without a sink the rows sit on the roots, as every package table's do;
- a run that declared no constraint writes no such table at all.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.authoring import (
    Constraint,
    ConstraintBounds,
    ConstraintCall,
    ConstraintFinding,
    EconomicAccountView,
    Hold,
    StrategyModel,
)
from vqapr.data.sources import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.agendas import OperationOccurrence, OperationRole
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionInputRegistration, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.flow.record import RunRecordWriter, read_typed_table, table_ids
from vqapr.flow.run import ConstraintSet, StrategyConfig
from vqapr.flow.run_state import LifecycleKind, RunStateRepository
from vqapr.flow.simulation import DueExecutionTrace, SimulationFlow

KST = ZoneInfo("Asia/Seoul")
TABLE = "vqapr.monitoring"
FIRST_SESSION = date(2024, 1, 2)
FILL = time(15, 30)
"""The venue prints once a session, at the close; every held book is valued and judged there."""


class _Holds(StrategyModel):
    """Never trades. Each Hold still reaches the execution instant, where the book is judged."""

    def decide(self, call) -> Hold:
        return Hold(reason="hold, and be judged at the close")


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset access: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source access: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:  # pragma: no cover - nothing is ordered
        raise AssertionError("no order is placed")


class _Rule(Constraint):
    """A rule whose finding is fixed, so the test knows exactly what should land on disk."""

    def __init__(self, constraint_id: str, finding: ConstraintFinding) -> None:
        self._constraint_id = constraint_id
        self._finding = finding

    @property
    def constraint_id(self) -> str:
        return self._constraint_id

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        return ConstraintBounds(
            lower_weights={instrument: Decimal("0") for instrument in call.instruments},
            upper_weights={instrument: Decimal("1") for instrument in call.instruments},
        )

    def monitor(
        self, call: ConstraintCall, account: EconomicAccountView, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        return self._finding


BREACH = ConstraintFinding(
    passed=False,
    measured=Decimal("0.35"),
    bound=Decimal("0.10"),
    excess=Decimal("0.25"),
    details={},
    offenders=("B", "A"),
)
HELD = ConstraintFinding(
    passed=True, measured=Decimal("0"), bound=Decimal("0"), excess=Decimal("0"), details={}
)
RULES = (_Rule("single-name-cap", BREACH), _Rule("no-short", HELD))


def _component(raw_id: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(raw_id, kind, Path("component.py"), "Component", fingerprint="0" * 64)


def _sessions(count: int) -> tuple[date, ...]:
    return tuple(FIRST_SESSION + timedelta(days=number) for number in range(count))


def _callbacks(sessions: tuple[date, ...]) -> tuple[OperationOccurrence, ...]:
    """One strategy callback per session, before the open: the run's one agenda (record `148`)."""
    return tuple(
        OperationOccurrence(
            f"strategy-{session.isoformat()}",
            OperationRole.STRATEGY_CALLBACK,
            LocalInstantDeclaration(session, time(8, 0), "Asia/Seoul", 0, "+09:00"),
        )
        for session in sessions
    )


def _fill_instant(session: date) -> datetime:
    return datetime.combine(session, FILL, tzinfo=KST)


def _execution_input(root: Path, sessions: tuple[date, ...]) -> ExecutionInputRegistration:
    """A venue that prints A at 15:30 on every session, so a held book can be valued there."""
    path = root / "execution.parquet"
    rows = ",\n".join(
        f"(TIMESTAMPTZ '{session.isoformat()} 15:30:00+09', 'A', true, {100 + n}.0)"
        for n, session in enumerate(sessions)
    )
    connection = duckdb.connect()
    try:
        connection.execute(
            f"""COPY (
                SELECT * FROM (VALUES
                    {rows}
                ) AS t(trade_at, instrument, is_tradable, close)
            ) TO '{path.as_posix()}' (FORMAT PARQUET)"""
        )
    finally:
        connection.close()
    return ExecutionInputRegistration.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", path),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillConvention(FillSelector.SAME_DAY, FILL, "Asia/Seoul", "close"),
    )


def _flow(
    root: Path,
    state: RunStateRepository,
    sessions: tuple[date, ...],
    rules: tuple[Constraint, ...] = RULES,
) -> SimulationFlow:
    occurrences = _callbacks(sessions)
    frozen = FrozenRun(
        run_id="monitored",
        strategies=(
            FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", ComponentKind.STRATEGY_MODEL),
                    "strategy",
                    OperationRole.STRATEGY_CALLBACK,
                ),
                constraints=ConstraintSet(
                    tuple(
                        _component(rule.constraint_id, ComponentKind.CONSTRAINT) for rule in rules
                    )
                ),
                agenda=FrozenAgenda(
                    "strategy", OperationRole.STRATEGY_CALLBACK, occurrences, timezone="Asia/Seoul"
                ),
            ),
        ),
        exchange=_component("exchange", ComponentKind.EXCHANGE),
        execution_input=_execution_input(root, sessions),
        start=occurrences[0].evaluation_time,
        end=_fill_instant(sessions[-1]) + timedelta(hours=1),
        initial_account_snapshot=AccountSnapshot(0, Decimal(100), {"A": Decimal(1)}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A", "B"),
    )

    def window_for_occurrence(occurrence: object) -> ModelWindow:
        return ModelWindow(
            evaluation_time=occurrence.evaluation_time,  # type: ignore[attr-defined]
            instruments=("A", "B"),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(),
            consumer_id="test-consumer",
        )

    return SimulationFlow(
        frozen,
        _Holds(),
        state,
        strategy_window_for_occurrence=window_for_occurrence,
        constraint_window_for_occurrence=window_for_occurrence,
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_Exchange(),
        constraints=rules,
    )


def _state(row_sink=None) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(AccountSnapshot(0, Decimal(100), {"A": Decimal(1)})),
        row_sink=row_sink,
    )


def test_each_finding_reaches_the_record_typed_and_the_roots_keep_none(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "monitored")
    writer.open()
    sessions = _sessions(2)

    result = _flow(tmp_path, _state(row_sink=writer.append), sessions).run()
    writer.release()

    rows = list(read_typed_table(tmp_path, "monitored", TABLE))
    assert len(rows) == 2 * len(RULES), "one row per declared constraint per commit"
    assert result.final_state.recorder_rows == {}, "a streamed run retains no rows on its roots"

    by_key = {(row["event_time"], row["constraint"]): row for row in rows}
    first = _fill_instant(sessions[0])
    breach = by_key[(first, "single-name-cap")]
    assert breach["passed"] is False
    assert breach["measured"] == Decimal("0.35") and isinstance(breach["measured"], Decimal)
    assert breach["bound"] == Decimal("0.10")
    assert breach["excess"] == Decimal("0.25")
    assert breach["offenders"] == "B A", "the breaching ids, in the order the rule named them"
    assert breach["account_version"] == 0, "a held book is judged without a fill advancing it"
    assert breach["stage"] == "MONITORING"
    assert isinstance(breach["event_time"], datetime) and breach["event_time"].tzinfo is not None
    assert breach["event_time"] == first, (
        "dated by the instant the book was committed and marked, not by the 08:00 decision"
    )

    held = by_key[(first, "no-short")]
    assert held["passed"] is True and held["offenders"] == ""

    # The second commit is dated by its own fill instant, not the first's.
    assert (_fill_instant(sessions[1]), "single-name-cap") in by_key
    assert [
        entry.kind for entry in result.final_state.lifecycle_trace
    ].count(LifecycleKind.MONITORED) == 2
    # And what the due path returned carries the same findings the record does.
    due = [trace for trace in result.occurrences if isinstance(trace, DueExecutionTrace)]
    assert len(due) == 2
    assert all(
        [finding.constraint_id for finding in trace.result.report.findings]
        == ["single-name-cap", "no-short"]
        for trace in due
    )


def test_without_a_sink_the_rows_stay_on_the_roots(tmp_path: Path) -> None:
    result = _flow(tmp_path, _state(), _sessions(3)).run()

    rows = result.final_state.recorder_rows[TABLE]
    assert len(rows) == 3 * len(RULES)
    assert {row["constraint"] for row in rows} == {"single-name-cap", "no-short"}
    assert {row["stage"] for row in rows} == {"MONITORING"}
    assert {row["event_time"] for row in rows} == {
        _fill_instant(session) for session in _sessions(3)
    }, "one judgement per commit, each at its own fill instant"
    # The counts the `contract` block reports come from the same findings, so they agree.
    breaches = [row for row in rows if row["passed"] is False]
    assert len(breaches) == 3 and all(row["constraint"] == "single-name-cap" for row in breaches)


def test_a_run_that_declared_no_constraint_writes_no_monitoring_table(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "monitored")
    writer.open()

    result = _flow(tmp_path, _state(row_sink=writer.append), _sessions(2), rules=()).run()
    writer.release()

    assert TABLE not in table_ids(tmp_path, "monitored")
    assert TABLE not in result.final_state.recorder_rows
    assert all(
        entry.kind is not LifecycleKind.MONITORED for entry in result.final_state.lifecycle_trace
    )
    due = [trace for trace in result.occurrences if isinstance(trace, DueExecutionTrace)]
    assert len(due) == 2 and all(trace.result.monitoring is None for trace in due), (
        "nothing to judge, so the due path reports no monitoring rather than an empty report"
    )
