import json
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from qlibx import (
    BudgetMode,
    DecisionAction,
    OutcomeStatus,
    QlibxProject,
    StrategyDraft,
    StrategyInvocation,
    WeightEntry,
)
from qlibx.data import (
    AvailableAtField,
    CalendarLookback,
    ComponentRequirement,
    DatasetRegistration,
    ObservationStore,
    RowsLookback,
    SourceFormat,
)
from qlibx.data.store import DataSnapshotError


def register(tmp_path: Path, rows: str):
    root = tmp_path / "project"
    QlibxProject.init(root, apply=True)
    source = root / "panel.csv"
    source.write_text(
        "observation_time,available_at,instrument,sequence,value\n" + rows,
        encoding="utf-8",
    )
    project = QlibxProject.open(root)
    outcome = project.register_dataset(
        DatasetRegistration(
            dataset_id="panel",
            source="panel.csv",
            source_format=SourceFormat.CSV,
            instrument_field="instrument",
            observation_time_field="observation_time",
            source_timezone="UTC",
            available_at=AvailableAtField(field="available_at"),
            logical_key=(
                "observation_time",
                "available_at",
                "instrument",
                "sequence",
            ),
            semantic_bindings={"value": "value"},
            source_provenance="exact lookback fixture",
        )
    )
    assert outcome.status is OutcomeStatus.COMPLETE
    return project, outcome.result


class BoundedHistoryStrategy:
    strategy_id = "tests.bounded-history"

    def requirements(self) -> tuple[ComponentRequirement, ...]:
        return (
            ComponentRequirement(
                requirement_id="bounded.value",
                semantic_role="value",
                dataset_id="panel",
                lookback=RowsLookback(rows=2),
            ),
        )

    def run(self, view: object) -> StrategyDraft:
        frame = view.history("value", ("A", "C"))  # type: ignore[attr-defined]
        assert frame["value"].tolist() == [2, 3]
        return StrategyDraft(
            weights=(WeightEntry(instrument="A", weight=1.0),),
            budget_mode=BudgetMode.FIXED,
            target_gross=1.0,
            decision_action=DecisionAction.RESEARCH_ONLY,
        )


def test_rows_lookback_is_per_instrument_and_tie_deterministic(tmp_path: Path) -> None:
    _project, dataset = register(
        tmp_path,
        "2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,1\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,A,1,2\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,A,2,3\n"
        "2025-01-01T00:00:00,2025-01-01T01:00:00,B,1,4\n",
    )
    store = ObservationStore()

    frame = store.query(
        dataset,
        field="value",
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
        lookback=RowsLookback(rows=2),
        instruments=("A", "B", "C"),
    )

    assert frame[["instrument", "value"]].to_records(index=False).tolist() == [
        ("A", 2),
        ("A", 3),
        ("B", 4),
    ]
    empty = store.query(
        dataset,
        field="value",
        as_of=datetime(2025, 1, 3, tzinfo=UTC),
        lookback=RowsLookback(rows=2),
        instruments=("C",),
    )
    assert empty.empty


def test_strategy_v3_records_exact_lookback_snapshot_and_requested_counts(
    tmp_path: Path,
) -> None:
    project, dataset = register(
        tmp_path,
        "2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,1\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,A,1,2\n"
        "2025-01-02T00:00:00,2025-01-02T01:00:00,A,2,3\n",
    )
    outcome = project.invoke(
        BoundedHistoryStrategy(),
        StrategyInvocation(
            invocation_id="bounded-history",
            evaluation_time=datetime(2025, 1, 3, tzinfo=UTC),
            config_fingerprint="bounded-history-v1",
        ),
    )

    assert outcome.status is OutcomeStatus.COMPLETE
    access = outcome.result.result.accesses[0]
    assert access.lookback == RowsLookback(rows=2)
    assert dataset.query_snapshot is not None
    assert access.snapshot_fingerprint == dataset.query_snapshot.fingerprint
    assert access.requested_instruments == ("A", "C")
    assert access.per_instrument_actual_count == (("A", 2), ("C", 0))
    assert outcome.result.artifact.artifact_schema_version == 3


def test_calendar_lookback_uses_local_midnight_month_end_clamp_and_inclusive_bounds(
    tmp_path: Path,
) -> None:
    _project, dataset = register(
        tmp_path,
        "2024-02-28T14:59:00,2024-02-28T14:59:00,A,1,1\n"
        "2024-02-28T15:00:00,2024-02-28T15:00:00,A,1,2\n"
        "2024-03-31T14:00:00,2024-03-31T14:00:00,A,1,3\n"
        "2024-03-31T14:01:00,2024-03-31T14:01:00,A,1,4\n",
    )

    frame = ObservationStore().query(
        dataset,
        field="value",
        as_of=datetime(2024, 3, 31, 23, 0, tzinfo=ZoneInfo("Asia/Seoul")),
        lookback=CalendarLookback(months=1, timezone="Asia/Seoul"),
    )

    assert frame["value"].tolist() == [2, 3]


def test_history_without_lookback_fails_explicitly(tmp_path: Path) -> None:
    _project, dataset = register(
        tmp_path,
        "2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,1\n",
    )

    with pytest.raises(DataSnapshotError) as raised:
        ObservationStore().query(
            dataset,
            field="value",
            as_of=datetime(2025, 1, 3, tzinfo=UTC),
        )
    assert raised.value.code == "DATASET_LOOKBACK_REQUIRED"


def test_explicit_reindex_upgrades_legacy_pointer_idempotently(tmp_path: Path) -> None:
    project, dataset = register(
        tmp_path,
        "2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,1\n",
    )
    assert dataset.query_snapshot is not None
    registry_path = Path(dataset.query_snapshot.path).parent.parent / "registrations" / "panel.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["registration_schema_version"] = 1
    payload["query_snapshot"] = None
    payload["bindings"] = {
        "instrument": "instrument",
        "available_at": "__available_at__",
        "value": "value",
    }
    payload.pop("source_bindings", None)
    registry_path.write_text(json.dumps(payload), encoding="utf-8")
    legacy = project.registry_snapshot().get("panel")
    assert legacy is not None

    with pytest.raises(DataSnapshotError) as raised:
        ObservationStore().query(
            legacy,
            field="value",
            as_of=datetime(2025, 1, 3, tzinfo=UTC),
            lookback=RowsLookback(rows=1),
        )
    assert raised.value.code == "DATASET_QUERY_SNAPSHOT_REQUIRED"
    public_outcome = project.invoke(
        BoundedHistoryStrategy(),
        StrategyInvocation(
            invocation_id="legacy-snapshot-required",
            evaluation_time=datetime(2025, 1, 3, tzinfo=UTC),
            config_fingerprint="legacy-snapshot-required-v1",
        ),
    )
    assert public_outcome.status is OutcomeStatus.FAILED
    assert public_outcome.errors[0].error_code == "DATASET_QUERY_SNAPSHOT_REQUIRED"

    upgraded = project.reindex_datasets(("panel",))
    repeated = project.reindex_datasets(("panel",))

    assert upgraded.status is repeated.status is OutcomeStatus.COMPLETE
    assert upgraded.result.items[0].changed is True
    assert repeated.result.items[0].changed is False
    current = project.registry_snapshot().get("panel")
    assert current is not None
    assert current.registration_identity == dataset.registration_identity
    assert current.query_snapshot is not None


def test_reindex_source_drift_fails_before_registry_pointer_write(tmp_path: Path) -> None:
    project, dataset = register(
        tmp_path,
        "2025-01-01T00:00:00,2025-01-01T01:00:00,A,1,1\n",
    )
    assert dataset.query_snapshot is not None
    registry_path = Path(dataset.query_snapshot.path).parent.parent / "registrations" / "panel.json"
    before = registry_path.read_bytes()
    (project.root / "panel.csv").write_text("drift", encoding="utf-8")

    outcome = project.reindex_datasets(("panel",))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.errors[0].error_code == "DATASET_SOURCE_DRIFT"
    assert registry_path.read_bytes() == before
