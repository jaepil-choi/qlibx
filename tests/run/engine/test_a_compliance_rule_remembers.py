"""A Compliance rule is a Component: it keeps memory between observations, and the run commits it.

Owner ruling, 2026-09-08: *"constraint가 기억이 필요없다는 전제 자체가 잘못된거야"* -- a rule such as
"out after three breaches" has to count, and counting is memory. Record `181` put `memory` on
the one base every authored kind shares; design §7.2 is why it matters here: *"위반은 세는 것이고
세는 것은 기억한다."* The run restores a rule's memory before `observe` and commits what it left
with the findings, at every market-clock instant.

Three properties, asserted on one run of four sessions:

- what one observation counted is visible to the next, so a rule can act on it;
- the count is committed on the roots -- a fresh instance restored from the final root reads the
  same number, and the rule's own attribute is not the authority;
- an observation that fails after mutating its memory commits nothing: the root keeps the mark
  the instant made and none of what the rule left.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.authoring import (
    Compliance,
    ComplianceCall,
    ComplianceFinding,
    Hold,
    StrategyModel,
)
from vqapr.component.reference import ComponentRef
from vqapr.data.execution_table import ExecutionTable, ExecutionTableSpec
from vqapr.data.source import SourceSpec
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.window import ModelWindow
from vqapr.domain.account import Account, AccountMode, AccountSnapshot, AccountState
from vqapr.domain.fill import FillRule
from vqapr.domain.instants import LocalInstantDeclaration
from vqapr.domain.schedule import OperationOccurrence
from vqapr.domain.wiring import Role
from vqapr.run.engine.failure import SimulationFailure, SimulationStage
from vqapr.run.engine.loop import RunLoop, strategy_loop
from vqapr.run.engine.run_state import LifecycleKind, RunStateRepository
from vqapr.run.preflight.frozen import FrozenAgenda, FrozenRun, FrozenStrategy
from vqapr.workspace.run_definition import ComplianceSet, StrategyConfig

KST = ZoneInfo("Asia/Seoul")
RULE = "three-strikes"


class _Holds(StrategyModel):
    def decide(self, call):
        return Hold(reason="held")


class _Catalog:
    def dataset(self, raw_dataset_id: str) -> object:
        raise AssertionError(f"unexpected dataset read: {raw_dataset_id}")

    def source(self, raw_source_id: str) -> object:
        raise AssertionError(f"unexpected source read: {raw_source_id}")


class _Exchange:
    def execute(self, *args: object) -> object:
        raise AssertionError("a holding strategy never executes")


class ThreeStrikes(Compliance):
    """Counts its own breaches in memory. Every observation is a breach here, so the count is the
    number of observations so far; what the test asserts is the plumbing, not the economics."""

    observed_with: list[int]
    """The count `observe` saw on each call, in order: the property under test."""

    def __init__(self) -> None:
        self.observed_with = []

    @property
    def compliance_id(self) -> str:
        return RULE

    def _count(self) -> int:
        memory = self.memory if isinstance(self.memory, dict) else {}
        return int(memory.get("breaches", 0))

    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        seen = self._count()
        self.observed_with.append(seen)
        self.memory = {"breaches": seen + 1}
        return ComplianceFinding(
            passed=False,
            measured=Decimal("1"),
            bound=Decimal("0"),
            excess=Decimal("1"),
            details={"strikes": seen + 1},
            offenders=("A",),
        )


class MutateThenFail(ThreeStrikes):
    """Mutates memory inside `observe`, then fails."""

    def observe(self, call: ComplianceCall) -> ComplianceFinding:
        self.memory = {"breaches": 99}
        raise RuntimeError("observe fault after the mutation")


def _component(raw_id: str, kind: Role) -> ComponentRef:
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
        FillRule("close", "Asia/Seoul", at=time(15, 30)),
    )


def _flow(
    root: Path, rule: ThreeStrikes, sessions: tuple[date, ...], state: RunStateRepository
) -> RunLoop:
    occurrences = _callbacks(sessions)
    frozen = FrozenRun(
        run_id="remembered",
        strategy=FrozenStrategy(
            config=StrategyConfig(_component("strategy", Role.STRATEGY_MODEL), "strategy"),
            compliance=ComplianceSet((_component(RULE, Role.COMPLIANCE),)),
            agenda=FrozenAgenda("strategy", occurrences, timezone="Asia/Seoul"),
        ),
        exchange=_component("exchange", Role.EXCHANGE),
        execution=_execution_input(root, sessions),
        start=occurrences[0].evaluation_time,
        end=_fill_instant(sessions[-1]) + timedelta(hours=1),
        initial_account_snapshot=AccountSnapshot(0, Decimal(100), {"A": Decimal(1)}),
        initial_account_mode=AccountMode.LONG_ONLY,
        instruments=("A", "B"),
        writes="remembered-weights",
    )

    def window_at(instant: datetime) -> ModelWindow:
        return ModelWindow(
            evaluation_time=instant,
            instruments=("A", "B"),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(),
        )

    return strategy_loop(
        frozen,
        _Holds(),
        state,
        strategy_window_for_occurrence=lambda occurrence: ModelWindow(
            evaluation_time=occurrence.evaluation_time,
            instruments=("A", "B"),
            store=DuckDbObservationStore(_Catalog()),
            allowed_requirements=(),
            consumer_id="test-consumer",
        ),
        compliance_window_at=window_at,
        account=Account(mode=AccountMode.LONG_ONLY),
        exchange=_Exchange(),
        compliance=(rule,),
    )


def _state(rule: Compliance) -> RunStateRepository:
    return RunStateRepository(
        initial_account=AccountState(AccountSnapshot(0, Decimal(100), {"A": Decimal(1)})),
        initial_component_memory={rule.compliance_id: rule.memory},
    )


def test_what_one_observation_counted_is_what_the_next_reads(tmp_path: Path) -> None:
    rule = ThreeStrikes()
    result = _flow(tmp_path, rule, _sessions(4), _state(rule)).run()

    # One observation per market-clock instant -- the venue's 15:30 print, four sessions -- and
    # each reads the count the one before it committed.
    assert rule.observed_with == [0, 1, 2, 3]

    # The count lives on the root, not on the instance: a fresh instance restored from what the
    # run committed reads the same number. Four observations, four strikes.
    fresh = ThreeStrikes()
    fresh.memory = result.final_state.component_memory()[RULE]
    assert fresh.memory == {"breaches": 4}
    assert set(result.final_state.component_state_refs) == {RULE}
    assert [
        entry.kind for entry in result.final_state.lifecycle_trace
    ].count(LifecycleKind.MONITORED) == 4


def test_a_failed_observation_commits_nothing_the_rule_left(tmp_path: Path) -> None:
    rule = MutateThenFail()
    state = _state(rule)
    flow = _flow(tmp_path, rule, _sessions(2), state)

    with pytest.raises(SimulationFailure, match="observe fault after the mutation") as raised:
        flow.run()

    assert raised.value.stage is SimulationStage.MARKET_COMPLIANCE
    assert state.current.component_memory() == {RULE: None}, "nothing the rule left was committed"
    kinds = [entry.kind for entry in state.current.lifecycle_trace]
    assert LifecycleKind.MARKED in kinds, "the mark the instant made before COMPLIANCE stands"
    assert LifecycleKind.MONITORED not in kinds
