from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from qlibx import OutcomeStatus, QlibxProject
from qlibx.data import (
    AvailableAtField,
    ComponentRequirement,
    DatasetRegistration,
    ObservationStore,
    RequirementResolver,
    SourceFormat,
)
from qlibx.runtime import BacktestClock
from qlibx.view import ViewGate

KST = ZoneInfo("Asia/Seoul")


@pytest.mark.parametrize(
    ("session_timezone", "session_date", "expected"),
    [
        ("Asia/Seoul", date(2024, 1, 3), ["SECOND"]),
        ("UTC", date(2024, 1, 2), ["FIRST", "SECOND"]),
        ("UTC", date(2024, 1, 3), []),
    ],
)
def test_session_query_uses_the_declared_calendar_day(
    tmp_path: Path,
    session_timezone: str,
    session_date: date,
    expected: list[str],
) -> None:
    source = tmp_path / "market.csv"
    source.write_text(
        "observation_time,available_at,instrument,value\n"
        "2024-01-02T23:30:00+09:00,2024-01-02T23:30:00+09:00,FIRST,1.0\n"
        "2024-01-03T00:30:00+09:00,2024-01-03T00:30:00+09:00,SECOND,2.0\n",
        encoding="utf-8",
    )
    QlibxProject.init(tmp_path, apply=True)
    project = QlibxProject.open(tmp_path)
    registered = project.register_dataset(
        DatasetRegistration(
            dataset_id="boundary-market",
            source=source.name,
            source_format=SourceFormat.CSV,
            instrument_field="instrument",
            observation_time_field="observation_time",
            available_at=AvailableAtField(field="available_at"),
            logical_key=("observation_time", "available_at", "instrument"),
            semantic_bindings={"decision_return": "value"},
            source_provenance="offset-aware calendar boundary fixture",
        )
    )
    assert registered.status is OutcomeStatus.COMPLETE
    resolution = RequirementResolver().resolve(
        operation="strategy.run",
        idempotency_identity=f"session-{session_timezone}-{session_date}",
        requirements=(
            ComponentRequirement(
                requirement_id="strategy.return",
                semantic_role="decision_return",
                dataset_id="boundary-market",
            ),
        ),
        registry=project.registry_snapshot(),
    )
    assert not resolution.failed
    view = ViewGate(project.registry_snapshot(), ObservationStore()).model_view(
        BacktestClock(datetime(2024, 1, 3, 1, 0, tzinfo=KST)),
        resolution.bindings,
    )

    frame = view.session(
        "decision_return",
        session_date,
        session_timezone=session_timezone,
    )

    assert frame["instrument"].tolist() == expected