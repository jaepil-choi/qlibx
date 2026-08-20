"""The context answers what it already knows.

An `EconomicPortfolioIntent` carries eight values and five of them are mechanical: the id derives
from the occurrence, the targets are the weights sorted, the cash target is the unallocated
remainder, the provenance is the window's, and the account version is the one the callback was
handed. Only the weights, the budget, and the strategy's identity are decisions.

The provenance one matters most. The Flow derives the same value from the same accesses and
**refuses an intent that disagrees with it**, so a Strategy assembling it by hand is transcribing
an answer that is then checked against the original. A Strategy that forgets ships an intent with
no provenance, and nothing about that is loud.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from vqapr.account.snapshot import AccountSnapshot
from vqapr.data.store import DuckDbObservationStore
from vqapr.data.windows import ModelWindow
from vqapr.domain.timestamps import LocalInstantDeclaration
from vqapr.models.contexts import StrategyModelContext
from vqapr.portfolio.budgets import Budget, PortfolioDirection
from vqapr.public import (
    DataRequirement,
    DatasetRegistration,
    RowsLookback,
    SourceSpec,
    Workspace,
)
from vqapr.runtime.agendas import OperationOccurrence, OperationRole

AT = datetime(2024, 3, 5, 6, 30, tzinfo=UTC)
BUDGET = Budget(
    PortfolioDirection.LONG_ONLY, Decimal("0"), Decimal("1"), Decimal("0"), Decimal("1")
)
REQUIREMENT = DataRequirement.of("strategy", "prices", fields=("close",), lookback=RowsLookback(1))


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    source = tmp_path / "prices.parquet"
    pq.write_table(
        pa.Table.from_pylist(
            [
                {"available_at": AT, "instrument": "A", "close": Decimal("10")},
                {"available_at": AT, "instrument": "B", "close": Decimal("20")},
            ],
            schema=pa.schema(
                [
                    ("available_at", pa.timestamp("us", tz="UTC")),
                    ("instrument", pa.string()),
                    ("close", pa.decimal128(18, 4)),
                ]
            ),
        ),
        source,
    )
    space = Workspace.create(tmp_path)
    space.register_dataset(
        DatasetRegistration.of(
            "prices",
            "prices-source",
            instrument_field="instrument",
            available_at="available_at",
            key_fields=("available_at", "instrument"),
            fields={"close": "close"},
        ),
        SourceSpec.of("prices-source", source),
    )
    return space


def _context(space: Workspace) -> StrategyModelContext:
    return StrategyModelContext(
        occurrence=OperationOccurrence(
            "cb-1",
            OperationRole.STRATEGY_CALLBACK,
            LocalInstantDeclaration(
                AT.date(), AT.timetz().replace(tzinfo=None), "UTC", 0, "+00:00"
            ),
        ),
        window=ModelWindow(
            evaluation_time=AT,
            instruments=("A", "B"),
            store=DuckDbObservationStore(space),
            allowed_requirements=(REQUIREMENT,),
        ),
        account=AccountSnapshot(7, Decimal("1000"), {}),
    )


def test_source_refs_are_empty_before_anything_is_read(workspace: Workspace) -> None:
    """Provenance describes reads that happened, not reads that were allowed."""
    assert _context(workspace).source_refs() == ()


def test_source_refs_report_what_the_window_actually_read(workspace: Workspace) -> None:
    context = _context(workspace)
    context.window.observations(REQUIREMENT)

    refs = context.source_refs()

    assert [ref.source_id for ref in refs] == ["prices-source"]
    assert refs[0].content_digest == context.window.accesses[0].source_digest


def test_reading_twice_reports_one_ref(workspace: Workspace) -> None:
    """A source read repeatedly is one provenance entry, not one per access."""
    context = _context(workspace)
    context.window.observations(REQUIREMENT)
    context.window.observations(REQUIREMENT)

    assert len(context.source_refs()) == 1


def test_source_refs_match_what_the_flow_independently_derives(workspace: Workspace) -> None:
    """The property that makes this helper safe rather than merely convenient.

    `SimulationFlow._actual_source_refs` computes provenance from the same accesses and rejects an
    intent whose refs differ. If the two ever disagreed, every intent built through the context
    would be refused -- so this equality is the contract, not an implementation detail.
    """
    from vqapr.flow.simulation import SimulationFlow

    context = _context(workspace)
    context.window.observations(REQUIREMENT)

    class _Dataset:
        dataset_id = "prices"
        source = "prices-source"

    class _Source:
        source_id = "prices-source"

    flow = SimulationFlow.__new__(SimulationFlow)
    frozen = type("_F", (), {"datasets": (_Dataset(),), "sources": (_Source(),)})()
    object.__setattr__(flow, "_frozen_run", frozen)

    assert flow._actual_source_refs(context.window) == context.source_refs()


def test_intent_fills_in_the_five_mechanical_values(workspace: Workspace) -> None:
    context = _context(workspace)
    context.window.observations(REQUIREMENT)

    intent = context.intent(
        {"B": Decimal("0.3"), "A": Decimal("0.5")}, budget=BUDGET, strategy_id="alpha"
    )

    assert [target.instrument_id for target in intent.targets] == ["A", "B"]
    assert intent.cash_target == Decimal("0.2")
    assert intent.account_version_seen == 7
    assert intent.source_refs == context.source_refs()
    assert intent.strategy_id == "alpha"


def test_an_intent_built_this_way_passes_the_validator(workspace: Workspace) -> None:
    """Budget identity holds: weights plus cash equal one."""
    from vqapr.portfolio.intents import validate_economic_intent

    context = _context(workspace)
    context.window.observations(REQUIREMENT)

    intent = context.intent({"A": Decimal("1")}, budget=BUDGET, strategy_id="alpha")

    assert validate_economic_intent(intent) is intent


def test_the_same_occurrence_and_strategy_derive_the_same_intent_id(
    workspace: Workspace,
) -> None:
    """A replay is comparable to the run it replays."""
    first = _context(workspace).intent({"A": Decimal("1")}, budget=BUDGET, strategy_id="alpha")
    second = _context(workspace).intent({"A": Decimal("1")}, budget=BUDGET, strategy_id="alpha")
    other = _context(workspace).intent({"A": Decimal("1")}, budget=BUDGET, strategy_id="beta")

    assert first.intent_id == second.intent_id
    assert first.intent_id != other.intent_id


def test_cash_target_can_be_stated_when_it_is_not_the_remainder(workspace: Workspace) -> None:
    """Holding cash deliberately is a decision, so it stays expressible."""
    context = _context(workspace)

    intent = context.intent(
        {"A": Decimal("0.5")},
        budget=BUDGET,
        strategy_id="alpha",
        cash_target=Decimal("0.5"),
    )

    assert intent.cash_target == Decimal("0.5")
