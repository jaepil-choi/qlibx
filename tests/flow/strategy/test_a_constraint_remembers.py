"""A Constraint is a Component: it keeps memory between callbacks, and the run commits it.

Owner ruling, 2026-09-08: *"constraint가 기억이 필요없다는 전제 자체가 잘못된거야"* -- a rule such as
"out after three breaches" has to count, and counting is memory. Record `181` put `memory` on
the one base every authored kind shares and made the run state commit a constraint's memory the
way it commits the Strategy's: restored before `project` and before `monitor`, and what each
callback left published with that callback's root.

Three properties, asserted on one run of four sessions:

- what `monitor` counts is visible to the next `project`, so the rule can act on it;
- the count is committed on the roots -- a fresh instance restored from the final root reads
  the same number, and the constraint's own attribute is not the authority;
- a callback that fails after `project` mutated the memory leaves the root, and the
  instance, exactly as they were.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

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
from vqapr.domain.agendas import OperationOccurrence
from vqapr.domain.values import LocalInstantDeclaration
from vqapr.flow.artifacts import SimulationFailure
from vqapr.exchange.conventions import FillConvention, FillSelector
from vqapr.exchange.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.extension.component import ComponentKind, ComponentRef
from vqapr.flow.declaration.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.flow.declaration.run import ConstraintSet, StrategyConfig
from vqapr.flow.run_state import RunStateRepository
from vqapr.flow.strategy.loop import StrategyEventLoop

KST = ZoneInfo("Asia/Seoul")
RULE = "three-strikes"


class _Holds(StrategyModel):
    def decide(self, call):  # noqa: ANN001 - the authored signature
        return Hold(reason="held")


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("a holding strategy never executes")


class ThreeStrikes(Constraint):
    """Counts its own breaches in memory and closes the box once it has seen three.

    `monitor` always reports a breach here, so the count is the number of judgements so far;
    `project` reads that count and returns a zero box once it reaches three. What the test
    asserts is the plumbing between the two, not the economics.
    """

    projected_with: list[int]
    """The count `project` saw on each callback, in order: the property under test."""

    def __init__(self) -> None:
        self.projected_with = []

    @property
    def constraint_id(self) -> str:
        return RULE

    def _count(self) -> int:
        memory = self.memory if isinstance(self.memory, dict) else {}
        return int(memory.get("breaches", 0))

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        seen = self._count()
        self.projected_with.append(seen)
        ceiling = Decimal("0") if seen >= 3 else Decimal("1")
        return ConstraintBounds(
            lower_weights={name: Decimal("0") for name in call.instruments},
            upper_weights={name: ceiling for name in call.instruments},
        )

    def monitor(
        self, call: ConstraintCall, account: EconomicAccountView, bounds: ConstraintBounds
    ) -> ConstraintFinding:
        self.memory = {"breaches": self._count() + 1}
        return ConstraintFinding(
            passed=False,
            measured=Decimal("1"),
            bound=Decimal("0"),
            excess=Decimal("1"),
            details={},
            offenders=("A",),
        )


class ProjectThenFail(ThreeStrikes):
    """Mutates memory inside `project`, then the callback fails downstream."""

    def project(self, call: ConstraintCall) -> ConstraintBounds:
        self.memory = {"breaches": 99}
        return super().project(call)


def _component(raw_id: str, kind: ComponentKind) -> ComponentRef:
    return ComponentRef.of(raw_id, kind, Path("component.py"), "Component", fingerprint="0" * 64)


def _sessions(count: int) -> tuple[date, ...]:
    return tuple(date(2024, 3, 4) + timedelta(days=index) for index in range(count))


def _callbacks(sessions: tuple[date, ...]) -> tuple[OperationOccurrence, ...]:
    return tuple(
        OperationOccurrence(
            occurrence_id=f"callback-{index}",
            local_instant=LocalInstantDeclaration(session, time(9, 0), "Asia/Seoul", 0, "+09:00"),
        )
        for index, session in enumerate(sessions)
    )


def _fill_instant(session: date) -> datetime:
    return datetime.combine(session, time(15, 30), tzinfo=KST)


def _execution_input(root: Path, sessions: tuple[date, ...]) -> ExecutionTable:
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
    return ExecutionTable.of(
        "execution",
        ExecutionTableSpec(
            SourceSpec.of("execution-source", path),
            "trade_at",
            "instrument",
            "is_tradable",
            {"close": "close"},
        ),
        FillConvention(FillSelector.SAME_DAY, time(15, 30), "Asia/Seoul", "close"),
    )


def _flow(
    root: Path, rule: ThreeStrikes, sessions: tuple[date, ...], state: RunStateRepository
) -> StrategyEventLoop:
    occurrences = _callbacks(sessions)
    frozen = FrozenRun(
        run_id="remembered",
        strategies=(
            FrozenStrategy(
                config=StrategyConfig(
                    _component("strategy", ComponentKind.STRATEGY_MODEL),
                    "strategy",
                ),
                constraints=ConstraintSet((_component(RULE, ComponentKind.CONSTRAINT),)),
                agenda=FrozenAgenda(
                    "strategy", occurrences, timezone="Asia/Seoul"
                ),
            ),
        ),
        exchange=_component("exchange", ComponentKind.EXCHANGE),
        execution=_execution_input(root, sessions),
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

    return StrategyEventLoop(
        frozen,
        _Holds(),
        state,
        strategy_window_for_occurrence=window_for_occurrence,
        constraint_window_for_occurrence=window_for_occurrence,
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_Exchange(),
        constraints=(rule,),
    )


def _state(rule: Constraint) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(AccountSnapshot(0, Decimal(100), {"A": Decimal(1)})),
        initial_component_memory={rule.constraint_id: rule.memory},
    )


def test_what_monitor_counted_is_what_the_next_project_reads(tmp_path: Path) -> None:
    rule = ThreeStrikes()
    result = _flow(tmp_path, rule, _sessions(4), _state(rule)).run()

    # `project` runs twice per session: at the callback, and again at the fill instant right
    # before `monitor` judges the book (record `148`). Both read the count monitoring committed on
    # the sessions before, and monitoring's own increment lands after its projection -- so each
    # session's pair sees the same number, and that number is the breaches so far.
    assert rule.projected_with == [0, 0, 1, 1, 2, 2, 3, 3]

    # The count lives on the root, not on the instance: a fresh instance restored from what the
    # run committed reads the same number. Four judgements, four breaches.
    fresh = ThreeStrikes()
    fresh.memory = result.final_state.component_memory()[RULE]
    assert fresh.memory == {"breaches": 4}
    assert set(result.final_state.component_state_refs) == {RULE}


def test_the_root_and_the_instance_carry_no_memory_a_failed_callback_left(tmp_path: Path) -> None:
    rule = ProjectThenFail()
    state = _state(rule)
    flow = _flow(tmp_path, rule, _sessions(2), state)

    # `project` runs before `decide` in a callback, so a `decide` that raises fails the
    # callback after the constraint has already mutated its memory.
    def failing_decide(call):  # noqa: ANN001, ANN202
        raise RuntimeError("decide fault after project")

    flow._context.strategy.decide = failing_decide  # type: ignore[method-assign]  # noqa: SLF001

    with pytest.raises(SimulationFailure, match="decide fault after project"):
        flow.run()

    assert state.current.component_memory() == {RULE: None}, "nothing was committed"
    assert rule.memory is None, "the instance was restored to what the root holds"
    assert state.current.lifecycle_trace == ()
