"""Publishing a run allocation must derive its own stamp and round-trip exactly."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

import duckdb
import pytest

from vqapr.data.lookback import RowsLookback
from vqapr.data.requirements import DataRequirement
from vqapr.domain.errors import VqaprError
from vqapr.flow.materialize import AllocationPublicationSpec, publish_run_allocation
from vqapr.flow.views import data_model_window
from vqapr.models.strategy_model import NoDecision
from vqapr.workspace import Workspace

KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True)
class _Access:
    """The access record shape the stamping rule reads."""

    max_available_at: datetime | None


@dataclass(frozen=True)
class _Target:
    instrument_id: str
    weight: Decimal | None


@dataclass(frozen=True)
class _Intent:
    targets: tuple[_Target, ...]


@dataclass(frozen=True)
class _Evidence:
    run_identity: str
    cutoff: datetime
    strategy_accesses: tuple[_Access, ...]
    decision: object


def _evidence(
    *, cutoff: datetime, read_at: datetime, weights: dict[str, str], run: str = "run-1"
) -> _Evidence:
    return _Evidence(
        run_identity=run,
        cutoff=cutoff,
        strategy_accesses=(_Access(read_at),),
        decision=_Intent(
            tuple(_Target(name, Decimal(value)) for name, value in sorted(weights.items()))
        ),
    )


def _published(path: Path) -> list[tuple]:
    con = duckdb.connect()
    try:
        return con.execute(
            f"SELECT available_at, instrument, weight FROM read_parquet('{path.as_posix()}')"
            " ORDER BY 1, 2"
        ).fetchall()
    finally:
        con.close()


def test_published_weights_round_trip_exactly(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    weights = {"A": "0.326800000000", "B": "0.180600000000"}

    result = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("alpha_allocation"),
        [_evidence(cutoff=cutoff, read_at=cutoff, weights=weights)],
    )

    rows = _published(result.output_path)
    assert result.occurrences == 1
    assert result.row_count == 2
    assert [row[1] for row in rows] == ["A", "B"]
    for row in rows:
        # Exact Decimal equality against the intent weight, not against the written file.
        assert row[2] == Decimal(weights[row[1]])


def test_the_stamp_is_derived_from_reads_not_chosen_by_the_producer(tmp_path: Path) -> None:
    """A producer must not be able to advertise a decision earlier than its own inputs."""
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    late_read = cutoff + timedelta(hours=2)

    result = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("alpha_allocation"),
        [_evidence(cutoff=cutoff, read_at=late_read, weights={"A": "0.5"})],
    )

    stamped = _published(result.output_path)[0][0]
    assert stamped == late_read, "the stamp must not precede the input that justified it"


def test_a_consumer_evaluating_before_the_stamp_sees_nothing(tmp_path: Path) -> None:
    """The point-in-time negative test: publication cannot leak backwards."""
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    result = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("alpha_allocation"),
        [_evidence(cutoff=cutoff, read_at=cutoff, weights={"A": "0.5"})],
    )

    con = duckdb.connect()
    try:
        table = f"read_parquet('{result.output_path.as_posix()}')"
        before = con.execute(
            f"SELECT count(*) FROM {table} WHERE available_at <= ?", [cutoff - timedelta(seconds=1)]
        ).fetchone()[0]
        at = con.execute(
            f"SELECT count(*) FROM {table} WHERE available_at <= ?", [cutoff]
        ).fetchone()[0]
    finally:
        con.close()

    assert before == 0
    assert at == 1


def test_lineage_shares_the_envelope_and_discriminates_by_operation(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)

    result = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("alpha_allocation"),
        [_evidence(cutoff=cutoff, read_at=cutoff, weights={"A": "0.5"})],
    )

    payload = json.loads(result.lineage_path.read_text(encoding="utf-8"))

    assert payload["schema_version"] == 1
    assert payload["operation"] == "strategy.allocation"
    assert set(payload["output"]) == {"dataset_id", "source_id", "value_fields"}
    assert payload["instruments"] == ["A"]
    assert payload["run"]["run_identity"] == ["run-1"]
    assert payload["run"]["occurrences"] == 1
    assert "component" not in payload, "a run allocation has no component provenance to fabricate"
    assert "invocations" not in payload


def test_declining_occurrences_publish_nothing_rather_than_an_empty_allocation(
    tmp_path: Path,
) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    no_decision = _Evidence("run-1", cutoff, (_Access(cutoff),), NoDecision("no signal"))

    with pytest.raises(VqaprError, match="at least one row"):
        publish_run_allocation(
            tmp_path, AllocationPublicationSpec.of("alpha_allocation"), [no_decision]
        )


def test_a_wrong_typed_evidence_is_refused_rather_than_counted_as_a_decline(
    tmp_path: Path,
) -> None:
    """A caller contract violation must not masquerade as strategy behaviour."""
    Workspace.create(tmp_path)

    with pytest.raises(VqaprError, match="callback authority"):
        publish_run_allocation(
            tmp_path, AllocationPublicationSpec.of("alpha_allocation"), [object()]
        )


def test_a_decision_that_is_neither_no_decision_nor_an_intent_is_refused(
    tmp_path: Path,
) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    bogus = _Evidence("run-1", cutoff, (_Access(cutoff),), object())

    with pytest.raises(VqaprError, match="NoDecision or an economic intent"):
        publish_run_allocation(tmp_path, AllocationPublicationSpec.of("alpha_allocation"), [bogus])


def test_quantity_economics_cannot_publish_an_allocation(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    quantity = _Evidence("run-1", cutoff, (_Access(cutoff),), _Intent((_Target("A", None),)))

    with pytest.raises(VqaprError, match="weight-economics"):
        publish_run_allocation(
            tmp_path, AllocationPublicationSpec.of("alpha_allocation"), [quantity]
        )


def test_publishing_over_an_existing_dataset_is_refused(tmp_path: Path) -> None:
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    spec = AllocationPublicationSpec.of("alpha_allocation")
    publish_run_allocation(
        tmp_path, spec, [_evidence(cutoff=cutoff, read_at=cutoff, weights={"A": "0.5"})]
    )

    with pytest.raises(VqaprError, match="must be new"):
        publish_run_allocation(
            tmp_path, spec, [_evidence(cutoff=cutoff, read_at=cutoff, weights={"A": "0.5"})]
        )


def test_reserved_field_names_are_refused() -> None:
    for reserved in ("available_at", "instrument"):
        with pytest.raises(ValueError, match="package-owned"):
            AllocationPublicationSpec.of("d", value_field=reserved)


def test_empty_evidence_is_refused(tmp_path: Path) -> None:
    Workspace.create(tmp_path)

    with pytest.raises(VqaprError, match="at least one callback evidence"):
        publish_run_allocation(tmp_path, AllocationPublicationSpec.of("d"), [])


def test_a_published_allocation_is_readable_through_an_ordinary_data_requirement(
    tmp_path: Path,
) -> None:
    """The read half of the round trip: subscribe to the publication, not to the file.

    Reading the parquet directly proves the writer serialised something. It does not prove a later
    run can *subscribe* to it, which is the milestone's actual claim: the registered dataset must be
    reachable through a `DataRequirement` inside a point-in-time window, with Decimal fidelity
    preserved across the store boundary.
    """
    Workspace.create(tmp_path)
    cutoff = datetime(2026, 4, 1, 15, 30, tzinfo=KST)
    weights = {"A": Decimal("0.326800000000"), "B": Decimal("0.180600000000")}

    published = publish_run_allocation(
        tmp_path,
        AllocationPublicationSpec.of("alpha_allocation"),
        [_evidence(cutoff=cutoff, read_at=cutoff, weights={k: str(v) for k, v in weights.items()})],
    )
    assert published.registration.dataset_id is not None

    workspace = Workspace.open(tmp_path)
    requirement = DataRequirement.of(
        "subscriber", "alpha_allocation", fields=("weight",), lookback=RowsLookback(1)
    )

    visible = data_model_window(
        workspace,
        evaluation_time=cutoff,
        instruments=tuple(sorted(weights)),
        requirements=(requirement,),
    )
    rows = visible.observations(requirement).rows
    subscribed = {row["instrument"]: row["weight"] for row in rows}

    assert subscribed == weights, "Decimal fidelity must survive the store boundary"

    hidden = data_model_window(
        workspace,
        evaluation_time=cutoff - timedelta(seconds=1),
        instruments=tuple(sorted(weights)),
        requirements=(requirement,),
    )
    assert hidden.observations(requirement).rows == ()
