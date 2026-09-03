"""What monitoring measured reaches the record, one row per constraint per occurrence.

Before record `140` a monitoring occurrence's findings lived on its trace and nowhere else. The
strategy record's `contract` block counted them (`held` / `checked`), so a run could say THAT a
limit was breached and never WHICH name, against WHAT bound, by HOW MUCH -- the three things PRD
7.1 says a breach must leave behind. `vqapr.monitoring` is where they go now, through the same
accept funnel every other package table uses, so a run with a store streams them to disk as it
goes.

Three properties, asserted directly:

- a run with a store writes one row per declared constraint per monitoring occurrence, typed --
  a `Decimal` reads back a `Decimal`, `passed` a bool, `offenders` the breaching ids joined by a
  space -- and keeps none of them on its roots;
- without a sink the rows sit on the roots, as every package table's do;
- a run that declared no constraint writes no such table at all.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from vqapr.account.account import Account, AccountMode
from vqapr.account.snapshot import AccountSnapshot, AccountState
from vqapr.authoring import ConstraintCall, EconomicAccountView, Hold, StrategyModel
from vqapr.constraints.constraint import Constraint, ConstraintBounds
from vqapr.constraints.findings import ConstraintFinding
from vqapr.constraints.monitoring import MonitoringPolicy
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.run import ConstraintSet, FrozenAgenda, FrozenRun, FrozenStrategy, StrategyConfig
from vqapr.flow.run_records import RunRecordWriter, read_typed_table, table_ids
from vqapr.flow.run_state import LifecycleKind, RunStateRepository
from vqapr.flow.simulation import SimulationFlow
from vqapr.runtime.agendas import OperationOccurrence, OperationRole
from vqapr.valuation.configuration import ValuationConfig

KST = ZoneInfo("Asia/Seoul")
TABLE = "vqapr.monitoring"


class _Holds(StrategyModel):
    def decide(self, call) -> Hold:  # pragma: no cover - no callback occurrence is scheduled
        return Hold(reason="never called")


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


def _monitoring(count: int) -> tuple[OperationOccurrence, ...]:
    first = date(2024, 1, 1)
    return tuple(
        OperationOccurrence(
            f"monitoring-{number}",
            OperationRole.MONITORING,
            LocalInstantDeclaration(
                first + timedelta(days=number), time(16, 30), "Asia/Seoul", 0, "+09:00"
            ),
        )
        for number in range(1, count + 1)
    )


def _flow(
    state: RunStateRepository,
    occurrences: tuple[OperationOccurrence, ...],
    rules: tuple[Constraint, ...] = RULES,
) -> SimulationFlow:
    frozen = FrozenRun(
        run_id="monitored",
        valuation=ValuationConfig("valuation", OperationRole.VALUATION),
        valuation_agenda=FrozenAgenda("valuation", OperationRole.VALUATION, ()),
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
                agenda=FrozenAgenda("strategy", OperationRole.STRATEGY_CALLBACK, ()),
            ),
        ),
        monitoring=MonitoringPolicy("monitoring", OperationRole.MONITORING),
        monitoring_agenda=FrozenAgenda("monitoring", OperationRole.MONITORING, occurrences),
        start=occurrences[0].evaluation_time,
        end=occurrences[-1].evaluation_time,
        initial_account_snapshot=AccountSnapshot(0, Decimal(100), {"A": Decimal(1)}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A", "B"),
    )

    def window_for_occurrence(occurrence: OperationOccurrence) -> ModelWindow:
        return ModelWindow(
            evaluation_time=occurrence.evaluation_time,
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
    occurrences = _monitoring(2)

    result = _flow(_state(row_sink=writer.append), occurrences).run()
    writer.release()

    rows = list(read_typed_table(tmp_path, "monitored", TABLE))
    assert len(rows) == 2 * len(RULES), "one row per declared constraint per occurrence"
    assert result.final_state.recorder_rows == {}, "a streamed run retains no rows on its roots"

    by_key = {(row["event_time"], row["constraint"]): row for row in rows}
    first = occurrences[0].evaluation_time
    breach = by_key[(first, "single-name-cap")]
    assert breach["passed"] is False
    assert breach["measured"] == Decimal("0.35") and isinstance(breach["measured"], Decimal)
    assert breach["bound"] == Decimal("0.10")
    assert breach["excess"] == Decimal("0.25")
    assert breach["offenders"] == "B A", "the breaching ids, in the order the rule named them"
    assert breach["account_version"] == 0
    assert breach["stage"] == "MONITORING"
    assert isinstance(breach["event_time"], datetime) and breach["event_time"].tzinfo is not None

    held = by_key[(first, "no-short")]
    assert held["passed"] is True and held["offenders"] == ""

    # The second occurrence is dated by its own cutoff, not the first's.
    assert (occurrences[1].evaluation_time, "single-name-cap") in by_key
    assert [
        entry.kind for entry in result.final_state.lifecycle_trace
    ].count(LifecycleKind.MONITORED) == 2


def test_without_a_sink_the_rows_stay_on_the_roots() -> None:
    result = _flow(_state(), _monitoring(3)).run()

    rows = result.final_state.recorder_rows[TABLE]
    assert len(rows) == 3 * len(RULES)
    assert {row["constraint"] for row in rows} == {"single-name-cap", "no-short"}
    # The counts the `contract` block reports come from the same findings, so they agree.
    breaches = [row for row in rows if row["passed"] is False]
    assert len(breaches) == 3 and all(row["constraint"] == "single-name-cap" for row in breaches)


def test_a_run_that_declared_no_constraint_writes_no_monitoring_table(tmp_path: Path) -> None:
    writer = RunRecordWriter(tmp_path, "monitored")
    writer.open()

    result = _flow(_state(row_sink=writer.append), _monitoring(2), rules=()).run()
    writer.release()

    assert TABLE not in table_ids(tmp_path, "monitored")
    assert TABLE not in result.final_state.recorder_rows
    assert all(
        entry.kind is not LifecycleKind.MONITORED for entry in result.final_state.lifecycle_trace
    )
