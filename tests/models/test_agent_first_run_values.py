"""Value-contract tests for `vqapr.materialization`, `vqapr.simulation`, and `vqapr.venues`.

These are pure algebra tests: required/explicit-absence fields, venue grid/cost/access
validation, cadence timezone/horizon rules, publication reserved-name rejection, and immutable
detachment. No Project/store/catalog wiring is exercised here.
"""

from __future__ import annotations

import copy
import dataclasses
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path

import pytest

from vqapr import authoring, materialization, simulation, venues
from vqapr.portfolio.budgets import Budget, PortfolioDirection


def _instant(hour: int = 9, day: int = 1) -> datetime:
    return datetime(2024, 1, day, hour, tzinfo=UTC)


# ----------------------------------------------------------------------------------
# vqapr.materialization
# ----------------------------------------------------------------------------------


def test_materialization_requires_all_fields_explicit() -> None:
    declaration = materialization.Materialization(
        output_dataset_id="monthly_return",
        evaluation_times=(_instant(9, 1), _instant(9, 2)),
        instruments=("A", "B"),
    )
    assert declaration.output_dataset_id == "monthly_return"
    assert declaration.evaluation_times == (_instant(9, 1), _instant(9, 2))
    assert declaration.instruments == ("A", "B")


def test_materialization_rejects_naive_evaluation_time() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        materialization.Materialization(
            output_dataset_id="x",
            evaluation_times=(datetime(2024, 1, 1),),
            instruments=("A",),
        )


def test_materialization_rejects_non_increasing_evaluation_times() -> None:
    with pytest.raises(ValueError, match="strictly increasing"):
        materialization.Materialization(
            output_dataset_id="x",
            evaluation_times=(_instant(9, 2), _instant(9, 1)),
            instruments=("A",),
        )


def test_materialization_rejects_duplicate_instruments() -> None:
    with pytest.raises(ValueError, match="unique"):
        materialization.Materialization(
            output_dataset_id="x",
            evaluation_times=(_instant(),),
            instruments=("A", "A"),
        )


def test_materialization_rejects_empty_instruments() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        materialization.Materialization(
            output_dataset_id="x", evaluation_times=(_instant(),), instruments=()
        )


def test_materialization_invocation_rejects_duplicate_instrument_rows() -> None:
    row = authoring.DerivedRow(instrument_id="A", values={"ret": Decimal("0.1")})
    duplicate = authoring.DerivedRow(instrument_id="A", values={"ret": Decimal("0.2")})
    with pytest.raises(ValueError, match="not repeat an instrument_id"):
        materialization.MaterializationInvocation(evaluation_time=_instant(), rows=(row, duplicate))


def test_materialization_result_requires_strictly_ordered_invocations() -> None:
    row = authoring.DerivedRow(instrument_id="A", values={"ret": Decimal("0.1")})
    first = materialization.MaterializationInvocation(evaluation_time=_instant(9, 1), rows=(row,))
    second = materialization.MaterializationInvocation(evaluation_time=_instant(9, 2), rows=(row,))
    result = materialization.MaterializationResult(
        output_dataset_id="monthly_return", invocations=(first, second)
    )
    assert result.invocations == (first, second)

    with pytest.raises(ValueError, match="strictly ordered"):
        materialization.MaterializationResult(
            output_dataset_id="monthly_return", invocations=(second, first)
        )


def test_materialization_result_rejects_empty_invocations() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        materialization.MaterializationResult(output_dataset_id="x", invocations=())


def test_materialization_is_frozen_and_detached() -> None:
    declaration = materialization.Materialization(
        output_dataset_id="x", evaluation_times=(_instant(),), instruments=("A",)
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        declaration.output_dataset_id = "y"  # type: ignore[misc]

    sources = ["A"]
    declaration2 = materialization.Materialization(
        output_dataset_id="x", evaluation_times=(_instant(),), instruments=tuple(sources)
    )
    sources.append("B")
    assert declaration2.instruments == ("A",)


# ----------------------------------------------------------------------------------
# vqapr.venues
# ----------------------------------------------------------------------------------


def test_academic_requires_explicit_listings_grid_and_costs() -> None:
    academic = venues.Academic(
        listings=(
            venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),
            venues.Listing(instrument_id="B", access=venues.ListingAccess.LONG_ONLY),
        ),
        quantity_step=Decimal("0.000001"),
        price_step=Decimal("0.01"),
        costs=(
            venues.VenueCost(side="buy", commission_rate=Decimal("0.0003"), tax_rate=Decimal("0")),
            venues.VenueCost(
                side="sell", commission_rate=Decimal("0.0003"), tax_rate=Decimal("0.0023")
            ),
        ),
    )
    assert academic.listing("A").access is venues.ListingAccess.SIGNED
    assert academic.cost("sell").tax_rate == Decimal("0.0023")
    assert academic.cost("unknown_side") is None


def test_academic_free_venue_is_explicit_empty_costs_not_a_default() -> None:
    academic = venues.Academic(
        listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
        quantity_step=Decimal("0.000001"),
        price_step=Decimal("0.000001"),
        costs=(),
    )
    assert academic.costs == ()


def test_academic_rejects_empty_listings() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        venues.Academic(listings=(), quantity_step=Decimal("1"), price_step=Decimal("1"), costs=())


def test_academic_rejects_duplicate_listing_instrument() -> None:
    with pytest.raises(ValueError, match="not repeat an instrument_id"):
        venues.Academic(
            listings=(
                venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),
                venues.Listing(instrument_id="A", access=venues.ListingAccess.LONG_ONLY),
            ),
            quantity_step=Decimal("1"),
            price_step=Decimal("1"),
            costs=(),
        )


def test_academic_rejects_duplicate_cost_side() -> None:
    with pytest.raises(ValueError, match="not declare the same side"):
        venues.Academic(
            listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
            quantity_step=Decimal("1"),
            price_step=Decimal("1"),
            costs=(
                venues.VenueCost(side="buy", commission_rate=Decimal("0"), tax_rate=Decimal("0")),
                venues.VenueCost(side="buy", commission_rate=Decimal("0"), tax_rate=Decimal("0")),
            ),
        )


@pytest.mark.parametrize(
    "quantity_step,price_step",
    [(Decimal("0"), Decimal("1")), (Decimal("-1"), Decimal("1")), (Decimal("1"), Decimal("0"))],
)
def test_academic_rejects_non_positive_grid(quantity_step: Decimal, price_step: Decimal) -> None:
    with pytest.raises(ValueError, match="positive"):
        venues.Academic(
            listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
            quantity_step=quantity_step,
            price_step=price_step,
            costs=(),
        )


def test_venue_cost_rejects_negative_rate() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        venues.VenueCost(side="buy", commission_rate=Decimal("-0.001"), tax_rate=Decimal("0"))


def test_venue_cost_rejects_non_finite_rate() -> None:
    with pytest.raises(ValueError, match="finite"):
        venues.VenueCost(side="buy", commission_rate=Decimal("Infinity"), tax_rate=Decimal("0"))


def test_listing_access_has_no_default_shortcut() -> None:
    with pytest.raises(TypeError):
        venues.Listing(instrument_id="A")  # type: ignore[call-arg]


def test_academic_is_frozen() -> None:
    academic = venues.Academic(
        listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
        quantity_step=Decimal("1"),
        price_step=Decimal("1"),
        costs=(),
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        academic.quantity_step = Decimal("2")  # type: ignore[misc]


# ----------------------------------------------------------------------------------
# vqapr.simulation: ExecutionInput / FillConvention / Execution
# ----------------------------------------------------------------------------------


def test_execution_input_requires_all_fields() -> None:
    execution_input = simulation.ExecutionInput(
        input_id="krx-daily",
        path=Path("prepared/execution.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )
    assert execution_input.input_id == "krx-daily"
    assert execution_input.price_fields == {"close": "close"}


def test_execution_input_rejects_empty_price_fields() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        simulation.ExecutionInput(
            input_id="x",
            path=Path("x.parquet"),
            hive_partitioned=False,
            trade_at_field="trade_at",
            instrument_field="instrument",
            is_tradable_field="is_tradable",
            price_fields={},
        )


def test_fill_convention_requires_iana_timezone() -> None:
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        simulation.FillConvention(
            selector=simulation.FillSelector.SAME_DAY,
            at=time(15, 30),
            timezone="Not/AZone",
            trade_price="close",
        )


def test_fill_convention_rejects_tz_aware_wall_time() -> None:
    with pytest.raises(ValueError, match="timezone-naive"):
        simulation.FillConvention(
            selector=simulation.FillSelector.SAME_DAY,
            at=time(15, 30, tzinfo=UTC),
            timezone="Asia/Seoul",
            trade_price="close",
        )


def test_execution_requires_typed_input_and_fill() -> None:
    execution_input = simulation.ExecutionInput(
        input_id="krx-daily",
        path=Path("execution.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )
    fill = simulation.FillConvention(
        selector=simulation.FillSelector.NEXT_ELIGIBLE,
        at=time(15, 30),
        timezone="Asia/Seoul",
        trade_price="close",
    )
    execution = simulation.Execution(input=execution_input, fill=fill)
    assert execution.input is execution_input
    assert execution.fill is fill


# ----------------------------------------------------------------------------------
# vqapr.simulation: Cadence / Schedule
# ----------------------------------------------------------------------------------


def test_cadence_requires_sessions_and_iana_timezone() -> None:
    cadence = simulation.Cadence(
        sessions=(date(2024, 1, 2), date(2024, 1, 3)), at=time(9), timezone="Asia/Seoul"
    )
    assert cadence.sessions == (date(2024, 1, 2), date(2024, 1, 3))


def test_cadence_rejects_empty_sessions() -> None:
    with pytest.raises(ValueError, match="at least one entry"):
        simulation.Cadence(sessions=(), at=time(9), timezone="Asia/Seoul")


def test_cadence_rejects_unknown_timezone() -> None:
    with pytest.raises(ValueError, match="unknown IANA timezone"):
        simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(9), timezone="Fake/Zone")


def test_cadence_rejects_duplicate_sessions() -> None:
    with pytest.raises(ValueError, match="unique"):
        simulation.Cadence(
            sessions=(date(2024, 1, 2), date(2024, 1, 2)), at=time(9), timezone="Asia/Seoul"
        )


def test_cadence_rejects_unsorted_sessions() -> None:
    with pytest.raises(ValueError, match="ascending order"):
        simulation.Cadence(
            sessions=(date(2024, 1, 3), date(2024, 1, 2)), at=time(9), timezone="Asia/Seoul"
        )


def test_schedule_requires_explicit_monitoring_none() -> None:
    strategy = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(8), timezone="Asia/Seoul")
    valuation = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(16), timezone="Asia/Seoul")
    schedule = simulation.Schedule(
        strategy=strategy,
        valuation=valuation,
        monitoring=None,
        start=_instant(0, 1),
        end=_instant(0, 5),
    )
    assert schedule.monitoring is None


def test_schedule_accepts_explicit_monitoring_cadence() -> None:
    strategy = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(8), timezone="Asia/Seoul")
    valuation = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(16), timezone="Asia/Seoul")
    monitoring = simulation.Cadence(
        sessions=(date(2024, 1, 2),), at=time(16, 30), timezone="Asia/Seoul"
    )
    schedule = simulation.Schedule(
        strategy=strategy,
        valuation=valuation,
        monitoring=monitoring,
        start=_instant(0, 1),
        end=_instant(0, 5),
    )
    assert schedule.monitoring is monitoring


def test_schedule_rejects_naive_start_or_end() -> None:
    strategy = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(8), timezone="Asia/Seoul")
    valuation = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(16), timezone="Asia/Seoul")
    with pytest.raises(ValueError, match="timezone-aware"):
        simulation.Schedule(
            strategy=strategy,
            valuation=valuation,
            monitoring=None,
            start=datetime(2024, 1, 1),
            end=_instant(0, 5),
        )


def test_schedule_horizon_must_be_forward() -> None:
    strategy = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(8), timezone="Asia/Seoul")
    valuation = simulation.Cadence(sessions=(date(2024, 1, 2),), at=time(16), timezone="Asia/Seoul")
    with pytest.raises(ValueError, match="strictly after"):
        simulation.Schedule(
            strategy=strategy,
            valuation=valuation,
            monitoring=None,
            start=_instant(0, 5),
            end=_instant(0, 5),
        )


# ----------------------------------------------------------------------------------
# vqapr.simulation: AccountSnapshot / InitialAccount
# ----------------------------------------------------------------------------------


def test_account_snapshot_cash_only_factory() -> None:
    snapshot = simulation.AccountSnapshot.cash_only(Decimal("1000000000"))
    assert snapshot.version == 0
    assert snapshot.cash == Decimal("1000000000")
    assert snapshot.positions == {}


def test_account_snapshot_rejects_negative_cash() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        simulation.AccountSnapshot(version=0, cash=Decimal("-1"), positions={})


def test_initial_account_long_only_rejects_negative_starting_position() -> None:
    snapshot = simulation.AccountSnapshot(
        version=0, cash=Decimal("100"), positions={"A": Decimal("-1")}
    )
    with pytest.raises(ValueError, match="negative starting position"):
        simulation.InitialAccount(snapshot=snapshot, mode=simulation.AccountMode.LONG_ONLY)


def test_initial_account_signed_allows_negative_starting_position() -> None:
    snapshot = simulation.AccountSnapshot(
        version=0, cash=Decimal("100"), positions={"A": Decimal("-1")}
    )
    account = simulation.InitialAccount(snapshot=snapshot, mode=simulation.AccountMode.SIGNED)
    assert account.snapshot.positions["A"] == Decimal("-1")


# ----------------------------------------------------------------------------------
# vqapr.simulation: ConstraintDeclaration
# ----------------------------------------------------------------------------------


class _StubConstraint(authoring.Constraint):
    def project(self, call):  # type: ignore[override]
        raise NotImplementedError

    def validate(self, decision, bounds):  # type: ignore[override]
        raise NotImplementedError

    def monitor(self, call, bounds):  # type: ignore[override]
        raise NotImplementedError


def test_constraint_declaration_requires_authoring_constraint_subclass() -> None:
    declaration = simulation.ConstraintDeclaration(
        constraint=_StubConstraint, config={"cap": Decimal("0.1")}, name="single-name-cap"
    )
    assert declaration.constraint is _StubConstraint
    assert declaration.config == {"cap": Decimal("0.1")}


def test_constraint_declaration_rejects_non_constraint_type() -> None:
    with pytest.raises(TypeError, match=r"subclass of vqapr\.authoring\.Constraint"):
        simulation.ConstraintDeclaration(constraint=object, config={}, name="bad")  # type: ignore[arg-type]


# ----------------------------------------------------------------------------------
# vqapr.simulation: Simulation
# ----------------------------------------------------------------------------------


def _build_simulation(
    *, constraints: tuple[simulation.ConstraintDeclaration, ...] = (), initial_strategy_state=None
) -> simulation.Simulation:
    schedule = simulation.Schedule(
        strategy=simulation.Cadence(
            sessions=(date(2024, 1, 2),), at=time(8), timezone="Asia/Seoul"
        ),
        valuation=simulation.Cadence(
            sessions=(date(2024, 1, 2),), at=time(16), timezone="Asia/Seoul"
        ),
        monitoring=None,
        start=_instant(0, 1),
        end=_instant(0, 5),
    )
    execution_input = simulation.ExecutionInput(
        input_id="krx-daily",
        path=Path("execution.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields={"close": "close"},
    )
    fill = simulation.FillConvention(
        selector=simulation.FillSelector.SAME_DAY,
        at=time(15, 30),
        timezone="Asia/Seoul",
        trade_price="close",
    )
    academic = venues.Academic(
        listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
        quantity_step=Decimal("0.000001"),
        price_step=Decimal("0.000001"),
        costs=(),
    )
    account = simulation.InitialAccount(
        snapshot=simulation.AccountSnapshot.cash_only(Decimal("1000000000")),
        mode=simulation.AccountMode.SIGNED,
    )
    return simulation.Simulation(
        schedule=schedule,
        execution=simulation.Execution(input=execution_input, fill=fill),
        exchange=academic,
        account=account,
        constraints=constraints,
        instruments=("A",),
        initial_strategy_state=initial_strategy_state,
    )


def test_simulation_requires_explicit_empty_constraints_and_none_state() -> None:
    sim = _build_simulation()
    assert sim.constraints == ()
    assert sim.initial_strategy_state is None


def test_simulation_accepts_constraints_and_json_state() -> None:
    declaration = simulation.ConstraintDeclaration(
        constraint=_StubConstraint, config={}, name="cap"
    )
    sim = _build_simulation(constraints=(declaration,), initial_strategy_state={"warm": True})
    assert sim.constraints == (declaration,)
    assert sim.initial_strategy_state == {"warm": True}


def test_simulation_rejects_duplicate_constraint_names() -> None:
    first = simulation.ConstraintDeclaration(constraint=_StubConstraint, config={}, name="cap")
    second = simulation.ConstraintDeclaration(constraint=_StubConstraint, config={}, name="cap")
    with pytest.raises(ValueError, match="not repeat a declaration name"):
        _build_simulation(constraints=(first, second))


def test_simulation_is_frozen() -> None:
    sim = _build_simulation()
    with pytest.raises(dataclasses.FrozenInstanceError):
        sim.instruments = ("B",)  # type: ignore[misc]


# ----------------------------------------------------------------------------------
# vqapr.simulation: Publication
# ----------------------------------------------------------------------------------


def test_publication_requires_at_least_one_output() -> None:
    with pytest.raises(ValueError, match="at least one output"):
        simulation.Publication(allocation=None, records=())


def test_publication_allocation_only_is_explicit() -> None:
    allocation = simulation.AllocationOutput(dataset_id="weights", value_field="weight")
    publication = simulation.Publication(allocation=allocation, records=())
    assert publication.allocation is allocation
    assert publication.records == ()


def test_publication_records_only_is_explicit() -> None:
    record = simulation.RecordOutput(
        dataset_id="diagnostics", table_id="membership", semantic_fields=("score",)
    )
    publication = simulation.Publication(allocation=None, records=(record,))
    assert publication.allocation is None
    assert publication.records == (record,)


@pytest.mark.parametrize(
    "reserved_field",
    ["observed_at", "producer", "stage", "event_time", "sequence", "lineage", "version"],
)
def test_publication_rejects_reserved_semantic_field_names(reserved_field: str) -> None:
    record = simulation.RecordOutput(
        dataset_id="diagnostics", table_id="membership", semantic_fields=(reserved_field,)
    )
    with pytest.raises(ValueError, match="framework-reserved"):
        simulation.Publication(allocation=None, records=(record,))


def test_allocation_output_rejects_reserved_value_field() -> None:
    with pytest.raises(ValueError, match="framework-reserved"):
        simulation.AllocationOutput(dataset_id="weights", value_field="producer")


def test_publication_rejects_duplicate_record_dataset_ids() -> None:
    first = simulation.RecordOutput(
        dataset_id="diagnostics", table_id="membership", semantic_fields=("score",)
    )
    second = simulation.RecordOutput(
        dataset_id="diagnostics", table_id="other", semantic_fields=("score",)
    )
    with pytest.raises(ValueError, match="not repeat a dataset_id"):
        simulation.Publication(allocation=None, records=(first, second))


def test_publication_is_frozen() -> None:
    allocation = simulation.AllocationOutput(dataset_id="weights", value_field="weight")
    publication = simulation.Publication(allocation=allocation, records=())
    with pytest.raises(dataclasses.FrozenInstanceError):
        publication.allocation = None  # type: ignore[misc]


# ----------------------------------------------------------------------------------
# Immutable detachment across the three modules
# ----------------------------------------------------------------------------------


def test_execution_input_price_fields_detach_from_caller_mapping() -> None:
    source = {"close": "close"}
    execution_input = simulation.ExecutionInput(
        input_id="x",
        path=Path("x.parquet"),
        hive_partitioned=False,
        trade_at_field="trade_at",
        instrument_field="instrument",
        is_tradable_field="is_tradable",
        price_fields=source,
    )
    source["open"] = "open"
    assert execution_input.price_fields == {"close": "close"}
    with pytest.raises(TypeError):
        execution_input.price_fields["hacked"] = "x"  # type: ignore[index]


def test_account_snapshot_positions_detach_from_caller_mapping() -> None:
    source = {"A": Decimal("1")}
    snapshot = simulation.AccountSnapshot(version=0, cash=Decimal("0"), positions=source)
    source["B"] = Decimal("2")
    assert dict(snapshot.positions) == {"A": Decimal("1")}


def test_venue_listings_and_costs_are_deep_copyable_and_immutable() -> None:
    academic = venues.Academic(
        listings=(venues.Listing(instrument_id="A", access=venues.ListingAccess.SIGNED),),
        quantity_step=Decimal("1"),
        price_step=Decimal("1"),
        costs=(),
    )
    cloned = copy.deepcopy(academic)
    assert cloned == academic
    with pytest.raises(dataclasses.FrozenInstanceError):
        academic.listings[0].access = venues.ListingAccess.LONG_ONLY  # type: ignore[misc]


def test_rebalance_is_available_through_authoring_for_budget_declaration() -> None:
    """Confirms simulation-adjacent modules interoperate with the sibling authoring contract."""
    budget = Budget(
        direction=PortfolioDirection.SIGNED,
        cash_lower=Decimal("-1"),
        cash_upper=Decimal("1"),
        target_lower=Decimal("-1"),
        target_upper=Decimal("1"),
    )
    rebalance = authoring.Rebalance(
        target_weights={"A": Decimal("0.5")}, cash_weight=Decimal("0.5"), budget=budget
    )
    assert rebalance.target_weights == {"A": Decimal("0.5")}
